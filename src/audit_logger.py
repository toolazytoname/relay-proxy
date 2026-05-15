"""
Audit Logger - 完整决策链审计日志
参考: Teleport 决策链审计 + JSONL 结构化存储
"""

import uuid
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict


@dataclass
class AuditLog:
    """单条审计日志"""
    log_id: str
    timestamp: str
    session_id: str
    token_id: str

    # 请求
    request_raw: str
    request_parsed: dict

    # 策略检查
    server: str
    policy_matched: str
    command_checked: str
    policy_allowed: bool
    policy_reason: str

    # 执行
    ssh_session_id: Optional[str]
    command_executed: Optional[str]
    exit_code: Optional[int]
    duration_ms: Optional[int]

    # 响应
    status: str  # success / denied / error
    message: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class AuditLogger:
    """
    审计日志
    - JSONL 格式存储（按日分割）
    - 完整决策链记录
    - 支持查询和导出
    """

    def __init__(self, log_dir: Optional[Path] = None):
        if log_dir is None:
            log_dir = Path("/tmp/relay-proxy/logs")
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _log_file(self, date: Optional[str] = None) -> Path:
        """获取当天的日志文件路径"""
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")
        return self.log_dir / f"audit_{date}.jsonl"

    def log(
        self,
        session_id: str,
        token_id: str,
        request_raw: str,
        request_parsed: dict,
        server: str,
        policy_matched: str,
        command_checked: str,
        policy_allowed: bool,
        policy_reason: str,
        status: str,
        message: str,
        ssh_session_id: Optional[str] = None,
        command_executed: Optional[str] = None,
        exit_code: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> str:
        """写入一条审计日志"""
        log_id = f"log_{datetime.utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"

        log = AuditLog(
            log_id=log_id,
            timestamp=datetime.utcnow().isoformat() + "+08:00",
            session_id=session_id,
            token_id=token_id,
            request_raw=request_raw,
            request_parsed=request_parsed,
            server=server,
            policy_matched=policy_matched,
            command_checked=command_checked,
            policy_allowed=policy_allowed,
            policy_reason=policy_reason,
            ssh_session_id=ssh_session_id,
            command_executed=command_executed,
            exit_code=exit_code,
            duration_ms=duration_ms,
            status=status,
            message=message,
        )

        # 追加写入当日文件
        f = self._log_file()
        with open(f, "a", encoding="utf-8") as fp:
            fp.write(log.to_json() + "\n")

        return log_id

    def query(
        self,
        date: Optional[str] = None,
        session_id: Optional[str] = None,
        server: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询审计日志"""
        results = []
        f = self._log_file(date)
        if not f.exists():
            return results

        with open(f, "r", encoding="utf-8") as fp:
            for line in fp:
                try:
                    entry = json.loads(line.strip())
                    # 过滤
                    if session_id and entry.get("session_id") != session_id:
                        continue
                    if server and entry.get("server") != server:
                        continue
                    if status and entry.get("status") != status:
                        continue
                    results.append(entry)
                    if len(results) >= limit:
                        break
                except json.JSONDecodeError:
                    continue

        return results

    def export(
        self,
        from_date: str,
        to_date: str,
        output_path: Path,
        session_id: Optional[str] = None,
        server: Optional[str] = None,
    ) -> int:
        """导出日志到文件（支持日期范围）"""
        from datetime import datetime, timedelta

        start = datetime.strptime(from_date, "%Y-%m-%d")
        end = datetime.strptime(to_date, "%Y-%m-%d")
        count = 0

        with open(output_path, "w", encoding="utf-8") as out:
            current = start
            while current <= end:
                date_str = current.strftime("%Y-%m-%d")
                f = self._log_file(date_str)
                if f.exists():
                    with open(f, "r", encoding="utf-8") as inp:
                        for line in inp:
                            try:
                                entry = json.loads(line.strip())
                                if session_id and entry.get("session_id") != session_id:
                                    continue
                                if server and entry.get("server") != server:
                                    continue
                                out.write(line)
                                count += 1
                            except json.JSONDecodeError:
                                continue
                current += timedelta(days=1)

        return count

    def recent(self, limit: int = 50) -> list[dict]:
        """获取最近日志"""
        return self.query(date=None, limit=limit)
