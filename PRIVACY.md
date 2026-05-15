# 隐私与安全

Relay Proxy 设计的第一原则：**Agent 永远不接触服务器密码**。

## 密钥管理

### 绝不能提交的内容

以下文件**绝不**提交到 GitHub（已加入 `.gitignore`）：

| 类型 | 示例 | 原因 |
|------|------|------|
| SSH 私钥 | `keys/*_ed25519` | 持有私钥即可连接服务器 |
| 服务器密码 | `init_server.py` 运行时 | 直接登录凭证 |
| ADMIN_TOKEN | Fly.io Secrets | 管理接口的完全访问权限 |
| `.env` 文件 | `RELAY_URL`, `ADMIN_TOKEN` | 运行时凭证 |

### 安全存放

| 凭证 | 推荐存储 |
|------|----------|
| ADMIN_TOKEN | Fly.io Secrets（`fly secrets set`）|
| SSH 私钥 | Fly.io Secrets（每服务器一个 secret） |
| 服务器密码 | 仅初始化时使用，用完即弃 |

## 审计日志的隐私说明

审计日志记录了：
- 执行的命令内容（**不含命令输出**）
- Session ID、时间、时长、退出码
- 匹配的权限策略

审计日志**不**记录：
- 命令的实际输出内容（可能有敏感数据）
- 文件读写内容
- 交互式会话的输入

如需记录输出，需在部署时显式开启 `AUDIT_LOG_OUTPUT=true`，并确保日志存储符合 GDPR/等效法规。

## 网络安全

- Relay Server **必须**使用 HTTPS（生产环境）
- ADMIN_TOKEN 只能通过 HTTPS 传输
- 建议限制 `ALLOWED_HOSTS`（只允许你的 Agent 服务器 IP）
- 服务器的 `relay` 账号应该是普通用户，不是 root

## 最小权限原则

```yaml
# ❌ 错误示范：权限过大
allowed_commands: ["*"]           # 允许所有命令

# ✅ 正确示范：精确授权
allowed_commands:
  - docker ps
  - docker logs --tail 100
  - docker-compose ps
  - tail /var/log/nginx/*.log
```

## 定期轮换

- SSH Key 建议每 90 天重新生成
- ADMIN_TOKEN 建议每 30 天更换
- 每次更换后执行：`python3 cli_admin.py sessions revoke --all`
