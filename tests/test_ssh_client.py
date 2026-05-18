"""Tests for ssh_client.py — SSH connection pool."""
import pytest, sys, time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ssh_client import SSHClientPool, SSHConnection, _pool_lock


@pytest.fixture
def pool():
    return SSHClientPool()


class TestSSHConnection:
    def test_ssh_connection_dataclass(self):
        client = MagicMock()
        conn = SSHConnection(client=client, server_name="web-1", last_used=time.time(), in_use=False)
        assert conn.server_name == "web-1"
        assert conn.in_use is False


class TestSSHClientPool:
    def test_init(self, pool):
        assert pool._pool == {}
        assert pool._keys == {}

    def test_register_key(self, pool):
        pool.register_key("web-1", "fake-private-key-content")
        assert "web-1" in pool._keys
        assert pool._keys["web-1"] == "fake-private-key-content"

    def test_execute_no_key_registered(self, pool):
        exit_code, stdout, stderr = pool.execute("unknown-server", {"host": "1.2.3.4"}, "echo ok", timeout=5)
        assert exit_code == -1
        assert "无法连接到服务器" in stderr

    def test_get_conn_unknown_server(self, pool):
        conn = pool._get_conn("unknown", {"host": "1.2.3.4"})
        assert conn is None

    def test_close(self, pool):
        pool._pool["web-1"] = SSHConnection(
            client=MagicMock(), server_name="web-1", last_used=time.time(), in_use=False
        )
        pool.close("web-1")
        assert "web-1" not in pool._pool

    def test_close_all(self, pool):
        pool._pool["web-1"] = SSHConnection(
            client=MagicMock(), server_name="web-1", last_used=time.time(), in_use=False
        )
        pool._pool["db-1"] = SSHConnection(
            client=MagicMock(), server_name="db-1", last_used=time.time(), in_use=False
        )
        pool.close_all()
        assert pool._pool == {}