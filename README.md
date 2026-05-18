# Relay Proxy

> 让 AI Agent 操作你的 Linux 服务器，但你不用把密码交给它。

## 它解决什么问题

你让 AI（Hermes）帮你管理服务器，但不想把服务器密码给 AI。

**传统方案**：把密码给 AI → AI 可以删库、格盘

**Relay Proxy**：AI 只跟 Relay Server 说话，Relay Server 用临时凭证操作服务器，随时可撤销

## 整体架构

```
┌──────────────┐     HTTPS      ┌──────────────┐     SSH     ┌─────────────┐
│   Hermes     │ ─────────────→ │   Relay       │ ──────────→ │  Linux      │
│   (AI Agent) │               │   Server      │             │  Server     │
│              │  Agent Token │  (你部署的)    │             │  (受管理的)  │
└──────────────┘               └──────────────┘             └─────────────┘
                                       ↑
                              你（管理员）用 ADMIN_TOKEN
                              查看会话、撤销权限、查审计日志
```

## Token 鉴权说明

| Token | 谁用 | 什么时候用 | 作用 |
|------|------|-----------|------|
| ADMIN_TOKEN | 你（管理员） | 任何时候 | 查看会话、撤销权限、查审计日志 |
| Agent Token | AI（Hermes） | AI 执行命令时 | AI 的临时操作凭证（自动生成） |

## 完整使用流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        1. 部署 Relay Server                             │
│  在你的云服务器上运行：                                                 │
│  curl -L https://.../deploy_to_server.sh | bash                         │
│  → 生成 ADMIN_TOKEN，保存下来                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     2. 初始化目标服务器（本地执行）                          │
│  在你的电脑本地运行（脚本会自动完成所有配置）：                              │
│  bash /opt/relay-proxy/scripts/init_target_server.sh \                    │
│    --host 目标服务器IP --relay-url http://Relay服务器IP:8000 \           │
│    --password 目标服务器密码                                             │
│  → 自动为这台服务器生成 SSH 密钥对                                       │
│  → SSH 进目标服务器，创建 relay 用户，写入公钥                            │
│  → 自动更新权限清单                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     3. AI 执行命令                                         │
│  你： Hermes，我需要查看服务器状态                                        │
│  Hermes： relay.exec_command("web-1", "docker ps")                       │
│         ↓                                                                 │
│  Relay Server：用私钥 SSH 进目标服务器，执行命令                            │
│  返回结果给 Hermes                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     4. 随时撤销权限                                        │
│  你（用 ADMIN_TOKEN）：relay.revoke_session(session_id)                    │
│  → AI 的会话立刻失效，无法再操作服务器                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 第一步：部署 Relay Server

在**你有公网 IP 的服务器**上运行：

```bash
curl -L https://raw.githubusercontent.com/toolazytoname/relay-proxy/main/scripts/deploy_to_server.sh | bash
```

部署完成后会显示 **ADMIN_TOKEN**，请记录下来。

**验证部署成功：**
```bash
curl http://你的服务器IP:8000/health
# 返回 {"status": "ok"}
```

### 第二步：初始化要管理的服务器

在你**本地电脑**上运行：

```bash
bash /opt/relay-proxy/scripts/init_target_server.sh \
  --host 你的服务器IP \
  --relay-url http://你的Relay服务器IP:8000 \
  --password 你的服务器密码
```

脚本会自动：
1. 为这台服务器生成 SSH 密钥对
2. SSH 进目标服务器配置 relay 用户
3. 自动更新权限清单

### 第三步：让 AI 执行命令

```python
from hermes_tool import RelayProxyTool

relay = RelayProxyTool(
    relay_url="http://你的Relay服务器IP:8000",
    admin_token="部署时的ADMIN_TOKEN"
)

result = relay.exec_command("web-1", "docker ps")
print(result.output)

relay.revoke_session(result.session_id)
```

## 详细文档

- [DEPLOY_SELF_HOSTED.md](DEPLOY_SELF_HOSTED.md) - 完整部署指南
- [HOW_TO_USE.md](HOW_TO_USE.md) - 详细使用指南