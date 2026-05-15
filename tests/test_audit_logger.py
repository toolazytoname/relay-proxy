"""Tests for audit_logger.py — Audit trail."""
import pytest, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from audit_logger import AuditLogger, AuditLog


@pytest.fixture
def logger(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return AuditLogger(log_dir=log_dir)


class TestAuditLog:
    def test_to_dict(self):
        log = AuditLog(
            log_id="log_001",
            timestamp="2025-01-01T00:00:00+08:00",
            session_id="sess_123",
            token_id="tok_abc",
            request_raw="docker ps",
            request_parsed={"parsed": True},
            server="web-1",
            policy_matched="docker_manager",
            command_checked="docker ps",
            policy_allowed=True,
            policy_reason="OK",
            ssh_session_id="ssh_xyz",
            command_executed="docker ps",
            exit_code=0,
            duration_ms=150,
            status="success",
            message="OK",
        )
        d = log.to_dict()
        assert d["log_id"] == "log_001"
        assert d["exit_code"] == 0
        assert d["status"] == "success"

    def test_to_json(self):
        log = AuditLog(
            log_id="log_001", timestamp="", session_id="", token_id="",
            request_raw="", request_parsed={}, server="",
            policy_matched="", command_checked="", policy_allowed=True,
            policy_reason="", ssh_session_id=None, command_executed=None,
            exit_code=None, duration_ms=None, status="success", message="",
        )
        j = log.to_json()
        parsed = json.loads(j)
        assert parsed["log_id"] == "log_001"


class TestAuditLogger:
    def test_log_returns_log_id(self, logger):
        log_id = logger.log(
            session_id="sess_test",
            token_id="tok_test",
            request_raw="docker ps",
            request_parsed={"command": "docker ps"},
            server="web-1",
            policy_matched="docker_manager",
            command_checked="docker ps",
            policy_allowed=True,
            policy_reason="OK",
            status="success",
            message="OK",
        )
        assert log_id.startswith("log_")

    def test_log_all_fields(self, logger):
        log_id = logger.log(
            session_id="sess_all",
            token_id="tok_all",
            request_raw="uptime",
            request_parsed={},
            server="web-1",
            policy_matched="system_status",
            command_checked="uptime",
            policy_allowed=True,
            policy_reason="OK",
            status="success",
            message="OK",
            ssh_session_id="ssh_123",
            command_executed="uptime",
            exit_code=0,
            duration_ms=50,
        )
        record = logger.get_record(log_id)
        assert record is not None
        assert record["ssh_session_id"] == "ssh_123"
        assert record["exit_code"] == 0

    def test_log_denied(self, logger):
        log_id = logger.log(
            session_id="sess_denied",
            token_id="tok_denied",
            request_raw="rm -rf /",
            request_parsed={},
            server="web-1",
            policy_matched="",
            command_checked="rm -rf /",
            policy_allowed=False,
            policy_reason="命中全局黑名单",
            status="denied",
            message="拒绝执行",
        )
        record = logger.get_record(log_id)
        assert record["status"] == "denied"
        assert record["policy_allowed"] is False

    def test_query_by_session(self, logger):
        logger.log(session_id="sess_q", token_id="tok_q", request_raw="ls",
                   request_parsed={}, server="web-1", policy_matched="",
                   command_checked="ls", policy_allowed=True, policy_reason="",
                   status="success", message="")
        results = logger.query(session_id="sess_q")
        assert len(results) >= 1
        assert all(r["session_id"] == "sess_q" for r in results)

    def test_query_by_server(self, logger):
        logger.log(session_id="sess_s1", token_id="tok_s1", request_raw="ls",
                   request_parsed={}, server="web-1", policy_matched="",
                   command_checked="ls", policy_allowed=True, policy_reason="",
                   status="success", message="")
        logger.log(session_id="sess_s2", token_id="tok_s2", request_raw="ls",
                   request_parsed={}, server="web-2", policy_matched="",
                   command_checked="ls", policy_allowed=True, policy_reason="",
                   status="success", message="")
        results = logger.query(server="web-1")
        assert all(r["server"] == "web-1" for r in results)

    def test_query_by_status(self, logger):
        logger.log(session_id="sess_d", token_id="tok_d", request_raw="rm",
                   request_parsed={}, server="web-1", policy_matched="",
                   command_checked="rm", policy_allowed=False, policy_reason="",
                   status="denied", message="")
        logger.log(session_id="sess_s", token_id="tok_s", request_raw="ls",
                   request_parsed={}, server="web-1", policy_matched="",
                   command_checked="ls", policy_allowed=True, policy_reason="",
                   status="success", message="")
        results = logger.query(status="denied")
        assert all(r["status"] == "denied" for r in results)

    def test_query_limit(self, logger):
        for i in range(5):
            logger.log(session_id=f"sess_{i}", token_id=f"tok_{i}",
                       request_raw="ls", request_parsed={}, server="web-1",
                       policy_matched="", command_checked="ls",
                       policy_allowed=True, policy_reason="",
                       status="success", message="")
        results = logger.query(limit=3)
        assert len(results) == 3

    def test_get_record(self, logger):
        log_id = logger.log(session_id="sess_g", token_id="tok_g",
                            request_raw="ls", request_parsed={},
                            server="web-1", policy_matched="",
                            command_checked="ls", policy_allowed=True,
                            policy_reason="", status="success", message="")
        record = logger.get_record(log_id)
        assert record is not None
        assert record["log_id"] == log_id

    def test_get_record_not_found(self, logger):
        assert logger.get_record("log_does_not_exist") is None

    def test_recent(self, logger):
        for i in range(3):
            logger.log(session_id=f"sess_r{i}", token_id=f"tok_r{i}",
                       request_raw="ls", request_parsed={}, server="web-1",
                       policy_matched="", command_checked="ls",
                       policy_allowed=True, policy_reason="",
                       status="success", message="")
        results = logger.recent(limit=2)
        assert len(results) == 2

    def test_export(self, logger, tmp_path):
        logger.log(session_id="sess_exp", token_id="tok_exp",
                   request_raw="ls", request_parsed={}, server="web-1",
                   policy_matched="", command_checked="ls",
                   policy_allowed=True, policy_reason="",
                   status="success", message="")
        out_path = tmp_path / "export.jsonl"
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        count = logger.export(today, today, out_path, server="web-1")
        assert count >= 1
        assert out_path.exists()

    def test_log_file_created(self, logger, tmp_path):
        logger.log(session_id="sess_f", token_id="tok_f", request_raw="ls",
                   request_parsed={}, server="web-1", policy_matched="",
                   command_checked="ls", policy_allowed=True, policy_reason="",
                   status="success", message="")
        log_files = list((tmp_path / "logs").glob("audit_*.jsonl"))
        assert len(log_files) >= 1
