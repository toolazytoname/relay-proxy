# Relay Proxy Hermes Skill

## 简介

这个 Skill 让 Hermes Agent 能够通过 Relay Proxy 控制远程 Linux 服务器，无需接触密码。

## 工作原理

```
用户（飞书）→ Hermes Agent → Relay Proxy API → Linux 服务器
                                    ↓
                              SSH Ed25519 密钥
                              权限清单控制
```

## 配置（管理员设置，Hermes 只能读取）

管理员在 Hermes 的环境变量中设置：

```bash
RELAY_URL=http://你的Relay服务器IP:8000
# ADMIN_TOKEN 由管理员保留，Hermes 执行命令时不需要
```

## 使用方法

### 调用方式

```python
from hermes_tool import RelayProxyTool

relay = RelayProxyTool()

# 执行命令，server 可以是服务器名称或 IP 地址
result = relay.exec_command("服务器名称或IP", "命令")
print(result.output)
```

### 1. 查看服务器状态

```python
# 用 IP 地址
result = relay.exec_command("1.2.3.4", "uptime && df -h && free -h")

# 或用名称（如果已配置）
result = relay.exec_command("web-1", "uptime && df -h && free -h")
```

### 2. 执行 Docker 命令

```python
# 查看容器
result = relay.exec_command("1.2.3.4", "docker ps")

# 查看日志
result = relay.exec_command("1.2.3.4", "docker logs --tail 50 容器名")

# 进入容器
result = relay.exec_command("1.2.3.4", "docker exec -it 容器名 /bin/bash")
```

### 3. 文件操作

```python
# 查看日志文件
result = relay.exec_command("1.2.3.4", "tail -n 100 /var/log/nginx/access.log")

# 检查磁盘空间
result = relay.exec_command("1.2.3.4", "df -h")
```

### 4. 会话管理

```python
# 查看当前所有会话
sessions = relay.list_sessions()

# 撤销某个会话
relay.revoke_session("sess_abc123")

# 撤销所有会话
relay.revoke_all_sessions()
```

## 服务器名称

在 `permission_manifest.yaml` 中定义的 `name` 字段就是服务器名称，例如：
- `web-1` - Web 服务器 1
- `db-1` - 数据库服务器
- `cache-1` - 缓存服务器

## 权限控制

AI 只能执行权限清单中允许的命令。危险命令（如 `rm -rf /`）无论是否在清单中都会被阻止。

## 审计

所有操作都有记录，可以通过以下方式查询：

```python
# 查询某台服务器的审计日志
records = relay.query_audit(server="web-1", limit=50)

# 只看被拒绝的操作
records = relay.query_audit(server="web-1", limit=50)
# 然后筛选 status == "denied" 的记录
```

## 错误处理

```python
result = relay.exec_command("1.2.3.4", "some command")
if result.status == "denied":
    print(f"命令被拒绝: {result.output}")
elif result.status == "error":
    print(f"执行错误: {result.output}")
```

## 常用命令模板

| 目的 | 命令 |
|------|------|
| 查看服务器状态 | `uptime && df -h && free -h` |
| 查看 Docker 容器 | `docker ps` |
| 查看容器日志 | `docker logs --tail 100 容器名` |
| 查看 Nginx 日志 | `tail -n 100 /var/log/nginx/access.log` |
| 检查端口占用 | `netstat -tlnp \| grep 80` |
| 查看进程 | `ps aux \| grep python` |

## 用户对话示例

用户在飞书中对 Hermes 说：

```
帮我看一下 1.2.3.4 的服务器状态
帮我执行 docker ps 在 1.2.3.4
查看 1.2.3.4 的容器日志，容器名叫 web
```

Hermes 会自动解析为：
```python
relay.exec_command("1.2.3.4", "uptime && df -h && free -h")
relay.exec_command("1.2.3.4", "docker ps")
relay.exec_command("1.2.3.4", "docker logs --tail 100 web")
```