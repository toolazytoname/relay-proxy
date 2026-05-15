"""
Auth Layer - 短期 Token 管理 + 即时撤销
参考: Teleport 短期证书思想
"""

import uuid
import time
import json
import secrets
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

# Token 存储文件（生产环境建议用 Redis）
TOKEN_STORE_PATH = Path("/tmp/relay-proxy/tokens.jsonl")
TOKEN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Token:
    session_id: str
    token: str
    agent_id: str
    created_at: str
    expires_at: str  # ISO timestamp
    scope: list[str]  # 允许操作的服务器列表
    revoked: bool = False

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > datetime.fromisoformat(self.expires_at)

    @property
    def is_valid(self) -> bool:
        return not self.revoked and not self.is_expired

    def to_dict(self) -> dict:
        return asdict(self)


class AuthLayer:
    """认证层：Token 申请、验证、撤销"""

    DEFAULT_TTL_SECONDS = 8 * 3600  # 默认 8 小时

    def __init__(self, token_store_path: Path = TOKEN_STORE_PATH):
        self.token_store_path = token_store_path

    # ---- Token 操作 ----

    def create_token(
        self,
        agent_id: str,
        scope: list[str],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> Token:
        """创建新的短期 Token"""
        now = datetime.utcnow()
        token = Token(
            session_id=f"sess_{uuid.uuid4().hex[:12]}",
            token=secrets.token_urlsafe(32),
            agent_id=agent_id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
            scope=scope,
            revoked=False,
        )
        self._save_token(token)
        return token

    def verify_token(self, token_str: str) -> tuple[bool, Optional[Token], str]:
        """
        验证 Token
        Returns: (is_valid, token_obj, reason)
        """
        token = self._load_token(token_str)

        if token is None:
            return False, None, "Token 不存在"

        if token.revoked:
            return False, None, "Token 已撤销"

        if token.is_expired:
            return False, None, "Token 已过期"

        return True, token, "OK"

    def revoke_token(self, token_str: str) -> tuple[bool, str]:
        """撤销 Token"""
        token = self._load_token(token_str)
        if token is None:
            return False, "Token 不存在"

        token.revoked = True
        self._save_token(token)
        return True, "OK"

    def revoke_session(self, session_id: str) -> tuple[bool, str]:
        """根据 session_id 撤销所有相关 Token"""
        tokens = self._load_all_tokens()
        found = False
        for t in tokens:
            if t.session_id == session_id:
                t.revoked = True
                found = True
        if found:
            self._save_all_tokens(tokens)
        return found, "OK" if found else "Session 不存在"

    def revoke_all(self) -> int:
        """撤销所有 Token"""
        tokens = self._load_all_tokens()
        count = 0
        for t in tokens:
            if not t.revoked:
                t.revoked = True
                count += 1
        self._save_all_tokens(tokens)
        return count

    def list_active_sessions(self) -> list[Token]:
        """列出所有活跃会话"""
        tokens = self._load_all_tokens()
        return [t for t in tokens if t.is_valid]

    def cleanup_expired(self) -> int:
        """清理过期 Token"""
        tokens = self._load_all_tokens()
        before = len(tokens)
        tokens = [t for t in tokens if t.is_valid]  # 保留未过期的
        self._save_all_tokens(tokens)
        return before - len(tokens)

    # ---- 私有方法 ----

    def _token_file(self, token: str) -> Path:
        # token 存储用 token 的前2位做二级目录，避免单文件过大
        subdir = token[:2]
        return self.token_store_path / subdir / f"{token}.json"

    def _save_token(self, token: Token) -> None:
        f = self._token_file(token.token)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(token.to_dict(), ensure_ascii=False))

    def _load_token(self, token_str: str) -> Optional[Token]:
        f = self._token_file(token_str)
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text())
            return Token(**data)
        except Exception:
            return None

    def _load_all_tokens(self) -> list[Token]:
        """加载所有 Token（用于 list/revoke_all 等操作）"""
        tokens = []
        if not self.token_store_path.exists():
            return tokens
        for f in self.token_store_path.rglob("*.json"):
            try:
                token = Token(**json.loads(f.read_text()))
                tokens.append(token)
            except Exception:
                pass
        return tokens

    def _save_all_tokens(self, tokens: list[Token]) -> None:
        """批量保存 Token"""
        # 先清空目录再重写
        if self.token_store_path.exists():
            import shutil
            shutil.rmtree(self.token_store_path)
        self.token_store_path.mkdir(parents=True, exist_ok=True)
        for t in tokens:
            self._save_token(t)
