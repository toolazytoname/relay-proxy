# 完整使用指南

> 从零开始，一步步把 Relay Proxy 用起来。

---

## 目录

1. [它解决什么问题](#1-它解决什么问题)
2. [架构一览](#2-架构一览)
3. [部署 Relay Server](#3-部署-relay-server)
4. [初始化要管理的服务器](#4-初始化要管理的服务器)
5. [配置权限清单](#5-配置权限清单)
6. [让 AI 执行命令](#6-让-ai-执行命令)
7. [日常管理命令](#7-日常管理命令)
8. [常见问题](#8-常见问题)

---

## 1. 它解决什么问题

**场景**：你想让 AI Agent（Hermes）帮你操作 Linux 服务器，但你不想把服务器密码交给它。

**传统方案的问题**：
- 把密码给 Agent → Agent 可以做任何事（删库、格盘...）
- 密码泄露 → 不知道谁用过、做了什么
- 想收回权限 → 改密码，但所有需要密码的人都得重新配

**Relay Proxy 的方案**：
```
Agent → Relay Server（HTTPS）→ 服务器（只认 SSH Key）
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
│  Hermes Agent  │ ─────────────→ │  Relay Server  │ ────────────→ │  Linux Server │
│  (你让ta干活)   │   无密码接触     │  (你的云服务器)   │   临时会话Key  │  (要管理的机器) │
└────────────────┘                └────────────────┘                └───────────────┘
```

**组件说明**：

| 组件 | 作用 | 托管方式 |
|------|------|----------|
| Hermes Agent | AI Agent（Claude 等） | 本地/云端 |
| Relay Server | 命令转发 + 权限控制 | 自托管（见下文） |
| Linux Server | 实际执行命令 | 你的服务器 |

## Token 鉴权说明

| Token | 谁用 | 什么时候用 | 作用 |
|------|------|-----------|------|
| ADMIN_TOKEN | 你（管理员） | 任何时候 | 查看会话、撤销权限、查审计日志 |
| Agent Token | AI（Hermes） | AI 执行命令时 | AI 的临时操作凭证（自动生成） |

---

## 3. 部署 Relay Server

在**你有公网 IP 的服务器**上运行：

```bash
curl -L https://raw.githubusercontent.com/toolazytoname/relay-proxy/main/scripts/deploy_to_server.sh | bash
```

脚本会自动：
- 创建 `relay` 系统用户
- 克隆代码到 `/opt/relay-proxy`
- 安装 Python 环境（uv）
- 安装依赖
- 配置 systemd service
- 启动服务

**部署完成后会显示 ADMIN_TOKEN**，请记录下来。

---

## 4. 初始化要管理的服务器

在你**本地电脑**上执行：

```bash
bash /opt/relay-proxy/scripts/init_target_server.sh \
  --host 你的服务器IP \
  --relay-url http://你的Relay服务器IP:8000 \
  --password 你的服务器密码
```

> 脚本会自动：
> 1. 为这台服务器生成 SSH 密钥对（私钥留在 Relay Server）
> 2. SSH 登录目标服务器，创建 `relay` 用户并注入公钥
> 3. **自动更新权限清单**
>
> 初始化完成后，**服务器密码可以丢弃**，后续 Agent 用 SSH Key 认证。

> **前提**：你的电脑需要能访问 Relay Server 的 8000 端口。

---

## 5. 配置权限清单

### 5.1 什么是权限清单

权限清单（permission_manifest.yaml）决定 AI **只能做什么**。这是 Relay Proxy 的核心安全机制——即使 AI 被入侵，攻击者也只能做清单里允许的事。

### 5.2 默认策略（开箱即用）

默认配置已经允许以下**只读命令**，你不需要修改：

```yaml
default_policy:
  readonly: true
  allowed_commands:
    - tail
    - grep
    - cat
    - ls
    - df
    - free
    - ps
    - uptime
    - whoami
    - hostname
    - pwd
    - echo
```

### 5.3 添加你的服务器

编辑 `/opt/relay-proxy/config/permission_manifest.yaml`，在 `servers` 列表中添加：

```yaml
servers:
  - name: web-1              # 你给服务器起的名字
    host: 1.2.3.4            # 服务器 IP
    user: relay               # SSH 用户（初始化脚本自动创建的）
```

### 5.4 高级配置（可选）

如果 AI 需要执行更多命令，可以在服务器配置里添加：

```yaml
servers:
  - name: web-1
    host: 1.2.3.4
    user: relay
    policy:
      allowed_commands:
        - docker ps         # 允许执行 docker ps
        - docker logs *      # 允许查看 docker 日志
```

### 5.5 危险命令永远会被阻止

以下危险命令无论是否在白名单中都会被阻止：

```yaml
denied_commands:
  - rm -rf /           # 格式化磁盘
  - dd if=              # 写入磁盘
  - :(){ :|:& };:      # fork 炸弹
```

---

## 6. 让 AI 执行命令

### 6.1 安装 Hermes Tool

```python
pip install hermes-tool
```

### 6.2 执行命令

```python
from hermes_tool import RelayProxyTool

relay = RelayProxyTool(
    relay_url="http://你的Relay服务器IP:8000",
    admin_token="部署时生成的ADMIN_TOKEN"
)

# 让 AI 执行命令
result = relay.exec_command("web-1", "docker ps")
print(result.output)

# 撤销 AI 的权限
relay.revoke_session(result.session_id)
```

---

## 7. 日常管理命令

### 7.1 查看活跃会话

```bash
python3 cli_admin.py sessions list
```

### 7.2 撤销会话

```bash
# 撤销单个会话
python3 cli_admin.py sessions revoke sess_abc123

# 撤销所有 Agent 会话
python3 cli_admin.py sessions revoke --all
```

### 7.3 查看审计日志

```bash
# 最近 20 条记录
python3 cli_admin.py audit query --limit 20

# 只看被拒绝的命令
python3 cli_admin.py audit query --status denied

# 查看特定服务器的记录
python3 cli_admin.py audit query --server web-1
```

### 7.4 服务管理

```bash
sudo systemctl start   relay-proxy   # 启动
sudo systemctl stop    relay-proxy   # 停止
sudo systemctl restart relay-proxy   # 重启
sudo systemctl status  relay-proxy   # 状态
```

---

## 8. 常见问题

**Q: AI 执行命令报 403 Forbidden**
A: 命令不在权限清单中。检查 `/opt/relay-proxy/config/permission_manifest.yaml`

**Q: SSH 连接失败**
A: 检查服务器防火墙、SSH 端口、relay 用户公钥是否正确

**Q: 如何查看历史操作记录？**
A: `python3 cli_admin.py audit query`

**Q: 需要几台服务器？**
A: 最少 2 台：1 台部署 Relay Server（有公网 IP），n 台受管理的服务器
