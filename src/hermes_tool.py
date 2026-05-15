"""
Hermes Tool — Agent 接口层
把 Relay Proxy 封装成 Hermes Agent 可调用的 Tool。

用法（在你的 Hermes 配置或 skill 中）：
1. 启动 Relay Server（部署在 Fly.io 或你自己服务器）
2. 配置 RELAY_URL + ADMIN_TOKEN 环境变量
3. 在 Hermes 的 tools 配置里引用此类
"""

import os
import httpx
from typing import Optional
from pydantic import BaseModel


class CommandRequest(BaseModel):
    server: str           # 服务器名称（对应 permission_manifest.yaml 中的 name）
    command: str           # 命令或自然语言描述
    session_id: Optional[str] = None  # 可选，复用已有会话


class CommandResponse(BaseModel):
    session_id: str
    command: str
    output: str
    exit_code: int
    status: str            # "success" | "denied" | "error" | "revoked"
    intent_resolved: Optional[str] = None  # 如果输入是自然语言，返回解析后的实际命令
    audit_id: str          # 审计ID，可用于事后查询


class SessionInfo(BaseModel):
    session_id: str
    server: str
    created_at: str
    expires_at: str
    status: str


class RelayProxyTool:
    """
    Hermes Agent 调用 Relay Proxy 的接口封装。
    不直接持有任何服务器凭证，所有请求经过 Relay Server。
    """

    def __init__(
        self,
        relay_url: Optional[str] = None,
        admin_token: Optional[str] = None,
        timeout: int = 60,
    ):
        self.relay_url = (relay_url or os.environ.get("RELAY_URL", "http://localhost:8000")).rstrip("/")
        self.admin_token = admin_token or os.environ.get("ADMIN_TOKEN", "")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    # ──────────────────────────────────────────
    # 核心：执行命令（Agent 主动调用）
    # ──────────────────────────────────────────

    def exec_command(self, server: str, command: str, session_id: Optional[str] = None) -> CommandResponse:
        """
        执行命令或自然语言指令。

        Args:
            server: 服务器名称（manifest 中定义）
            command: Shell 命令，或自然语言描述（如"帮我看看服务器状态"）
            session_id: 可选，复用已有会话

        Returns:
            CommandResponse: 包含执行结果、审计ID等

        Example（Hermes skill 或代码中）:
            relay = RelayProxyTool()
            result = relay.exec_command("web-1", "docker ps")
            print(result.output)
        """
        payload = {"server": server, "command": command}
        if session_id:
            payload["session_id"] = session_id

        resp = self._post("/api/v1/exec", payload)
        return CommandResponse(**resp)

    # ──────────────────────────────────────────
    # 会话管理
    # ──────────────────────────────────────────

    def create_session(self, server: str, ttl_seconds: int = 3600) -> SessionInfo:
        """创建新会话（会生成临时凭证）"""
        payload = {"server": server, "ttl_seconds": ttl_seconds}
        resp = self._post("/api/v1/sessions", payload)
        return SessionInfo(**resp)

    def list_sessions(self) -> list[SessionInfo]:
        """列出所有活跃会话（需 ADMIN_TOKEN）"""
        resp = self._get("/api/v1/sessions")
        return [SessionInfo(**s) for s in resp["sessions"]]

    def revoke_session(self, session_id: str) -> dict:
        """撤销指定会话，立刻失效"""
        return self._delete(f"/api/v1/sessions/{session_id}")

    def revoke_all_sessions(self) -> dict:
        """撤销所有活跃会话"""
        return self._delete("/api/v1/sessions")

    # ──────────────────────────────────────────
    # 审计查询
    # ──────────────────────────────────────────

    def get_audit(self, audit_id: str) -> dict:
        """根据审计ID查询完整日志"""
        return self._get(f"/api/v1/audit/{audit_id}")

    def query_audit(
        self,
        session_id: Optional[str] = None,
        server: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """查询审计日志（支持过滤）"""
        params = {"limit": limit}
        if session_id:
            params["session_id"] = session_id
        if server:
            params["server"] = server
        resp = self._get("/api/v1/audit", params=params)
        return resp.get("records", [])

    # ──────────────────────────────────────────
    # 权限清单（只读）
    # ──────────────────────────────────────────

    def get_permission_manifest(self) -> dict:
        """获取当前权限清单"""
        return self._get("/api/v1/permissions")

    def check_permission(self, server: str, command: str) -> dict:
        """预先检查某命令是否会被允许（不实际执行）"""
        payload = {"server": server, "command": command}
        resp = self._post("/api/v1/permissions/check", payload)
        return resp

    # ──────────────────────────────────────────
    # 内部工具
    # ──────────────────────────────────────────

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.admin_token:
            headers["Authorization"] = f"Bearer {self.admin_token}"
        return headers

    def _post(self, path: str, payload: dict) -> dict:
        resp = self._client.post(
            f"{self.relay_url}{path}",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        resp = self._client.get(
            f"{self.relay_url}{path}",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        resp = self._client.delete(
            f"{self.relay_url}{path}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    # ──────────────────────────────────────────
    # 便捷方法（自然语言支持）
    # ──────────────────────────────────────────

    def status(self, server: str = "default") -> str:
        """查看服务器状态（简化入口）"""
        result = self.exec_command(server, "uptime && df -h && free -h")
        return f"[{result.session_id}] {result.output}"

    def docker_logs(self, server: str, container: str, lines: int = 50) -> str:
        """查看 Docker 容器日志"""
        result = self.exec_command(server, f"docker logs --tail {lines} {container}")
        return result.output

    def restart_service(self, server: str, service: str) -> str:
        """重启系统服务（需明确授权）"""
        result = self.exec_command(server, f"sudo systemctl restart {service}")
        return f"[{result.status}] {result.output}"


# ──────────────────────────────────────────
# Hermes Skill 格式导出
# ──────────────────────────────────────────

HERMES_SKILL = """
relay-proxy 工具：
- relay.create_session(server, ttl_seconds) — 创建会话
- relay.exec_command(server, command) — 执行命令（支持自然语言）
- relay.list_sessions() — 查看活跃会话（需 ADMIN_TOKEN）
- relay.revoke_session(session_id) — 撤销会话，立刻失效
- relay.query_audit(session_id) — 查询审计日志
- relay.check_permission(server, command) — 预先检查权限

使用示例：
  relay = RelayProxyTool()
  result = relay.exec_command("web-1", "docker ps")
  print(result.output)
"""

if __name__ == "__main__":
    # 快速测试（需本地 Relay Server 运行中）
    relay = RelayProxyTool(relay_url="http://localhost:8000", admin_token="dev-token")
    sessions = relay.list_sessions()
    print(f"当前活跃会话: {len(sessions)}")
