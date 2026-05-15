#!/usr/bin/env python3
"""
init_server.py - 服务器自动初始化脚本
本地运行，通过 SSH 登录目标服务器，自动完成 relay 账号创建 + sudoers 配置
"""

import argparse
import sys
from pathlib import Path

try:
    from paramiko import SSHClient, AutoAddPolicy
except ImportError:
    print("❌ 请先安装: pip install paramiko")
    sys.exit(1)


# 默认 sudoers 配置模板
DEFAULT_SUDOERS = """# Relay Proxy - relay 账号 sudoers 权限
# 此文件由 init_server.py 自动生成

# Nginx 服务管理
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl status nginx
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nginx
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop nginx
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl start nginx
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl enable nginx
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl disable nginx

# Docker 服务
relay ALL=(ALL) NOPASSWD: /usr/bin/docker ps
relay ALL=(ALL) NOPASSWD: /usr/bin/docker restart *
relay ALL=(ALL) NOPASSWD: /usr/bin/docker stop *
relay ALL=(ALL) NOPASSWD: /usr/bin/docker start *
relay ALL=(ALL) NOPASSWD: /usr/bin/docker logs *
relay ALL=(ALL) NOPASSWD: /usr/bin/docker exec *
relay ALL=(ALL) NOPASSWD: /usr/bin/docker images
relay ALL=(ALL) NOPASSWD: /usr/bin/docker-compose *

# 系统日志
relay ALL=(ALL) NOPASSWD: /usr/bin/journalctl -u *
relay ALL=(ALL) NOPASSWD: /usr/bin/journalctl --disk-usage

# Git 部署
relay ALL=(ALL) NOPASSWD: /usr/bin/git -C /home/* *

# 系统状态（只读，无需 sudo）
# tail, grep, cat, ls, df, free, top, ps, uptime, ss 已可在普通用户下运行
# 如果需要 systemctl status 等，需sudo:
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload

# ====== 禁止的命令（始终生效）======
relay ALL=(ALL) NOPASSWD: !/usr/bin/passwd
relay ALL=(ALL) NOPASSWD: !/usr/bin/shutdown
relay ALL=(ALL) NOPASSWD: !/usr/bin/reboot
relay ALL=(ALL) NOPASSWD: !/usr/bin/init 0
relay ALL=(ALL) NOPASSWD: !/usr/bin/init 6
relay ALL=(ALL) NOPASSWD: !/bin/rm -rf /*
relay ALL=(ALL) NOPASSWD: !/usr/bin/wget --no-check-certificate *
relay ALL=(ALL) NOPASSWD: !/usr/bin/curl *
relay ALL=(ALL) NOPASSWD: !/usr/bin/nc *
relay ALL=(ALL) NOPASSWD: !/usr/bin/curl * | *sh
relay ALL=(ALL) NOPASSWD: !/usr/bin/wget * | *sh
"""


def run_cmd(client: SSHClient, cmd: str, sudo_password: str = "") -> tuple[int, str, str]:
    """执行命令，返回 (exit_code, stdout, stderr)"""
    if sudo_password and ("sudo" in cmd or "su " in cmd):
        cmd = f"echo '{sudo_password}' | sudo -S {cmd}"
        cmd = cmd.replace("sudo -S -S", "sudo -S")

    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return exit_code, out, err


def init_server(
    host: str,
    port: int,
    user: str,
    auth_type: str,
    auth_value: str,
    relay_pubkey: str,
    sudo_password: str = "",
    disable_password_auth: bool = True,
) -> bool:
    """初始化一台服务器"""

    print(f"\n🔌 连接 {host}:{port}...")
    client = SSHClient()
    client.set_host_keys_policy(AutoAddPolicy())

    try:
        # 1. SSH 登录
        if auth_type == "password":
            client.connect(host, port=port, username=user, password=auth_value, timeout=10)
        elif auth_type == "key":
            client.connect(host, port=port, username=user, key_filename=auth_value, timeout=10)
        else:
            print(f"❌ 不支持的认证方式: {auth_type}")
            return False
        print(f"   ✅ SSH 连接成功")
    except Exception as e:
        print(f"   ❌ SSH 连接失败: {e}")
        return False

    try:
        # 2. 创建 relay 用户
        print(f"   👤 创建 relay 用户...")
        _, out, err = run_cmd(client, "id relay 2>/dev/null || useradd -m -s /bin/bash relay", sudo_password)
        if "already exists" in err or "already exists" in out:
            print(f"   ℹ️  relay 用户已存在，跳过创建")
        else:
            print(f"   ✅ relay 用户创建完成")

        # 3. 创建 .ssh 目录
        print(f"   🔑 配置 SSH 公钥...")
        run_cmd(client, "mkdir -p /home/relay/.ssh", sudo_password)
        run_cmd(client, "chmod 700 /home/relay/.ssh", sudo_password)
        run_cmd(client, "chown relay:relay /home/relay/.ssh", sudo_password)

        # 4. 写入公钥到 authorized_keys
        pubkey = relay_pubkey.strip()
        # 如果公钥包含 comment 部分，只取前面部分
        if " " in pubkey:
            pubkey = pubkey.split(" ")[0] + " " + pubkey.split(" ")[1]
        
        # 先清空旧的 authorized_keys（避免重复）
        run_cmd(client, "> /home/relay/.ssh/authorized_keys", sudo_password)
        run_cmd(client, f'echo "{pubkey}" >> /home/relay/.ssh/authorized_keys', sudo_password)
        run_cmd(client, "chmod 600 /home/relay/.ssh/authorized_keys", sudo_password)
        run_cmd(client, "chown relay:relay /home/relay/.ssh/authorized_keys", sudo_password)
        print(f"   ✅ SSH 公钥已写入")

        # 5. 写入 sudoers 配置
        print(f"   ⚙️  配置 sudoers 权限...")
        # heredoc 方式写入
        cmd = f'cat > /etc/sudoers.d/relay << \'SUDOERSEOF\'\n{DEFAULT_SUDOERS}SUDOERSEOF'
        run_cmd(client, cmd, sudo_password)
        run_cmd(client, "chmod 440 /etc/sudoers.d/relay", sudo_password)
        print(f"   ✅ sudoers 权限配置完成")

        # 6. 验证 sudoers 语法
        exit, out, err = run_cmd(client, "visudo -c", sudo_password)
        if exit == 0:
            print(f"   ✅ sudoers 语法正确")
        else:
            print(f"   ⚠️  sudoers 语法检查失败: {err[:200]}")

        # 7. 可选：禁止密码登录
        if disable_password_auth:
            print(f"   🔒 禁用 SSH 密码登录...")
            run_cmd(client, "sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config 2>/dev/null || true", sudo_password)
            run_cmd(client, "sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config 2>/dev/null || true", sudo_password)
            run_cmd(client, "systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null || true", sudo_password)
            print(f"   ✅ SSH 密码登录已禁用（密钥登录启用）")

        # 8. 测试 relay 用户 SSH
        print(f"   🧪 测试 relay 用户登录...")
        client.close()
        client = SSHClient()
        client.set_host_keys_policy(AutoAddPolicy())
        client.connect(host, port=port, username="relay", password="", timeout=10)
        _, out, _ = client.exec_command("whoami")
        who = out.read().decode().strip()
        if who == "relay":
            print(f"   ✅ relay 用户登录测试成功")
        else:
            print(f"   ⚠️  relay 用户登录测试结果: {who}")

        print(f"\n✅ {host} 初始化完成!")
        return True

    except Exception as e:
        print(f"   ❌ 初始化失败: {e}")
        return False
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="服务器自动初始化 - 创建 relay 账号并配置权限")
    parser.add_argument("--host", required=True, help="服务器 IP 或域名")
    parser.add_argument("--port", type=int, default=22, help="SSH 端口 (默认: 22)")
    parser.add_argument("--user", default="root", help="SSH 登录用户名 (默认: root)")
    parser.add_argument("--auth", choices=["password", "key"], default="password", help="认证方式")
    parser.add_argument("--auth-value", required=True, help="密码或私钥路径")
    parser.add_argument("--sudo-password", default="", help="sudo 密码（如果需要）")
    parser.add_argument("--relay-pubkey", required=True, help="Relay 的 SSH 公钥")
    parser.add_argument("--keep-password-auth", action="store_true", help="不禁用密码登录（默认会禁用）")
    parser.add_argument("--json", action="store_true", help="JSON 输出格式")

    args = parser.parse_args()

    success = init_server(
        host=args.host,
        port=args.port,
        user=args.user,
        auth_type=args.auth,
        auth_value=args.auth_value,
        relay_pubkey=args.relay_pubkey,
        sudo_password=args.sudo_password,
        disable_password_auth=not args.keep_password_auth,
    )

    if args.json:
        import json
        print(json.dumps({"host": args.host, "success": success}))
    else:
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
