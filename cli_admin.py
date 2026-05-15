#!/usr/bin/env python3
"""
cli_admin.py — Relay Proxy 管理CLI
用于查看会话、撤销权限、查询审计日志。
支持从终端运行，也支持从手机Shortcut调用。

用法：
  python3 cli_admin.py sessions list
  python3 cli_admin.py sessions revoke <session_id>
  python3 cli_admin.py audit query --session_id sess_xxx
  python3 cli_admin.py permissions check --server web-1 --command "docker ps"

环境变量：
  RELAY_URL      Relay Server 地址（默认 http://localhost:8000）
  ADMIN_TOKEN    管理令牌（必填，查询/撤销操作需要）
"""

import argparse
import os
import sys
import json
import httpx
from datetime import datetime
from typing import Optional

# ──────────────────────────────────────────
# 配置
# ──────────────────────────────────────────

RELAY_URL = os.environ.get("RELAY_URL", "http://localhost:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


# ──────────────────────────────────────────
# 颜色输出
# ──────────────────────────────────────────

class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def colored(text: str, color: str) -> str:
    return f"{color}{text}{Colors.RESET}"


def green(text: str) -> str:
    return colored(text, Colors.GREEN)


def red(text: str) -> str:
    return colored(text, Colors.RED)


def yellow(text: str) -> str:
    return colored(text, Colors.YELLOW)


def blue(text: str) -> str:
    return colored(text, Colors.BLUE)


def bold(text: str) -> str:
    return colored(text, Colors.BOLD)


def dim(text: str) -> str:
    return colored(text, Colors.DIM)


# ──────────────────────────────────────────
# API 客户端
# ──────────────────────────────────────────

class RelayClient:
    def __init__(self, url: str = RELAY_URL, token: str = ADMIN_TOKEN):
        self.url = url.rstrip("/")
        self.token = token
        self.client = httpx.Client(timeout=30)

    def _headers(self) -> dict:
        if not self.token:
            print(dim("⚠  未设置 ADMIN_TOKEN，只读操作"))
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}" if self.token else "",
        }

    def sessions_list(self) -> list:
        resp = self.client.get(
            f"{self.url}/api/v1/sessions",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("sessions", [])

    def sessions_revoke(self, session_id: str) -> dict:
        resp = self.client.delete(
            f"{self.url}/api/v1/sessions/{session_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def sessions_revoke_all(self) -> dict:
        resp = self.client.delete(
            f"{self.url}/api/v1/sessions",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def audit_query(
        self,
        session_id: Optional[str] = None,
        server: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        params = {"limit": limit}
        if session_id:
            params["session_id"] = session_id
        if server:
            params["server"] = server
        resp = self.client.get(
            f"{self.url}/api/v1/audit",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("records", [])

    def audit_get(self, audit_id: str) -> dict:
        resp = self.client.get(
            f"{self.url}/api/v1/audit/{audit_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def permissions_check(self, server: str, command: str) -> dict:
        resp = self.client.post(
            f"{self.url}/api/v1/permissions/check",
            json={"server": server, "command": command},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def permissions_manifest(self) -> dict:
        resp = self.client.get(
            f"{self.url}/api/v1/permissions",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────
# 格式化输出
# ──────────────────────────────────────────

def format_session(s: dict) -> str:
    status_color = {
        "active": Colors.GREEN,
        "expired": Colors.DIM,
        "revoked": Colors.RED,
    }.get(s.get("status", ""), Colors.YELLOW)

    created = s.get("created_at", "")
    expires = s.get("expires_at", "")
    ttl = ""
    if created and expires:
        try:
            from datetime import datetime
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            now = datetime.now(exp.tzinfo) if exp.tzinfo else datetime.now()
            diff = (exp - now).total_seconds()
            ttl = f"{int(diff)}s 后过期"
        except Exception:
            pass

    lines = [
        f"  {bold('Session ID')}  : {blue(s['session_id'])}",
        f"  {bold('Server')}      : {s.get('server', '?')}",
        f"  {bold('Status')}      : {colored(s.get('status', '?'), status_color)} {dim(ttl)}",
        f"  {bold('Created')}     : {created}",
        f"  {bold('Expires')}     : {expires}",
    ]
    return "\n".join(lines)


def format_audit_record(r: dict) -> str:
    status_map = {
        "success": (Colors.GREEN, "✓"),
        "denied": (Colors.RED, "✗"),
        "error": (Colors.RED, "✗"),
        "revoked": (Colors.RED, "✗"),
    }
    color, icon = status_map.get(r.get("status", ""), (Colors.YELLOW, "?"))

    cmd = r.get("command", "")
    if len(cmd) > 60:
        cmd = cmd[:57] + "..."

    lines = [
        f"  {icon} [{r.get('timestamp', '')}] {bold(r.get('session_id', '?'))[:20]}",
        f"    {blue(cmd)}",
        f"    → exit={r.get('exit_code', '')}  duration={r.get('duration_ms', 0)}ms  audit_id={dim(r.get('audit_id', '')[:16])}",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────
# 命令实现
# ──────────────────────────────────────────

def cmd_sessions_list(client: RelayClient):
    sessions = client.sessions_list()
    if not sessions:
        print(yellow("  暂无活跃会话"))
        return

    print(bold(f"\n  活跃会话 ({len(sessions)})：\n"))
    for i, s in enumerate(sessions, 1):
        marker = green("●") if s.get("status") == "active" else red("○")
        print(f"  {marker} [{i}] {format_session(s)}")
        print()


def cmd_sessions_revoke(client: RelayClient, session_id: str):
    result = client.sessions_revoke(session_id)
    print(green(f"\n  ✓ 会话已撤销: {session_id}"))
    if result.get("message"):
        print(f"  {dim(result['message'])}")


def cmd_sessions_revoke_all(client: RelayClient):
    result = client.sessions_revoke_all()
    count = result.get("revoked_count", 0)
    print(green(f"\n  ✓ 已撤销所有会话，共 {count} 个"))


def cmd_audit_query(client: RelayClient, session_id: Optional[str], server: Optional[str], limit: int):
    records = client.audit_query(session_id=session_id, server=server, limit=limit)
    if not records:
        print(yellow("  暂无审计记录"))
        return

    print(bold(f"\n  审计记录 ({len(records)})：\n"))
    for r in records:
        print(format_audit_record(r))
        print()


def cmd_audit_get(client: RelayClient, audit_id: str):
    record = client.audit_get(audit_id)
    print(bold(f"\n  审计详情: {audit_id}\n"))
    # 完整输出，不截断
    print(json.dumps(record, indent=2, ensure_ascii=False))


def cmd_permissions_check(client: RelayClient, server: str, command: str):
    result = client.permissions_check(server, command)
    allowed = result.get("allowed", None)
    if allowed is True:
        print(green(f"\n  ✓ 允许: {command}"))
    elif allowed is False:
        reason = result.get("reason", "未知原因")
        print(red(f"\n  ✗ 拒绝: {command}"))
        print(f"  原因: {reason}")
    else:
        print(yellow(f"\n  ? 待确认: {command}"))
    if result.get("intent_resolved"):
        print(f"  解析为: {blue(result['intent_resolved'])}")


def cmd_permissions_manifest(client: RelayClient):
    manifest = client.permissions_manifest()
    print(bold("\n  权限清单：\n"))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


# ──────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Relay Proxy 管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python3 cli_admin.py sessions list
  python3 cli_admin.py sessions revoke sess_abc123
  python3 cli_admin.py sessions revoke --all
  python3 cli_admin.py audit query --limit 20
  python3 cli_admin.py audit query --session_id sess_xxx
  python3 cli_admin.py audit get audit_xyz
  python3 cli_admin.py permissions check --server web-1 --command "docker ps"
  python3 cli_admin.py permissions manifest

环境变量：
  RELAY_URL=http://your-relay-server.fly.dev
  ADMIN_TOKEN=your_admin_token_here
        """,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # sessions
    p_sessions = sub.add_parser("sessions", help="会话管理")
    p_sessions_sub = p_sessions.add_subparsers(dest="subcommand")

    p_sessions_list = p_sessions_sub.add_parser("list", help="列出活跃会话")
    p_sessions_revoke = p_sessions_sub.add_parser("revoke", help="撤销会话")
    p_sessions_revoke.add_argument("session_id", nargs="?", help="会话ID（省略则撤销所有）")
    p_sessions_revoke.add_argument("--all", action="store_true", help="撤销所有会话")

    # audit
    p_audit = sub.add_parser("audit", help="审计查询")
    p_audit_sub = p_audit.add_subparsers(dest="subcommand")

    p_audit_query = p_audit_sub.add_parser("query", help="查询审计记录")
    p_audit_query.add_argument("--session_id", help="按会话过滤")
    p_audit_query.add_argument("--server", help="按服务器过滤")
    p_audit_query.add_argument("--limit", type=int, default=50)

    p_audit_get = p_audit_sub.add_parser("get", help="查看审计详情")
    p_audit_get.add_argument("audit_id", help="审计ID")

    # permissions
    p_perms = sub.add_parser("permissions", help="权限管理")
    p_perms_sub = p_perms.add_subparsers(dest="subcommand")

    p_perms_check = p_perms_sub.add_parser("check", help="检查命令是否允许")
    p_perms_check.add_argument("--server", required=True)
    p_perms_check.add_argument("--command", required=True)

    p_perms_sub.add_parser("manifest", help="查看完整权限清单")

    args = parser.parse_args()

    try:
        client = RelayClient()
    except Exception as e:
        print(red(f"\n  连接失败: {e}"))
        sys.exit(1)

    # 执行对应命令
    if args.command == "sessions":
        if args.subcommand == "list":
            cmd_sessions_list(client)
        elif args.subcommand == "revoke":
            if getattr(args, "all", False):
                cmd_sessions_revoke_all(client)
            elif args.session_id:
                cmd_sessions_revoke(client, args.session_id)
            else:
                print(yellow("  指定 session_id 或使用 --all"))
        else:
            p_sessions.print_help()

    elif args.command == "audit":
        if args.subcommand == "query":
            cmd_audit_query(client, args.session_id, args.server, args.limit)
        elif args.subcommand == "get":
            cmd_audit_get(client, args.audit_id)
        else:
            p_audit.print_help()

    elif args.command == "permissions":
        if args.subcommand == "check":
            cmd_permissions_check(client, args.server, args.command)
        elif args.subcommand == "manifest":
            cmd_permissions_manifest(client)
        else:
            p_perms.print_help()


if __name__ == "__main__":
    main()
