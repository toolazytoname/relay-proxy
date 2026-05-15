"""Tests for cli_admin.py — Admin CLI (mocked HTTP)."""
import pytest, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["RELAY_URL"] = "http://localhost:8000"
os.environ["ADMIN_TOKEN"] = "test-token"

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
        pass

    def get(self, url, **kw):
        if "sessions" in url:
            return MockResponse({"sessions": [
                {"session_id": "sess_1", "server": "web-1",
                 "status": "active", "created_at": "2025-01-01T00:00:00+08:00",
                 "expires_at": "2025-01-01T01:00:00+08:00"}
            ]})
        if "audit" in url:
            return MockResponse({"records": [
                {"audit_id": "aud_1", "session_id": "sess_1",
                 "timestamp": "2025-01-01T00:00:00+08:00",
                 "command": "docker ps", "exit_code": 0,
                 "duration_ms": 50, "status": "success"}
            ]})
        return MockResponse({})

    def post(self, url, **kw):
        return MockResponse({"allowed": True, "reason": "OK"})

    def delete(self, url, **kw):
        return MockResponse({"status": "ok", "revoked_count": 1})


@pytest.fixture(autouse=True)
def mock_httpx_client(monkeypatch):
    monkeypatch.setattr(httpx, "Client", MockClient)


from cli_admin import RelayClient


class TestRelayClient:
    def test_init_default(self):
        client = RelayClient()
        assert "localhost" in client.url

    def test_init_custom(self):
        client = RelayClient(url="https://custom.fly.dev", token="mytoken")
        assert client.url == "https://custom.fly.dev"
        assert client.token == "mytoken"

    def test_headers_without_token(self):
        client = RelayClient(token="")
        h = client._headers()
        assert isinstance(h, dict)

    def test_headers_with_token(self):
        client = RelayClient(token="secret")
        h = client._headers()
        assert h["Authorization"] == "Bearer secret"

    def test_sessions_list(self):
        client = RelayClient()
        sessions = client.sessions_list()
        assert isinstance(sessions, list)

    def test_sessions_revoke(self):
        client = RelayClient()
        result = client.sessions_revoke("sess_1")
        assert isinstance(result, dict)

    def test_sessions_revoke_all(self):
        client = RelayClient()
        result = client.sessions_revoke_all()
        assert isinstance(result, dict)

    def test_audit_query(self):
        client = RelayClient()
        records = client.audit_query()
        assert isinstance(records, list)

    def test_audit_query_with_filters(self):
        client = RelayClient()
        records = client.audit_query(session_id="sess_1", server="web-1", limit=10)
        assert isinstance(records, list)

    def test_audit_get(self):
        client = RelayClient()
        record = client.audit_get("aud_1")
        assert isinstance(record, dict)

    def test_permissions_check(self):
        client = RelayClient()
        result = client.permissions_check("web-1", "docker ps")
        assert "allowed" in result

    def test_permissions_manifest(self):
        client = RelayClient()
        result = client.permissions_manifest()
        assert isinstance(result, dict)
