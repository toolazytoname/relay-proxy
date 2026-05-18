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

在 **Relay Server 上**运行（脚本已在部署时下载到 `/opt/relay-proxy`）：

```bash
bash /opt/relay-proxy/scripts/init_target_server.sh \
  --host 你的服务器IP \
  --relay-url http://你的Relay服务器IP:8000 \
  --password 你的服务器密码
```

### 第三步：添加服务器到权限清单

编辑 `/opt/relay-proxy/config/permission_manifest.yaml`：

```yaml
servers:
  - name: web-1
    host: 你的服务器IP
    user: relay
```

### 第四步：让 AI 执行命令

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

## 权限清单

权限清单决定 AI 只能做什么。**默认配置已经可用**（只读命令如 `tail`, `grep`, `ls`, `df`, `ps` 等）。

详见 [HOW_TO_USE.md](HOW_TO_USE.md)

## 详细文档

- [DEPLOY_SELF_HOSTED.md](DEPLOY_SELF_HOSTED.md) - 完整部署指南
- [HOW_TO_USE.md](HOW_TO_USE.md) - 详细使用指南