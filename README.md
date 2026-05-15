# Relay Proxy

> Agent SSH Relay — 给 AI Agent 赋予 Linux 服务器操作能力，同时保持最小权限 + 完整审计。

**核心问题**：Agent 需要操作服务器，但你不想把 root 密码交给它。
**解法**：Agent 只跟 Relay Server 说话，Relay Server 用临时凭证连接服务器，所有操作都有记录，随时可撤销。

[![GitHub stars](https://img.shields.io/github/stars/toolazytoname/relay-proxy)](https://github.com/toolazytoname/relay-proxy)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 架构

```
┌─────────────┐      HTTPS       ┌──────────────┐      SSH       ┌─────────────┐
│  Hermes     │ ──────────────── │   Relay      │ ────────────── │  Linux      │
│  Agent      │   无服务器密码     │   Server     │   临时Key      │  Server     │
└─────────────┘                  └──────────────┘               └─────────────┘
                                        │
                                 ┌──────┴──────┐
                                 │  会话管理    │ ← 一键撤销，立刻失效
                                 │  审计日志    │ ← 完整决策链
                                 │  权限引擎   │ ← 最小授权
                                 └─────────────┘
```

---

## 特性

- 🔐 **最小权限** — 每个 Agent 会话只有临时 SSH Key，只能做你允许的事
- ⚡ **即时撤销** — 一键收回，Agent 下次调用立刻 403
- 📋 **完整审计** — 谁、什么时候、做了什么、耗时多久，全部记录
- 🧠 **意图映射** — Agent 说"帮我看看服务器状态"，自动解析为 `uptime && df -h`
- 🔍 **权限预检** — 不确定的命令可以先问再执行
- 📱 **管理CLI** — 手机上也能查日志、撤销会话（配合 iOS Shortcuts）
- 📱 **手机快捷指令** — Siri 一句话查看状态、撤销会话、查审计

---

## 文档目录

| 文档 | 内容 |
|------|------|
| [DEPLOY.md](DEPLOY.md) | Fly.io 部署完整步骤 |
| [PRIVACY.md](PRIVACY.md) | 密钥安全与隐私保护 |
| [shortcuts/](shortcuts/) | iOS Shortcut 快捷指令 |

---

## 快速开始

### 1. 部署 Relay Server

```bash
# 方式A：Fly.io 一键部署（推荐）
git clone https://github.com/toolazytoname/relay-proxy.git
cd relay-proxy
FLY_API_TOKEN=xxx ./scripts/setup_all.sh

# 方式B：Docker 手动部署
docker build -t relay-proxy .
docker run -e ADMIN_TOKEN=xxx -p 8000:8000 relay-proxy
```

详细步骤见 [DEPLOY.md](DEPLOY.md)

### 2. 初始化服务器

```bash
# 生成 SSH 密钥对（每台服务器独立）
python3 scripts/generate_ssh_keys.py

# 初始化服务器（创建 relay 账号，注入公钥）
python3 scripts/init_server.py --host 1.2.3.4 --user root --password xxx
```

### 3. 配置权限清单

编辑 `config/permission_manifest.yaml`，定义每个服务器允许执行的命令。

### 4. Agent 调用

```python
from hermes_tool import RelayProxyTool

relay = RelayProxyTool(
    relay_url="https://your-relay.fly.dev",
    admin_token="xxx"
)

# 执行命令
result = relay.exec_command("web-1", "docker ps")
print(result.output)

# 撤销会话
relay.revoke_session(result.session_id)
```

---

## CLI 管理工具

```bash
export RELAY_URL=https://your-relay.fly.dev
export ADMIN_TOKEN=xxx

# 查看活跃会话
python3 cli_admin.py sessions list

# 撤销指定会话
python3 cli_admin.py sessions revoke sess_abc123

# 查询审计日志
python3 cli_admin.py audit query --limit 20

# 预检命令权限
python3 cli_admin.py permissions check --server web-1 --command "docker ps"
```

---

## iOS 快捷指令

详见 [shortcuts/IMPORT_GUIDE.md](shortcuts/IMPORT_GUIDE.md)

| 触发词 | 作用 |
|--------|------|
| Siri：Relay状态 | 查看活跃会话 |
| Siri：Relay切断 | 撤销所有Agent会话 |
| Siri：Relay审计 | 查询审计记录 |

---

## 权限清单示例

```yaml
version: "1.0"
servers:
  - name: web-1
    host: 1.2.3.4
    user: relay
    policy:
      readonly: false
      allowed_commands:
        - docker ps
        - docker logs
        - docker-compose ps
        - tail /var/log/nginx/*.log
      denied_commands:
        - rm -rf /
        - dd if=
        - ">:(){ :|:& };:"
      allowed_paths:
        - /var/log/*
        - /home/*/logs/*
      denied_paths:
        - /etc/shadow
        - /root/.ssh/*
```

---

## 审计日志格式

```json
{
  "audit_id": "aud_abc123",
  "timestamp": "2025-05-15T19:30:00+08:00",
  "session_id": "sess_xxx",
  "server": "web-1",
  "command": "docker ps",
  "intent_resolved": null,
  "exit_code": 0,
  "duration_ms": 234,
  "status": "success",
  "permission_check": {
    "allowed": true,
    "policy_matched": "docker_manager"
  }
}
```

> **隐私说明**：审计日志记录命令内容，但**不记录命令输出**，保护服务器敏感数据。详见 [PRIVACY.md](PRIVACY.md)

---

## 目录结构

```
relay-proxy/
├── src/
│   ├── main.py              # FastAPI 主入口
│   ├── auth.py               # Token + 会话管理
│   ├── permission_engine.py  # 权限引擎 + 意图映射
│   ├── ssh_client.py         # SSH 连接池
│   ├── audit_logger.py       # 审计日志
│   └── hermes_tool.py        # Hermes Agent 接口封装
├── scripts/
│   ├── init_server.py        # 服务器初始化
│   └── generate_ssh_keys.py  # SSH 密钥生成
├── shortcuts/                 # iOS Shortcut 配置
│   ├── RELAY_STATUS.json
│   ├── RELAY_REVOKE_ALL.json
│   └── IMPORT_GUIDE.md
├── cli_admin.py               # 管理CLI
├── config/
│   └── permission_manifest.yaml  # 权限清单
├── DEPLOY.md                  # Fly.io 部署指南
├── PRIVACY.md                 # 隐私与安全说明
├── Dockerfile
├── fly.toml
├── requirements.txt
└── README.md
```

---

## 安全说明

> ⚠️ **请先阅读 [PRIVACY.md](PRIVACY.md)** 了解密钥安全要求。

- Agent 不持有任何服务器密码，只持有临时 SSH Key
- SSH Key 有 TTL，过期自动失效
- 所有命令经过权限引擎，超出清单直接拒绝
- 敏感命令（如 `rm -rf`）在 `denied_commands` 中拦截
- 管理 Token（ADMIN_TOKEN）仅用于管理操作，Agent 不知道
- 审计日志不记录命令输出，保护敏感数据

---

## License

MIT © toolazytoname
