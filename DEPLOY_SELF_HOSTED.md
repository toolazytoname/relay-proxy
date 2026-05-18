# 自托管部署指南（Debian/Ubuntu）

> 把 Relay Proxy 部署在你自己的 Linux 服务器上，完全免费，没有平台限制。

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 系统 | Debian 11+ / Ubuntu 20.04+ |
| 内存 | ≥ 512MB |
| 磁盘 | ≥ 2GB |
| 网络 | 公网 IP（用于 Agent 访问） |

---

## 方式一：一键脚本（推荐）

### 步骤 1：SSH 登录服务器

```bash
ssh root@你的服务器IP
```

### 步骤 2：运行部署脚本

```bash
# 在服务器上执行（需要 sudo 权限）
curl -fsSL https://raw.githubusercontent.com/toolazytoname/relay-proxy/main/scripts/deploy_to_server.sh | bash
```

或本地执行：

```bash
scp -r /tmp/relay-proxy root@你的服务器IP:/tmp/
ssh root@你的服务器IP "bash /tmp/relay-proxy/scripts/deploy_to_server.sh"
```

脚本会自动：
- 创建 `relay` 系统用户
- 克隆代码到 `/opt/relay-proxy`
- 创建 Python 虚拟环境
- 安装依赖
- 配置 systemd service
- 启动服务

### 步骤 3：记录 ADMIN_TOKEN

脚本会自动生成并显示 `ADMIN_TOKEN`，**请务必记录下来**。

如需重新查看：
```bash
sudo systemctl cat relay-proxy | grep ADMIN_TOKEN
```

---

## 方式二：手动部署

### 1. 安装依赖

```bash
apt update && apt install -y python3 python3-pip git
```

### 2. 克隆代码

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/toolazytoname/relay-proxy.git
cd relay-proxy
```

### 3. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. 配置环境变量

```bash
cat > /opt/relay-proxy/.env << 'EOF'
ADMIN_TOKEN=你的管理Token（自己生成）
MANIFEST_PATH=/opt/relay-proxy/config/permission_manifest.yaml
LOG_DIR=/opt/relay-proxy/logs
TOKEN_STORE_PATH=/opt/relay-proxy/tokens.jsonl
EOF
chmod 600 /opt/relay-proxy/.env
chown -R relay:relay /opt/relay-proxy
```

### 5. 安装 systemd service

```bash
cp deploy/systemd/relay-proxy.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable relay-proxy
systemctl start relay-proxy
```

### 6. 验证

```bash
curl http://localhost:8000/health
# 返回: {"status":"ok","version":"1.0.0"}
```

---

## 配置权限清单

编辑 `/opt/relay-proxy/config/permission_manifest.yaml`，添加你的服务器：

```yaml
version: "1.0"
servers:
  - name: my-server
    host: 127.0.0.1
    user: relay
    policy:
      allowed_commands:
        - docker ps
        - docker logs
        - df -h
        - free -h
      denied_commands:
        - rm -rf /
        - dd if=
```

修改后重启生效：
```bash
sudo systemctl restart relay-proxy
```

---

## 初始化 Linux 服务器（被管理端）

在**你自己的本地机器**上执行（不是 Relay Server）：

```bash
cd relay-proxy
pip install paramiko

python3 scripts/init_server.py \
  --host 你的服务器IP \
  --user root \
  --password 你的服务器密码
```

> 脚本会用 SSH 登录服务器，创建 `relay` 用户并注入公钥。初始化完成后，**服务器密码可以丢弃**，后续 Agent 用 SSH Key 认证。

---

## 生成 SSH 密钥

```bash
cd relay-proxy
python3 scripts/generate_ssh_keys.py
# 生成 keys/my-server_ed25519 和 .pub
```

把私钥内容添加到 `/opt/relay-proxy/.env`：

```bash
# 查看私钥
cat keys/my-server_ed25519

# 写入 .env（单行）
echo "SSH_KEY_MY_SERVER=$(cat keys/my-server_ed25519)" >> /opt/relay-proxy/.env
```

重启服务：
```bash
sudo systemctl restart relay-proxy
```

---

## Nginx 反向代理（HTTPS）

生产环境建议用 Nginx + HTTPS：

```nginx
server {
    listen 443 ssl;
    server_name relay.yourdomain.com;

    ssl_certificate /etc/ssl/certs/your cert.pem;
    ssl_certificate_key /etc/ssl/private/your key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300;
    }
}
```

启用并重启 Nginx：
```bash
systemctl enable nginx
systemctl restart nginx
```

---

## 管理命令

```bash
# 服务控制
sudo systemctl start   relay-proxy   # 启动
sudo systemctl stop    relay-proxy   # 停止
sudo systemctl restart relay-proxy   # 重启
sudo systemctl status  relay-proxy   # 状态

# 查看日志
sudo journalctl -u relay-proxy -f     # 实时日志
sudo journalctl -u relay-proxy -n 50  # 最近50行

# 配置文件
/opt/relay-proxy/.env                        # 环境变量
/opt/relay-proxy/config/permission_manifest.yaml  # 权限清单
/opt/relay-proxy/logs/                       # 审计日志
```

---

## 更新部署

```bash
cd /opt/relay-proxy
sudo git pull
sudo systemctl restart relay-proxy
```

---

## 防火墙配置

确保 Relay Server 的 8000 端口可被 Agent 访问：

```bash
# 开放 8000 端口（仅限 Agent IP，建议限制来源）
ufw allow from Agent_IP to any port 8000

# 或者如果用 Nginx 代理，开放 443
ufw allow 443/tcp
```

---

## 故障排查

### 服务启动失败
```bash
sudo journalctl -u relay-proxy -n 50
```

### 权限不足
```bash
# 检查 relay 用户对目录的权限
ls -la /opt/relay-proxy

# 修复
sudo chown -R relay:relay /opt/relay-proxy
```

### Agent 无法连接
```bash
# 检查端口是否监听
curl http://localhost:8000/health

# 检查防火墙
ufw status
```

---

## 目录结构

```
/opt/relay-proxy/
├── src/                  # 源代码
├── tests/                # 测试用例
├── scripts/              # 工具脚本
│   ├── init_server.py    # 服务器初始化
│   ├── generate_ssh_keys.py
│   └── deploy_to_server.sh  # 一键部署
├── config/
│   └── permission_manifest.yaml  # 权限清单
├── deploy/
│   └── systemd/
│       └── relay-proxy.service    # systemd 配置
├── .venv/                # Python 虚拟环境
├── .env                  # 环境变量（密钥）
├── logs/                 # 审计日志
└── tokens/               # Token 存储
```