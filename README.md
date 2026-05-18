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
│              │  Admin Token │  (你部署的)    │             │  (受管理的)  │
└──────────────┘               └──────────────┘             └─────────────┘
         ↑                            │
         │                            ↓
         │                     ┌──────────────┐
         └─────────────────── │   你（管理员）│
                              └──────────────┘
                                    Admin Token
```

## 使用流程

### 第一步：部署 Relay Server

在**你有公网 IP 的服务器**上运行：

```bash
git clone https://github.com/toolazytoname/relay-proxy.git
cd relay-proxy

# 安装 uv（环境管理）
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 安装依赖
uv venv
uv pip install -r requirements.txt

# 生成管理员 Token
export ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 配置
export MANIFEST_PATH=/opt/relay-proxy/config/permission_manifest.yaml
export LOG_DIR=/opt/relay-proxy/logs

# 启动
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**验证部署成功：**
```bash
curl http://你的服务器IP:8000/health
# 返回 {"status": "ok"}
```

### 第二步：初始化你的 Linux 服务器

在**受管理的服务器**上（需要 root 密码）：

```bash
# 在 Relay Server 机器上生成密钥
python3 scripts/generate_ssh_keys.py

# 在受管理服务器上初始化（创建 relay 用户，注入公钥）
python3 scripts/init_server.py \
  --host 1.2.3.4 \
  --user root \
  --password "你的服务器密码"
```

### 第三步：配置权限清单

编辑 `config/permission_manifest.yaml`：

```yaml
servers:
  - name: web-1
    host: 1.2.3.4
    user: relay
    policy:
      allowed_commands:
        - docker ps
        - docker logs
        - echo
```

### 第四步：让 Hermes 调用

```python
from hermes_tool import RelayProxyTool

relay = RelayProxyTool(
    relay_url="http://你的Relay服务器IP:8000",
    admin_token="你的ADMIN_TOKEN"
)

# AI 执行命令
result = relay.exec_command("web-1", "docker ps")
print(result.output)

# 撤销 AI 的权限
relay.revoke_session(result.session_id)
```

## 快速问答

**Q: 需要几台服务器？**
A: 最少 2 台：1 台部署 Relay Server（有公网 IP），n 台受管理的服务器

**Q: ADMIN_TOKEN 是什么？**
A: 你的"老板权限"，可以查看所有 AI 会话、撤销权限、查审计日志

**Q: 怎么让 AI 执行命令？**
A: AI 调用 `relay.exec_command("服务器名", "命令")`，Relay Server 转发到服务器

**Q: 如何撤销 AI 的权限？**
A: `relay.revoke_session(session_id)` 或 `relay.revoke_all()` 撤销所有

## 详细文档

- [DEPLOY_SELF_HOSTED.md](DEPLOY_SELF_HOSTED.md) - 完整部署指南
- [PRIVACY.md](PRIVACY.md) - 安全说明
- [HOW_TO_USE.md](HOW_TO_USE.md) - 详细使用指南