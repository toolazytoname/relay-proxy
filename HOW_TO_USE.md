# 完整使用指南

> 从零开始，一步步把 Relay Proxy 用起来。

---

## 目录

1. [它解决什么问题](#1-它解决什么问题)
2. [架构一览](#2-架构一览)
3. [快速体验（30分钟跑通）](#3-快速体验30分钟跑通)
4. [初始化 Linux 服务器](#4-初始化-linux-服务器)
5. [配置权限清单](#5-配置权限清单)
6. [Hermes Agent 集成](#6-hermes-agent-集成)
7. [手机管理（iOS Shortcut）](#7-手机管理ios-shortcut)
8. [日常使用命令](#8-日常使用命令)
9. [安全检查清单](#9-安全检查清单)
10. [常见问题](#10-常见问题)

---

## 1. 它解决什么问题

**场景**：你想让 AI Agent（Hermes）帮你操作 Linux 服务器，但你不想把服务器密码交给它。

**传统方案的问题**：
- 把密码给 Agent → Agent 可以做任何事（删库、格盘...）
- 密码泄露 → 不知道谁用过、做了什么
- 想收回权限 → 改密码，但所有需要密码的人都得重新配

**Relay Proxy 的方案**：
```
Agent → Relay Server（HTTPS，有管理界面）→ 服务器（只认 SSH Key）
         ↓
    会话制度：Agent 每次请求生成临时 Key
    权限清单：Agent 只能做清单里的事
    审计日志：所有操作都有记录
    一键撤销：立刻失效，Key 变废纸
```

---

## 2. 架构一览

```
┌────────────────┐     HTTPS      ┌────────────────┐    SSH/Key     ┌───────────────┐
│  Hermes Agent  │ ───────────── → │  Relay Server  │ ──────────── → │  Linux Server │
│  (你让ta干活)   │   无密码接触     │  (你的云服务器)   │   临时会话Key  │  (要管理的机器) │
└────────────────┘                └────────────────┘                └───────────────┘
```

**组件说明**：

| 组件 | 作用 | 托管方式 |
|------|------|----------|
| Hermes Agent | AI Agent（Claude 等） | 本地/云端 |
| Relay Server | 命令转发 + 权限控制 | 自托管（见下文） |
| Linux Server | 实际执行命令 | 你的服务器 |

---

## 3. 快速体验（30分钟跑通）

### 步骤 1：部署 Relay Server

**方式A：Docker 部署（推荐）**

```bash
docker build -t relay-proxy .
docker run -d \
  --name relay-proxy \
  -e ADMIN_TOKEN=your-admin-token \
  -e LOG_DIR=/data/logs \
  -v /path/to/keys:/data/keys:ro \
  -v /path/to/config:/data/config:ro \
  -v /path/to/data:/data \
  -p 8000:8000 \
  relay-proxy
```

**方式B：systemd 部署（生产环境）**

```bash
# 复制服务文件
sudo cp deploy/systemd/relay-proxy.service /etc/systemd/system/

# 编辑配置
sudo vim /etc/relay-proxy/config.env  # 设置环境变量

# 启动
sudo systemctl enable relay-proxy
sudo systemctl start relay-proxy
```

详细步骤见 [DEPLOY_SELF_HOSTED.md](DEPLOY_SELF_HOSTED.md)

### 步骤 2：配置环境变量

```bash
# 管理 Token（必填）
ADMIN_TOKEN=your-secure-token

# 日志目录（可选，默认 /opt/relay-proxy/logs）
LOG_DIR=/data/logs

# 权限清单路径（可选）
MANIFEST_PATH=/data/config/permission_manifest.yaml

# SSH 私钥（从环境变量加载，每服务器一个）
SSH_KEY_WEB_1=-----BEGIN OPENSSH PRIVATE KEY-----
SSH_KEY_DB_1=-----BEGIN OPENSSH PRIVATE KEY-----
```

### 步骤 3：配置权限清单

```bash
mkdir -p /data/config
vim /data/config/permission_manifest.yaml
```

示例配置：
```yaml
version: "1.0"
default_policy:
  readonly: false
  allowed_commands:
    - docker ps
    - docker logs
    - echo
    - ls
    - cat
servers:
  - name: web-1
    host: 1.2.3.4
    user: relay
    policy:
      allowed_commands:
        - docker ps
        - docker logs
        - docker-compose ps
```

---

## 4. 初始化 Linux 服务器

### 方式一：用脚本初始化（推荐）

```bash
python scripts/init_server.py \
  --host 1.2.3.4 \
  --user root \
  --password "xxx" \
  --relay-user relay \
  --ssh-key ~/.ssh/id_ed25519.pub
```

脚本会自动：
- 创建 `relay` 用户
- 配置 sudoers（无密码 sudo 仅限白名单命令）
- 写入 authorized_keys

### 方式二：手动初始化

登录服务器，手动执行：

```bash
# 1. 创建 relay 用户
useradd -m -s /bin/bash relay

# 2. relay 的 sudoers（仅允许特定命令）
echo "relay ALL=(ALL) NOPASSWD: /usr/bin/docker, /usr/bin/docker-compose, /usr/bin/systemctl status *, /usr/bin/tail" > /etc/sudoers.d/relay

# 3. 加入 docker 组（如果需要）
usermod -aG docker relay

# 4. 写入公钥（Relay Server 的公钥）
mkdir -p /home/relay/.ssh
echo "ssh-ed25519 AAAA... relay-proxy" >> /home/relay/.ssh/authorized_keys
chown -R relay:relay /home/relay/.ssh
chmod 600 /home/relay/.ssh/authorized_keys
```

---

## 5. 配置权限清单

### 5.1 清单结构

```yaml
version: "1.0"

# 默认策略
default_policy:
  readonly: false
  allowed_commands:
    - docker ps
    - docker logs
    - echo
    - ls
    - pwd
    - whoami

# 服务器列表
servers:
  - name: web-1              # 服务器标识
    host: 1.2.3.4            # IP 或域名
    user: relay              # SSH 用户
    port: 22                 # SSH 端口（默认22）
    policy:
      readonly: false        # true = 只读模式
      allowed_commands:     # 白名单命令
        - docker ps
        - docker logs
        - docker-compose ps
      denied_commands:      # 黑名单命令（优先级高于白名单）
        - rm -rf /
        - dd if=
        - ">:(){ :|:& };:"  # fork bomb
      allowed_paths:        # 允许访问的路径
        - /var/log/*
        - /home/*/logs/*
      denied_paths:         # 禁止访问的路径
        - /etc/shadow
        - /root/.ssh/*
      sudo_commands:        # 需要 sudo 的命令
        - systemctl restart docker
        - docker restart *
```

### 5.2 命令级 vs 路径级权限

| 类型 | 说明 | 示例 |
|------|------|------|
| 命令级 | 允许/禁止特定命令 | `allowed_commands: [docker ps]` |
| 路径级 | 允许/禁止访问特定路径 | `allowed_paths: [/var/log/*]` |
| sudo级 | 需要 sudo 才能执行的命令 | `sudo_commands: [systemctl restart *]` |

### 5.3 只读模式

```yaml
servers:
  - name: web-1
    policy:
      readonly: true  # 禁止写入操作（rm, mv, dd 等）
```

---

## 6. Hermes Agent 集成

### 6.1 安装 Hermes Tool

```python
from hermes_tool import RelayProxyTool

relay = RelayProxyTool(
    relay_url="https://your-relay.example.com",
    admin_token="your-admin-token"
)
```

### 6.2 执行命令

```python
# 执行单个命令
result = relay.exec_command("web-1", "docker ps")
print(result.output)
print(result.exit_code)

# 绑定 session（可选）
result = relay.exec_command("web-1", "docker ps", session_id="your-session-id")
```

### 6.3 管理会话

```python
# 列出活跃会话
sessions = relay.list_sessions()
for s in sessions:
    print(f"{s.session_id}: {s.agent_id} on {s.scope}")

# 撤销单个会话
relay.revoke_session("sess_abc123")

# 撤销所有会话
relay.revoke_all()
```

### 6.4 审计查询

```python
# 查询审计日志
logs = relay.query_audit(limit=20)
for log in logs:
    print(f"{log.timestamp} {log.status} {log.command_checked}")

# 按会话查询
logs = relay.query_audit(session_id="sess_abc123")

# 按服务器查询
logs = relay.query_audit(server="web-1", status="denied")
```

---

## 7. 手机管理（iOS Shortcut）

详见 [shortcuts/IMPORT_GUIDE.md](shortcuts/IMPORT_GUIDE.md)

| 触发词 | 作用 |
|--------|------|
| Siri：Relay状态 | 查看活跃会话 |
| Siri：Relay切断 | 撤销所有Agent会话 |
| Siri：Relay审计 | 查询审计记录 |

---

## 8. 日常使用命令

### CLI 管理工具

```bash
export RELAY_URL=https://your-relay.example.com
export ADMIN_TOKEN=your-admin-token

# 查看活跃会话
python3 cli_admin.py sessions list

# 撤销指定会话
python3 cli_admin.py sessions revoke sess_abc123

# 撤销所有会话
python3 cli_admin.py sessions revoke --all

# 查询审计日志
python3 cli_admin.py audit query --limit 20
python3 cli_admin.py audit query --server web-1 --status denied

# 预检命令权限
python3 cli_admin.py permissions check --server web-1 --command "docker ps"
```

---

## 9. 安全检查清单

- [ ] ADMIN_TOKEN 足够复杂（32位以上随机字符串）
- [ ] SSH 私钥已注册到 Relay Server
- [ ] 权限清单中 denied_commands 包含危险命令
- [ ] 服务器上 relay 用户 sudoers 已正确配置
- [ ] 审计日志定期检查（至少每周）
- [ ] ADMIN_TOKEN 定期轮换（建议每月）

---

## 10. 常见问题

**Q: Agent 执行命令报 403 Forbidden**
A: 命令不在权限清单中，检查 `permission_manifest.yaml`

**Q: SSH 连接失败**
A: 检查服务器防火墙、SSH 端口、relay 用户公钥是否正确

**Q: 如何查看历史操作记录？**
A: `python cli_admin.py audit query --session_id <id>` 或查看审计日志目录