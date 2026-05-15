"""
Permission Engine - 命令级权限检查 + 意图映射 + 运行时权限发现
参考: Teleport RBAC + 意图驱动权限扩展
"""

import re
import shlex
import yaml
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

# ============================================================
# 意图 → 命令映射（方案1）
# ============================================================

INTENT_COMMAND_MAP = {
    "docker": {
        "keywords": ["docker", "容器", "镜像", "container", "docker-compose"],
        "allowed_commands": ["docker", "docker-compose"],
        "sudo_commands": [
            "systemctl restart docker",
            "systemctl stop docker",
            "systemctl start docker",
            "docker restart *",
            "docker stop *",
            "docker start *",
            "docker exec *",
            "docker logs *",
        ],
        "allowed_paths": ["/var/lib/docker/*", "/etc/docker/*", "/home/*/docker-compose.yml"],
        "description": "Docker 容器管理",
    },
    "log_view": {
        "keywords": ["日志", "log", "查看日志", "tail", "journal"],
        "allowed_commands": ["tail", "grep", "cat", "ls", "journalctl"],
        "sudo_commands": ["journalctl -u *"],
        "allowed_paths": ["/var/log/*", "/home/*/logs/*"],
        "description": "日志查看",
    },
    "system_status": {
        "keywords": ["状态", "status", "监控", "系统状态", "资源", "top", "内存", "CPU"],
        "allowed_commands": ["top", "htop", "df", "free", "du", "ps", "uptime", "ls"],
        "sudo_commands": [],
        "allowed_paths": [],
        "description": "系统状态监控",
    },
    "nginx": {
        "keywords": ["nginx", "web服务", "网站", "http"],
        "allowed_commands": ["systemctl", "nginx", "curl"],
        "sudo_commands": [
            "systemctl status nginx",
            "systemctl restart nginx",
            "systemctl stop nginx",
            "systemctl start nginx",
            "nginx -t",
            "nginx -s reload",
        ],
        "allowed_paths": ["/etc/nginx/*", "/var/log/nginx/*"],
        "description": "Nginx 服务管理",
    },
    "git_deploy": {
        "keywords": ["部署", "deploy", "git", "代码部署", "更新代码", "pull", "clone"],
        "allowed_commands": ["git", "docker-compose", "curl"],
        "sudo_commands": [
            "systemctl restart *",
            "docker-compose -f * up -d",
            "docker-compose -f * down",
            "docker-compose -f * restart",
        ],
        "allowed_paths": ["/home/*/"],
        "description": "Git 代码部署",
    },
    "network": {
        "keywords": ["网络", "network", "端口", "firewall", "防火墙", "netstat", "ss"],
        "allowed_commands": ["ss", "netstat", "ip", "ping", "curl", "wget"],
        "sudo_commands": [
            "ufw allow *",
            "ufw deny *",
            "ufw status",
            "firewall-cmd *",
            "iptables -L",
        ],
        "allowed_paths": [],
        "description": "网络与防火墙",
    },
    "database": {
        "keywords": ["数据库", "db", "mysql", "postgres", "mongo", "redis", "sql"],
        "allowed_commands": ["docker"],
        "sudo_commands": [
            "docker exec *",
            "systemctl status postgresql",
            "systemctl status mysql",
            "systemctl status redis",
        ],
        "allowed_paths": ["/var/lib/postgresql/*", "/var/lib/mysql/*"],
        "description": "数据库状态查看",
    },
    "general": {
        "keywords": ["*"],  # 默认匹配
        "allowed_commands": ["ls", "cat", "echo", "pwd", "whoami", "hostname"],
        "sudo_commands": [],
        "allowed_paths": [],
        "description": "通用只读命令",
    },
}


class CheckResult(Enum):
    ALLOWED = "allowed"
    DENIED = "denied"


@dataclass
class PermissionCheck:
    status: CheckResult
    reason: str
    matched_intent: Optional[str] = None
    suggestion: Optional[dict] = None  # 拒绝时给出建议


@dataclass
class PermissionManifest:
    version: str = "1.0"
    default_policy: dict = field(default_factory=dict)
    servers: list = field(default_factory=list)
    # 运行时发现的待确认权限
    pending_permissions: list = field(default_factory=list)


class PermissionEngine:
    """
    权限引擎
    1. 从 YAML 加载权限清单
    2. 命令级检查
    3. 意图映射生成
    4. 运行时权限发现（拒绝时给出建议）
    """

    # 全局黑名单（始终禁止）
    GLOBAL_DENY = [
        r"rm\s+-rf\s+/",
        r"dd\s+if=",
        r":\(\)\{.*:&.*\};:",  # fork bomb
        r"curl.*\|.*sh",
        r"wget.*\|.*sh",
    ]

    def __init__(self, manifest_path: Optional[Path] = None):
        self.manifest_path = manifest_path
        self.manifest = PermissionManifest()
        if manifest_path and manifest_path.exists():
            self.load_manifest(manifest_path)

    def load_manifest(self, path: Path) -> None:
        """从 YAML 加载权限清单"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.manifest.version = data.get("version", "1.0")
        self.manifest.default_policy = data.get("default_policy", {})
        self.manifest.servers = data.get("servers", [])

    def save_manifest(self, path: Path) -> None:
        """保存权限清单到 YAML"""
        data = {
            "version": self.manifest.version,
            "default_policy": self.manifest.default_policy,
            "servers": self.manifest.servers,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def get_server_policy(self, server_name: str) -> dict:
        """获取指定服务器的权限策略（优先精确匹配，回退到默认）"""
        for server in self.manifest.servers:
            if server.get("name") == server_name:
                return {**self.manifest.default_policy, **server.get("policy", {})}
        return self.manifest.default_policy.copy()

    def check(self, command: str, server_name: str) -> PermissionCheck:
        """
        核心检查函数
        返回 PermissionCheck，包含状态、原因、建议（拒绝时）
        """
        # 1. 全局黑名单
        for pattern in self.GLOBAL_DENY:
            if re.search(pattern, command):
                return PermissionCheck(
                    status=CheckResult.DENIED,
                    reason=f"命中全局黑名单: {pattern}",
                )

        # 2. 获取服务器策略
        policy = self.get_server_policy(server_name)

        # 3. 解析命令
        try:
            cmd_parts = shlex.split(command.strip())
        except ValueError:
            return PermissionCheck(
                status=CheckResult.DENIED,
                reason="命令解析失败",
            )

        if not cmd_parts:
            return PermissionCheck(
                status=CheckResult.DENIED,
                reason="空命令",
            )

        base_cmd = cmd_parts[0]

        # 4. 显式黑名单
        denied_commands = policy.get("denied_commands", [])
        if any(re.search(p, command) for p in denied_commands):
            suggestion = self._build_suggestion(command, server_name)
            return PermissionCheck(
                status=CheckResult.DENIED,
                reason="命令命中黑名单",
                suggestion=suggestion,
            )

        # 5. 白名单检查
        allowed_commands = policy.get("allowed_commands", [])
        readonly = policy.get("readonly", False)

        if base_cmd not in allowed_commands:
            suggestion = self._build_suggestion(command, server_name)
            return PermissionCheck(
                status=CheckResult.DENIED,
                reason=f"命令不在白名单: {base_cmd}",
                suggestion=suggestion,
            )

        # 6. sudo 命令专项检查
        if base_cmd == "sudo" and len(cmd_parts) > 1:
            actual_cmd = " ".join(cmd_parts[1:])
            sudo_patterns = policy.get("sudo_commands", [])
            if not any(self._match_pattern(p, actual_cmd) for p in sudo_patterns):
                suggestion = self._build_suggestion(command, server_name)
                return PermissionCheck(
                    status=CheckResult.DENIED,
                    reason=f"Sudo 命令不在白名单: {actual_cmd}",
                    suggestion=suggestion,
                )

        # 7. 只读检查（readonly 模式下禁止写入操作）
        if readonly and any(cmd in base_cmd for cmd in ["rm", "mv", "dd", "mkfs"]):
            return PermissionCheck(
                status=CheckResult.DENIED,
                reason="只读模式禁止写入操作",
            )

        # 8. 路径检查
        denied_paths = policy.get("denied_paths", [])
        for path_pattern in denied_paths:
            if path_pattern.replace("*", "") in command:
                return PermissionCheck(
                    status=CheckResult.DENIED,
                    reason=f"路径禁止访问: {path_pattern}",
                )

        return PermissionCheck(
            status=CheckResult.ALLOWED,
            reason="OK",
        )

    # ---- 意图映射（方案1）----

    def generate_policy_from_intent(self, description: str) -> dict:
        """
        根据自然语言描述生成权限配置
        用户说"管理 Docker 和查看日志" → 自动展开命令清单
        """
        description_lower = description.lower()
        matched_intents = []

        # 关键词匹配
        for intent_key, intent_config in INTENT_COMMAND_MAP.items():
            if intent_key == "general":
                continue
            keywords = intent_config.get("keywords", [])
            if any(kw in description_lower for kw in keywords):
                matched_intents.append(intent_key)

        if not matched_intents:
            matched_intents = ["general"]

        # 合并所有匹配意图的命令
        merged_policy = {
            "allowed_commands": set(),
            "sudo_commands": set(),
            "allowed_paths": set(),
        }

        warnings = []
        for intent_key in matched_intents:
            config = INTENT_COMMAND_MAP[intent_key]
            merged_policy["allowed_commands"].update(config.get("allowed_commands", []))
            merged_policy["sudo_commands"].update(config.get("sudo_commands", []))
            merged_policy["allowed_paths"].update(config.get("allowed_paths", []))
            if config.get("dangerous"):
                warnings.append(f"⚠️ {config['description']} 为高危操作")

        return {
            "matched_intents": matched_intents,
            "policy": {
                "allowed_commands": sorted(list(merged_policy["allowed_commands"])),
                "sudo_commands": sorted(list(merged_policy["sudo_commands"])),
                "allowed_paths": sorted(list(merged_policy["allowed_paths"])),
            },
            "warnings": warnings,
        }

    # ---- 运行时权限发现（方案2）----

    def _build_suggestion(self, denied_command: str, server_name: str) -> dict:
        """
        被拒绝时，自动生成授权建议
        这是方案2的核心：让用户一步步放开权限
        """
        # 解析被拒绝的命令，提取需要的 sudo 权限
        try:
            cmd_parts = shlex.split(denied_command.strip())
        except ValueError:
            cmd_parts = [denied_command]

        base_cmd = cmd_parts[0] if cmd_parts else denied_command

        # 根据命令推断需要的权限
        suggested_sudo = []

        # apt-get / yum
        if base_cmd in ("apt-get", "apt", "yum", "dnf"):
            pkg = cmd_parts[2] if len(cmd_parts) > 2 else "*"
            suggested_sudo = [
                f"{base_cmd} install {pkg}",
                f"{base_cmd} remove {pkg}",
            ]

        # systemctl
        elif base_cmd == "systemctl":
            if len(cmd_parts) >= 2:
                action = cmd_parts[1]
                svc = cmd_parts[2] if len(cmd_parts) > 2 else "*"
                suggested_sudo = [
                    f"systemctl status {svc}",
                    f"systemctl {action} {svc}",
                ]

        # docker
        elif base_cmd == "docker":
            if len(cmd_parts) >= 2:
                action = cmd_parts[1]
                target = cmd_parts[2] if len(cmd_parts) > 2 else "*"
                suggested_sudo = [
                    f"docker {action} {target}",
                ]
                if action == "exec":
                    suggested_sudo.append(f"docker exec {target} *")

        # git
        elif base_cmd == "git":
            if len(cmd_parts) >= 3:
                path = cmd_parts[2] if len(cmd_parts) > 2 else "/home/*"
                suggested_sudo = [f"git -C {path} *"]

        # 其他，直接建议允许该命令
        else:
            suggested_sudo = [denied_command.strip()]

        return {
            "action": "add_permission",
            "denied_command": denied_command,
            "server": server_name,
            "suggested_sudo_commands": suggested_sudo,
            "auto_add_allowed": [base_cmd],  # 建议同时加入 allowed_commands
        }

    def add_pending_permission(
        self,
        session_id: str,
        agent_id: str,
        server: str,
        denied_command: str,
        suggestion: dict,
    ) -> dict:
        """将运行时发现的权限请求加入待确认队列"""
        import uuid
        from datetime import datetime, timedelta

        pending = {
            "pending_id": f"pend_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "agent_id": agent_id,
            "server": server,
            "denied_command": denied_command,
            "suggestion": suggestion,
            "status": "pending",
            "expires_at": (datetime.utcnow() + timedelta(hours=6)).isoformat(),
        }
        self.manifest.pending_permissions.append(pending)
        if self.manifest_path:
            self.save_manifest(self.manifest_path)
        return pending

    def approve_pending(self, pending_id: str, server_name: str, permanent: bool = True) -> tuple[bool, str]:
        """批准待确认的权限请求，永久或仅本次"""
        for p in self.manifest.pending_permissions:
            if p["pending_id"] == pending_id:
                suggestion = p["suggestion"]
                sudo_cmds = suggestion.get("suggested_sudo_commands", [])

                # 找到对应服务器，更新策略
                for srv in self.manifest.servers:
                    if srv.get("name") == server_name:
                        policy = srv.setdefault("policy", {})
                        if permanent:
                            sudo_list = policy.setdefault("sudo_commands", [])
                            allowed = policy.setdefault("allowed_commands", [])
                            # 添加新权限
                            for cmd in sudo_cmds:
                                if cmd not in sudo_list:
                                    sudo_list.append(cmd)
                            base_cmd = shlex.split(p["denied_command"])[0]
                            if base_cmd not in allowed:
                                allowed.append(base_cmd)
                        # 标记为已处理
                        p["status"] = "approved"
                        if self.manifest_path:
                            self.save_manifest(self.manifest_path)
                        return True, f"已批准: {sudo_cmds}"

                return False, f"未找到服务器: {server_name}"

        return False, f"未找到待确认请求: {pending_id}"

    # ---- 工具方法 ----

    @staticmethod
    def _match_pattern(pattern: str, text: str) -> bool:
        """简单的 glob 风格匹配（支持 * 匹配任意字符）"""
        # 转为正则
        regex = pattern.replace("*", ".*")
        return bool(re.match(f"^{regex}$", text))

    def list_pending(self) -> list:
        """列出所有待确认的权限请求"""
        return [p for p in self.manifest.pending_permissions if p["status"] == "pending"]
