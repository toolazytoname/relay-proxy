# 完整使用指南

> 从零开始，一步步把 Relay Proxy 用起来。

---

## 目录

1. [它解决什么问题](#1-它解决什么问题)
2. [架构一览](#2-架构一览)
3. [快速体验（30分钟跑通）](#3-快速体验30分钟跑通)
4. [Fly.io 部署](#4-flyio-部署)
5. [初始化 Linux 服务器](#5-初始化-linux-服务器)
6. [配置权限清单](#6-配置权限清单)
7. [Hermes Agent 集成](#7-hermes-agent-集成)
8. [手机管理（iOS Shortcut）](#8-手机管理ios-shortcut)
9. [日常使用命令](#9-日常使用命令)
10. [安全检查清单](#10-安全检查清单)
11. [常见问题](#11-常见问题)

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
                                           │
                              ┌────────────┴────────────┐
                              │  会话管理   权限引擎  审计日志 │
                              │  即时撤销    最小授权   完整记录 │
                              └─────────────────────────┘
```

---

## 3. 快速体验（30分钟跑通）

### 前置准备

- 一台可访问的 Linux 服务器（root 密码）
- 本地 Python 3.8+
- GitHub 账号

### 3.1 克隆代码

```bash
git clone https://github.com/toolazytoname/relay-proxy.git
cd relay-proxy
```

### 3.2 本地运行 Relay Server（开发模式）

```bash
# 安装依赖
pip install -r requirements.txt

# 生成临时管理 Token（开发用）
export ADMIN_TOKEN=dev-secret-token
export LOG_LEVEL=debug

# 启动服务
python -m uvicorn src.main:app --reload --port 8000

# 新终端验证
curl http://localhost:8000/health
# 返回: {"status":"ok"}
```

### 3.3 配置第一台服务器

```bash
# 在另一个终端，初始化你的服务器（创建 relay 账号）
python scripts/init_server.py \
  --host 1.2.3.4 \
  --port 22 \
  --user root \
  --password "你的服务器密码" \
  --relay-user relay
```

> **这个命令做了什么**：
> 1. 在服务器创建 `relay` 用户
> 2. 把 relay 的公钥加入 `authorized_keys`（Relay Server 用这个 Key 连接）
> 3. relay 用户加入 sudoers（可执行特定命令）

### 3.4 生成 SSH 密钥

```bash
python scripts/generate_ssh_keys.py
# 生成: keys/<server-name>_ed25519 和 .pub
```

### 3.5 配置权限清单

编辑 `config/permission_manifest.yaml`：

```yaml
servers:
  - name: my-server
    host: 1.2.3.4
    user: relay
    policy:
      allowed_commands:
        - docker ps
        - docker logs
        - tail /var/log/nginx/*.log
        - df -h
        - free -h
        - ps aux
      denied_commands:
        - rm -rf /
        - dd if=
        - ":(){ :|:& };:"
```

### 3.6 测试执行

```bash
# 通过 Relay 执行命令
curl -X POST http://localhost:8000/api/v1/exec \
  -H "Authorization: Bearer dev-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"server":"my-server","command":"uptime"}'
```

成功返回：

```json
{
  "session_id": "sess_abc123",
  "output": " 19:30:00 up 30 days, 3 users, load average: 0.52, 0.58, 0.59",
  "exit_code": 0,
  "status": "success",
  "audit_id": "aud_xyz789"
}
```

---

## 4. Fly.io 部署

### 4.1 注册 Fly.io

1. https://fly.io/signup（可用 GitHub 账号）
2. 安装 CLI：
   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```

### 4.2 初始化项目

```bash
cd relay-proxy
fly launch
# 按提示选择：
#   App name: relay-proxy（或其他）
#   Region: 选择离你最近的（sin=新加坡, hkg=香港）
#   Would you like to allocate a dedicated IP? No（以后再加）
```

### 4.3 配置 Secrets

```bash
# 管理 Token（必填）
fly secrets set ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 服务器 SSH 私钥（每个服务器一个 secret）
fly secrets set SSH_KEY_MY_SERVER="$(cat keys/my-server_ed25519)"

# 可选：日志级别
fly secrets set LOG_LEVEL=info
```

### 4.4 挂载权限清单（方式一：直接写入 secret）

```bash
fly secrets set PERMISSION_MANIFEST="$(cat config/permission_manifest.yaml | base64)"
```

### 4.5 挂载权限清单（方式二：持久存储卷）

```bash
# 创建持久卷
fly volumes create relay_data --region sin --size 1

# 在 fly.toml 中添加挂载（自动处理）
```

### 4.6 部署

```bash
fly deploy
```

### 4.7 验证

```bash
# 查看状态
fly status

# 查看日志
fly logs

# 测试健康检查
curl https://your-app-name.fly.dev/health
```

---

## 5. 初始化 Linux 服务器

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

## 6. 配置权限清单

### 6.1 清单结构

```yaml
version: "1.0"

# 默认策略（所有服务器的兜底规则）
default_policy:
  readonly: false
  allowed_commands:
    - ls
    - cat
    - echo
    - hostname
  denied_commands:
    - "rm -rf /"
    - "dd if="
  denied_paths:
    - /etc/shadow
    - /root/.ssh/*

# 服务器列表
servers:
  - name: web-1              # 唯一标识
    host: 1.2.3.4
    port: 22
    user: relay
    policy:                  # 覆盖默认策略
      allowed_commands:
        - docker ps
        - docker logs
        - docker-compose ps
        - tail /var/log/nginx/*.log
        - ps aux
        - df -h
      sudo_commands:
        - "docker restart *"
        - "docker stop *"
```

### 6.2 策略说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `allowed_commands` | 白名单命令 | `["docker ps", "tail /var/log/*"]` |
| `denied_commands` | 黑名单命令（优先于白名单） | `["rm -rf /", "dd if="]` |
| `sudo_commands` | 需要 sudo 的命令 | `["systemctl restart nginx"]` |
| `allowed_paths` | 允许访问的路径 | `["/var/log/*", "/home/*/data/*"]` |
| `denied_paths` | 禁止访问的路径 | `["/etc/shadow", "/root/.ssh/*"]` |
| `readonly` | true=禁止写入命令 | `rm`, `mv`, `dd` 自动拦截 |

### 6.3 自然语言意图映射

Agent 说中文也能理解：

| Agent 说 | 自动解析为 |
|---------|-----------|
| "帮我看看服务器状态" | `uptime && df -h && free -h` |
| "查看 Docker 容器" | `docker ps` |
| "看看 Nginx 日志" | `tail /var/log/nginx/access.log` |
| "重启 Nginx" | `sudo systemctl restart nginx` |

---

## 7. Hermes Agent 集成

### 7.1 配置环境变量

在 Hermes 的运行环境设置：

```bash
export RELAY_URL=https://your-app.fly.dev
export ADMIN_TOKEN=your_admin_token
```

### 7.2 在代码中使用

```python
from hermes_tool import RelayProxyTool

relay = RelayProxyTool(
    relay_url=os.environ.get("RELAY_URL"),
    admin_token=os.environ.get("ADMIN_TOKEN"),
)

# 执行命令
result = relay.exec_command("web-1", "docker ps")
print(result.output)

# 查看会话列表
sessions = relay.list_sessions()
for s in sessions:
    print(f"  {s.session_id} - {s.server} - {s.status}")

# 撤销某个会话
relay.revoke_session("sess_abc123")
```

### 7.3 权限预检

不确定某个命令能不能执行？先问：

```python
check = relay.check_permission("web-1", "docker-compose up -d")
if check["allowed"]:
    result = relay.exec_command("web-1", "docker-compose up -d")
else:
    print(f"不允许: {check['reason']}")
    print(f"建议: {check.get('suggestion', {})}")
```

### 7.4 自然语言驱动

```python
# Agent 直接说需求，Relay 自动解析
result = relay.exec_command("web-1", "帮我看看服务器状态")
print(result.output)  # 自动执行 uptime && df -h && free -h
```

---

## 8. 手机管理（iOS Shortcut）

### 8.1 导入快捷指令

1. 复制 `shortcuts/RELAY_STATUS.json` 内容
2. iPhone → Shortcuts App → + → 导入快捷指令
3. 粘贴内容
4. 替换 `${RELAY_ADMIN_TOKEN}` 为真实 Token

### 8.2 快捷指令列表

| 触发词（Siri） | 作用 |
|-------------|------|
| "Relay状态" | 查看所有活跃会话 |
| "Relay切断" | 一键撤销所有会话 |
| "Relay审计" | 查询最近审计记录 |

### 8.3 自定义

打开 Shortcuts → 编辑 → 替换占位符：
- `${RELAY_ADMIN_TOKEN}` → 你的 ADMIN_TOKEN
- `placeholder-relay.fly.dev` → 你的 Relay Server 地址

---

## 9. 日常使用命令

### 9.1 管理 CLI

```bash
# 配置环境变量
export RELAY_URL=https://your-app.fly.dev
export ADMIN_TOKEN=xxx

# 查看活跃会话
python cli_admin.py sessions list

# 撤销指定会话
python cli_admin.py sessions revoke sess_abc123

# 撤销所有会话（紧急情况）
python cli_admin.py sessions revoke --all

# 查询审计记录
python cli_admin.py audit query --limit 20

# 按会话查
python cli_admin.py audit query --session_id sess_abc123

# 按服务器查
python cli_admin.py audit query --server web-1

# 查看审计详情
python cli_admin.py audit get aud_xyz789

# 权限预检
python cli_admin.py permissions check --server web-1 --command "docker ps"

# 查看完整权限清单
python cli_admin.py permissions manifest
```

### 9.2 日志导出

```bash
# 导出某天的审计日志
python -c "
from src.audit_logger import AuditLogger
from pathlib import Path
logger = AuditLogger()
count = logger.export('2025-05-15', '2025-05-15', Path('/tmp/audit_export.jsonl'))
print(f'导出 {count} 条记录')
"
```

---

## 10. 安全检查清单

部署完成后，确认以下各项：

- [ ] ADMIN_TOKEN 已设置（不在代码里）
- [ ] 所有 SSH 私钥通过 Fly.io Secrets 注入
- [ ] 服务器 relay 账号不是 root
- [ ] `permission_manifest.yaml` 配置了 `denied_commands`
- [ ] 测试 `rm -rf /` 确认被拦截
- [ ] iOS Shortcut 里的 ADMIN_TOKEN 已替换
- [ ] `cli_admin.py` 的环境变量已配置
- [ ] 确认 Fly.io 部署用 HTTPS（自动启用）
- [ ] 定期：`python cli_admin.py sessions revoke --all` 后重建会话

---

## 11. 常见问题

### Q: Agent 说"权限不足"
A: 在 `permission_manifest.yaml` 的 `allowed_commands` 里添加对应命令，然后 `fly deploy`。

### Q: 会话过期了怎么办？
A: Agent 会自动申请新会话，或者 `relay.create_session(server)` 手动创建一个。

### Q: 想临时开放一个新命令
A: 运行 `python cli_admin.py permissions check --server web-1 --command "xxx"` 先预检，确认允许后再让 Agent 执行。

### Q: 服务器 SSH 密码要换怎么办？
A: 重新运行 `init_server.py`，传入新密码。Relay Server 会用新的 Key 连接，旧 Key 自动失效。

### Q: 想看 Agent 到底做了什么
A: `python cli_admin.py audit query --session_id <id>` 或在 Fly.io 日志里 `fly logs`。

### Q: 如何停止 Relay Server？
A: `fly scale count 0`（暂停），`fly destroy`（删除）。

---

## 快速参考卡

```
┌─────────────────────────────────────────────────────┐
│                    Relay Proxy 快速参考              │
├─────────────────────────────────────────────────────┤
│ 部署地址   : fly launch / fly deploy                │
│ 健康检查   : curl https://xxx.fly.dev/health         │
│ 查看会话   : python cli_admin.py sessions list      │
│ 撤销所有   : python cli_admin.py sessions revoke --all│
│ 查询审计   : python cli_admin.py audit query        │
│ 权限预检   : python cli_admin.py permissions check   │
│ 查看日志   : fly logs                               │
│ 停止服务   : fly scale count 0                      │
└─────────────────────────────────────────────────────┘
```
