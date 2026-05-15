# iOS Shortcut 导入指南

把以下 JSON 文件导入 iOS Shortcuts App，然后替换 `${RELAY_ADMIN_TOKEN}` 为你的真实 token。

## 方式

1. 在 iPhone 上打开 Shortcuts App
2. 点右上角 `+` → `导入快捷指令`
3. 选 `RELAY_STATUS.json` 等文件
4. 编辑每个快捷指令，把 `${RELAY_ADMIN_TOKEN}` 替换为真实 ADMIN_TOKEN

## 快捷指令列表

| 文件 | 名称 | 触发词 | 作用 |
|------|------|--------|------|
| RELAY_STATUS.json | Relay 状态 | "Relay状态" | 查看活跃会话 |
| RELAY_REVOKE_ALL.json | Relay 切断 | "Relay切断" | 撤销所有会话 |
| RELAY_AUDIT.json | Relay 审计 | "Relay审计" | 查询审计记录 |

## 部署地址

先在 Fly.io 部署 Relay Server，获取地址后编辑快捷指令中的 URL。

```bash
fly apps list      # 查看已部署的 app
fly info           # 查看 app 详情和地址
```
