"""Tests for auth.py — Token generation and session management."""
import pytest, sys, time, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from auth import AuthLayer, Token


@pytest.fixture
def tmp_store(tmp_path):
    """Use a temp directory for token storage so tests don't pollute each other."""
    store_path = tmp_path / "tokens"
    store_path.mkdir()
    return store_path


@pytest.fixture
def auth(tmp_store):
    return AuthLayer(token_store_path=tmp_store)


class TestToken:
    def test_token_is_expired_false(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"], ttl_seconds=3600)
        assert t.is_expired is False

    def test_token_is_expired_true(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"], ttl_seconds=-1)
        assert t.is_expired is True

    def test_token_is_valid_active(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"], ttl_seconds=3600)
        assert t.is_valid is True

    def test_token_is_valid_revoked(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"], ttl_seconds=3600)
        auth.revoke_token(t.token)
        # Token object is immutable copy — reload from store
        ok, _, reason = auth.verify_token(t.token)
        assert ok is False
        assert "撤销" in reason

    def test_token_to_dict(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"], ttl_seconds=3600)
        d = t.to_dict()
        assert "session_id" in d
        assert "token" in d
        assert d["agent_id"] == "test"
        assert d["scope"] == ["web-1"]
        assert d["revoked"] is False

    def test_token_session_id_prefix(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"])
        assert t.session_id.startswith("sess_")

    def test_token_unique(self, auth):
        t1 = auth.create_token(agent_id="test", scope=["web-1"])
        t2 = auth.create_token(agent_id="test", scope=["web-1"])
        assert t1.token != t2.token


class TestAuthLayer:
    def test_create_token(self, auth):
        t = auth.create_token(agent_id="agent-1", scope=["web-1", "web-2"], ttl_seconds=7200)
        assert t.agent_id == "agent-1"
        assert t.scope == ["web-1", "web-2"]
        assert t.revoked is False

    def test_verify_token_valid(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"])
        ok, token_obj, reason = auth.verify_token(t.token)
        assert ok is True
        assert token_obj.session_id == t.session_id
        assert reason == "OK"

    def test_verify_token_invalid_not_found(self, auth):
        ok, token_obj, reason = auth.verify_token("not.exist.at.all")
        assert ok is False
        assert token_obj is None
        assert "不存在" in reason

    def test_verify_token_revoked(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"])
        auth.revoke_token(t.token)
        ok, token_obj, reason = auth.verify_token(t.token)
        assert ok is False
        assert "撤销" in reason

    def test_verify_token_expired(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"], ttl_seconds=-1)
        ok, token_obj, reason = auth.verify_token(t.token)
        assert ok is False
        assert "过期" in reason

    def test_revoke_token(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"])
        ok, reason = auth.revoke_token(t.token)
        assert ok is True
        assert reason == "OK"

    def test_revoke_token_not_found(self, auth):
        ok, reason = auth.revoke_token("not.exist")
        assert ok is False
        assert "不存在" in reason

    def test_revoke_session(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1"])
        ok, reason = auth.revoke_session(t.session_id)
        assert ok is True
        # Verify it's revoked
        ok2, _, _ = auth.verify_token(t.token)
        assert ok2 is False

    def test_revoke_session_not_found(self, auth):
        ok, reason = auth.revoke_session("sess_does_not_exist")
        assert ok is False
        assert "不存在" in reason

    def test_revoke_all(self, auth):
        auth.create_token(agent_id="a", scope=["web-1"])
        auth.create_token(agent_id="b", scope=["web-2"])
        count = auth.revoke_all()
        assert count == 2
        assert len(auth.list_active_sessions()) == 0

    def test_list_active_sessions(self, auth):
        t1 = auth.create_token(agent_id="a", scope=["web-1"])
        t2 = auth.create_token(agent_id="b", scope=["web-2"])
        sessions = auth.list_active_sessions()
        assert len(sessions) == 2
        assert all(s.is_valid for s in sessions)

    def test_list_active_sessions_empty(self, tmp_store):
        auth = AuthLayer(token_store_path=tmp_store)
        assert auth.list_active_sessions() == []

    def test_cleanup_expired(self, auth):
        auth.create_token(agent_id="expired", scope=["web-1"], ttl_seconds=-1)
        auth.create_token(agent_id="valid", scope=["web-1"], ttl_seconds=3600)
        removed = auth.cleanup_expired()
        assert removed == 1
        assert len(auth.list_active_sessions()) == 1
        assert auth.list_active_sessions()[0].agent_id == "valid"

    def test_scope_parameter(self, auth):
        t = auth.create_token(agent_id="test", scope=["web-1", "db-1", "cache-1"])
        assert t.scope == ["web-1", "db-1", "cache-1"]
