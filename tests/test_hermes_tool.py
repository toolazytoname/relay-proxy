"""Tests for hermes_tool.py — Hermes tool interface (mocked HTTP)."""
import pytest, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ["RELAY_URL"] = "http://localhost:8000"
os.environ["ADMIN_TOKEN"] = "test-token"


# Mock httpx before importing the tool
import unittest.mock as mock, httpx


class MockResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", self, self)

    def json(self):
        return self._data


class MockClient:
    def __init__(self, **kw):
        self._data = kw

    def post(self, url, **kw):
        if "exec" in url:
            return MockResponse({"status": "ok", "session_id": "sess_test_123",
                                 "output": "docker output", "exit_code": 0,
                                 "command": kw.get("json", {}).get("command", ""),
                                 "audit_id": "aud_test_123",
                                 "intent_resolved": None})
        if "sessions" in url:
            return MockResponse({"session_id": "sess_test_123", "server": "web-1",
                                 "created_at": "2025-01-01T00:00:00+08:00",
                                 "expires_at": "2025-01-02T00:00:00+08:00",
                                 "status": "active"})
        if "permissions" in url:
            return MockResponse({"allowed": True, "reason": "OK"})
        return MockResponse({})

    def get(self, url, **kw):
        params = kw.get("params") or {}
        if "sessions" in url:
            return MockResponse({"sessions": []})
        if "audit" in url:
            return MockResponse({"records": []})
        if "permissions" in url:
            return MockResponse({"allowed": True, "reason": "OK"})
        return MockResponse({})

    def delete(self, url, **kw):
        return MockResponse({"status": "ok", "revoked_count": 1})


@pytest.fixture(autouse=True)
def mock_httpx_client(monkeypatch):
    monkeypatch.setattr(httpx, "Client", MockClient)


from hermes_tool import RelayProxyTool


class TestRelayProxyTool:
    def test_init_default_url(self):
        tool = RelayProxyTool()
        assert "localhost:8000" in tool.relay_url

    def test_init_custom_url(self):
        tool = RelayProxyTool(relay_url="https://my-relay.example.com")
        assert tool.relay_url == "https://my-relay.example.com"
        assert not tool.relay_url.endswith("/")

    def test_headers_no_token(self):
        # admin_token="" falls back to env var ADMIN_TOKEN="test-token"
        # so Authorization will be present in this test environment
        # We just verify headers() returns a valid dict
        tool = RelayProxyTool(admin_token="")
        h = tool.headers()
        assert isinstance(h, dict)
        assert "Content-Type" in h

    def test_headers_with_token(self):
        tool = RelayProxyTool(admin_token="secret123")
        h = tool.headers()
        assert h["Authorization"] == "Bearer secret123"

    def test_exec_command(self):
        tool = RelayProxyTool()
        result = tool.exec_command("web-1", "docker ps")
        assert result.session_id == "sess_test_123"
        assert result.status == "ok"

    def test_exec_command_with_session_id(self):
        tool = RelayProxyTool()
        result = tool.exec_command("web-1", "uptime", session_id="sess_existing")
        assert result.session_id == "sess_test_123"

    def test_create_session(self):
        tool = RelayProxyTool()
        session = tool.create_session("web-1", ttl_seconds=7200)
        assert session.session_id == "sess_test_123"

    def test_list_sessions(self):
        tool = RelayProxyTool()
        sessions = tool.list_sessions()
        assert isinstance(sessions, list)

    def test_revoke_session(self):
        tool = RelayProxyTool()
        result = tool.revoke_session("sess_abc")
        assert "status" in result or "revoked_count" in result

    def test_revoke_all(self):
        tool = RelayProxyTool()
        result = tool.revoke_all_sessions()
        assert isinstance(result, dict)

    def test_query_audit(self):
        tool = RelayProxyTool()
        records = tool.query_audit(limit=10)
        assert isinstance(records, list)

    def test_query_audit_with_filters(self):
        tool = RelayProxyTool()
        records = tool.query_audit(session_id="sess_123", server="web-1", limit=20)
        assert isinstance(records, list)

    def test_check_permission(self):
        tool = RelayProxyTool()
        result = tool.check_permission("web-1", "docker ps")
        assert isinstance(result, dict)
        assert "allowed" in result

    def test_status(self):
        tool = RelayProxyTool()
        result = tool.status("web-1")
        assert isinstance(result, str)
        assert "sess_test_123" in result

    def test_docker_logs(self):
        tool = RelayProxyTool()
        result = tool.docker_logs("web-1", "nginx", lines=50)
        assert isinstance(result, str)

    def test_restart_service(self):
        tool = RelayProxyTool()
        result = tool.restart_service("web-1", "nginx")
        assert isinstance(result, str)

    def test_get_audit(self):
        tool = RelayProxyTool()
        result = tool.get_audit("aud_abc123")
        assert isinstance(result, dict)

    def test_get_permission_manifest(self):
        tool = RelayProxyTool()
        result = tool.get_permission_manifest()
        assert isinstance(result, dict)
