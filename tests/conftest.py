"""pytest fixtures for relay-proxy tests."""
import pytest, sys, os
from pathlib import Path

# 确保 src 在 path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

@pytest.fixture
def mock_httpx(monkeypatch):
    """Mock httpx.Client so tests don't need a real server."""
    import httpx, json
    
    store = {}
    
    class FakeResponse:
        def __init__(self, data, status=200):
            self._data = data
            self.status_code = status
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", self, self)
        def json(self):
            return self._data
    
    class FakeClient:
        def __init__(self, **kw): pass
        def post(self, url, **kw):
            store["POST"] = (url, kw.get("json"))
            return FakeResponse({"status": "ok", "session_id": "sess_test_123"})
        def get(self, url, **kw):
            store["GET"] = (url, kw.get("params"))
            return FakeResponse({"sessions": []})
        def delete(self, url, **kw):
            store["DELETE"] = (url,)
            return FakeResponse({"revoked_count": 1})
    
    monkeypatch.setattr(httpx, "Client", FakeClient)
    return store
