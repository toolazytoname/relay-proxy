# Fly.io 部署指南

本文档详细说明如何将 Relay Proxy 部署到 Fly.io，并连接你的 Linux 服务器。

---

## 前置准备

1. **Fly.io 账号**：https://fly.io/signup
2. **flyctl CLI**：
   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```
3. **GitHub 仓库**：代码已在此 https://github.com/toolazytoname/relay-proxy

---

## 步骤 1：获取 Fly.io API Token

1. 打开 https://fly.io/dashboard/personal/access-tokens
2. 点 `Create Access Token`
3. 复制 Token，保存好

---

## 步骤 2：初始化 Fly.io 应用

```bash
cd relay-proxy

# 登录（会弹出浏览器）
fly auth login

# 初始化项目（交互式，按提示选择）
fly launch
```

> **注意**：部署地址保存下来，后面要用。格式：`https://xxx.fly.dev`

---

## 步骤 3：配置Secrets

```bash
# ADMIN_TOKEN：管理接口密码（自己生成）
fly secrets set ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 每台服务器的 SSH 私钥（按服务器名称）
fly secrets set SSH_KEY_WEB_1="$(cat keys/web-1_ed25519)"
fly secrets set SSH_KEY_DB_1="$(cat keys/db-1_ed25519)"
# ... 以此类推
```

---

## 步骤 4：配置权限清单

编辑 `config/permission_manifest.yaml`：

```bash
# 直接在 Fly.io 在线编辑
fly secrets set PERMISSION_MANIFEST="$(cat config/permission_manifest.yaml | base64)"
```

或者挂载卷：
```toml
# fly.toml 添加
[mounts]
source = "relay_data"
destination = "/app/data"
```

---

## 步骤 5：部署

```bash
fly deploy
```

成功后会显示：
```
https://xxx.fly.dev   <- Relay Server 地址
```

---

## 步骤 6：验证部署

```bash
# 检查应用状态
fly status

# 查看日志
fly logs

# 测试健康检查
curl https://xxx.fly.dev/health
```

---

## 步骤 7：初始化 Linux 服务器

在**你的本地机器**上运行（不是 Fly.io，是你要连接的服务器）：

```bash
cd relay-proxy

# 安装依赖
pip3 install paramiko

# 初始化服务器（会创建 relay 用户，注入公钥）
python3 scripts/init_server.py \
  --host 1.2.3.4 \
  --port 22 \
  --user root \
  --password "你的服务器密码"
```

> **安全提醒**：这个密码只在初始化时使用，用完即弃。后续 Agent 用 SSH Key 认证。

---

## 步骤 8：更新 Herme

在 Hermes 的环境变量或配置中设置：

```bash
RELAY_URL=https://xxx.fly.dev
ADMIN_TOKEN=xxx   # 步骤3中设置的
```

---

## 更新部署

```bash
# 修改代码后
git add . && git commit -m "update" && git push

# 重新部署
fly deploy
```

---

## 常见问题

### Q: `fly launch` 报 region 错误？
```bash
# 查看可用 region
flyctl platform regions

# 指定 region
fly launch --region sin
```

### Q: SSH Key 报权限错误？
```bash
# 本地修复
chmod 600 keys/*_ed25519

# 服务器端 relay 用户的 key 权限
# scripts/init_server.py 已处理
```

### Q: 会话超时？
检查 `src/main.py` 中 `SESSION_TTL_SECONDS` 是否合理，默认 3600s（1小时）。

### Q: 如何查看谁在用？
```bash
fly logs | grep "session"
```

---

## 生产环境检查清单

- [ ] ADMIN_TOKEN 已设置
- [ ] 所有服务器的 SSH Key 已注入 Secrets
- [ ] `permission_manifest.yaml` 已配置最小权限
- [ ] HTTPS 确认可用（`https://xxx.fly.dev/health`）
- [ ] 本地 `cli_admin.py` 已配置 `RELAY_URL` 和 `ADMIN_TOKEN`
- [ ] iOS Shortcut 中的 URL 已更新

---

## 下一步

- [配置 iOS Shortcut](shortcuts/IMPORT_GUIDE.md)
- [查看隐私安全说明](PRIVACY.md)
- [使用 cli_admin.py 管理会话](cli_admin.py)
