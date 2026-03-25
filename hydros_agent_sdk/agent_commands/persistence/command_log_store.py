"""
最小化的 command 日志存储抽象和 sqlite 实现。
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import List, Optional, Sequence

from hydros_agent_sdk.protocol.models import CommandStatus


DEFAULT_AGENT_COMMAND_DB_PATH = "data/agent_data.db"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_bool(value: Optional[bool], default: bool = False) -> int:
    if value is None:
        return 1 if default else 0
    return 1 if value else 0


def _serialize_status(value: Optional[CommandStatus]) -> Optional[str]:
    if value is None:
        return None
    return value.value if isinstance(value, CommandStatus) else str(value)


def _deserialize_status(value: Optional[str]) -> Optional[CommandStatus]:
    if not value:
        return None
    return CommandStatus(value)


def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _deserialize_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _resolve_db_path() -> str:
    path = Path(DEFAULT_AGENT_COMMAND_DB_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@dataclass
class AgentCommandLogEntry:
    """先把 command 的关键状态收住，方便持久化和恢复。"""

    command_id: str
    source_id: str
    tenant_id: Optional[str] = None
    biz_scenario_id: Optional[str] = None
    biz_scene_instance_id: Optional[str] = None
    command_type: Optional[str] = None
    command_request: Optional[str] = None
    source_agent_id: Optional[str] = None
    source_agent_name: Optional[str] = None
    target_agent_id: Optional[str] = None
    target_agent_name: Optional[str] = None
    need_ack_reply: Optional[bool] = None
    acked: Optional[bool] = None
    command_status: Optional[CommandStatus] = None
    command_response: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    source_type: Optional[str] = None
    reported: Optional[bool] = None
    record_id: Optional[int] = None
    gmt_create: Optional[datetime] = None
    gmt_modified: Optional[datetime] = None


class AgentCommandLogStore(ABC):
    """后面真要换存储介质，就沿着这个接口替换。"""

    @abstractmethod
    def save_command_log(self, entry: AgentCommandLogEntry) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_command_acked(self, command_id: str, source_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_command_log_by_request_id(self, command_id: str, source_id: str) -> Optional[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def find_command_logs_by_ack(self, acked: bool, source_id: str) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def find_command_logs_by_reported(
        self,
        reported: bool,
        source_id: str,
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def update_command_reported(self, command_ids: Sequence[str], source_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_command_logs_by_status(
        self,
        statuses: Sequence[CommandStatus],
        source_id: str,
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def update_command_result(
        self,
        command_id: str,
        source_id: str,
        command_status: CommandStatus,
        command_response: str,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_command_status(self, command_id: str, source_id: str, command_status: CommandStatus) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class SqliteAgentCommandLogStore(AgentCommandLogStore):
    """直接面向 runtime 的 sqlite 实现，不再额外拆 repository。"""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS command_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT,
        biz_scenario_id TEXT,
        biz_scene_instance_id TEXT,
        source_id TEXT NOT NULL,
        source_type TEXT,
        command_id TEXT NOT NULL,
        command_type TEXT,
        command_request TEXT,
        source_agent_id TEXT,
        source_agent_name TEXT,
        target_agent_id TEXT,
        target_agent_name TEXT,
        need_ack_reply INTEGER NOT NULL DEFAULT 0,
        acked INTEGER NOT NULL DEFAULT 0,
        reported INTEGER NOT NULL DEFAULT 0,
        command_status TEXT,
        command_response TEXT,
        error_code TEXT,
        error_detail TEXT,
        gmt_create TEXT NOT NULL,
        gmt_modified TEXT NOT NULL,
        UNIQUE(command_id, source_id)
    );
    """

    def __init__(self):
        self.db_path = _resolve_db_path()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = Lock()
        self._closed = False
        with self._conn:
            self._conn.execute(self.SCHEMA_SQL)

    def save_command_log(self, entry: AgentCommandLogEntry) -> None:
        prepared = self._prepare_entry(entry, now=_utc_now())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO command_log (
                    tenant_id, biz_scenario_id, biz_scene_instance_id, source_id, source_type,
                    command_id, command_type, command_request,
                    source_agent_id, source_agent_name, target_agent_id, target_agent_name,
                    need_ack_reply, acked, reported,
                    command_status, command_response, error_code, error_detail,
                    gmt_create, gmt_modified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._entry_to_insert_tuple(prepared),
            )

    def update_command_acked(self, command_id: str, source_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE command_log
                SET acked = 1, gmt_modified = ?
                WHERE command_id = ? AND source_id = ?
                """,
                (_serialize_dt(_utc_now()), command_id, source_id),
            )

    def find_command_log_by_request_id(self, command_id: str, source_id: str) -> Optional[AgentCommandLogEntry]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM command_log WHERE command_id = ? AND source_id = ?",
                (command_id, source_id),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def find_command_logs_by_ack(self, acked: bool, source_id: str) -> List[AgentCommandLogEntry]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM command_log
                WHERE acked = ? AND need_ack_reply = 1 AND source_id = ?
                """,
                (1 if acked else 0, source_id),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def find_command_logs_by_reported(
        self,
        reported: bool,
        source_id: str,
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM command_log
                WHERE command_status IN (?, ?) AND reported = ? AND source_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (
                    CommandStatus.SUCCEED.value,
                    CommandStatus.FAILED.value,
                    1 if reported else 0,
                    source_id,
                    limit,
                ),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def update_command_reported(self, command_ids: Sequence[str], source_id: str) -> None:
        if not command_ids:
            return

        placeholders = ",".join("?" for _ in command_ids)
        params = [_serialize_dt(_utc_now())] + list(command_ids) + [source_id]
        with self._lock, self._conn:
            self._conn.execute(
                f"""
                UPDATE command_log
                SET reported = 1, gmt_modified = ?
                WHERE command_id IN ({placeholders}) AND source_id = ?
                """,
                params,
            )

    def find_command_logs_by_status(
        self,
        statuses: Sequence[CommandStatus],
        source_id: str,
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        if not statuses:
            return []

        placeholders = ",".join("?" for _ in statuses)
        params = [_serialize_status(status) for status in statuses] + [source_id, limit]
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM command_log
                WHERE command_status IN ({placeholders}) AND source_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def update_command_result(
        self,
        command_id: str,
        source_id: str,
        command_status: CommandStatus,
        command_response: str,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE command_log
                SET acked = 1,
                    command_status = ?,
                    command_response = ?,
                    error_code = ?,
                    error_detail = ?,
                    gmt_modified = ?
                WHERE command_id = ? AND source_id = ?
                """,
                (
                    _serialize_status(command_status),
                    command_response,
                    error_code,
                    error_detail,
                    _serialize_dt(_utc_now()),
                    command_id,
                    source_id,
                ),
            )

    def update_command_status(self, command_id: str, source_id: str, command_status: CommandStatus) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE command_log
                SET command_status = ?, gmt_modified = ?
                WHERE command_id = ? AND source_id = ?
                """,
                (_serialize_status(command_status), _serialize_dt(_utc_now()), command_id, source_id),
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def _prepare_entry(self, entry: AgentCommandLogEntry, now: datetime) -> AgentCommandLogEntry:
        return AgentCommandLogEntry(
            record_id=entry.record_id,
            tenant_id=entry.tenant_id,
            biz_scenario_id=entry.biz_scenario_id,
            biz_scene_instance_id=entry.biz_scene_instance_id,
            command_id=entry.command_id,
            source_id=entry.source_id,
            command_type=entry.command_type,
            command_request=entry.command_request,
            source_agent_id=entry.source_agent_id,
            source_agent_name=entry.source_agent_name,
            target_agent_id=entry.target_agent_id,
            target_agent_name=entry.target_agent_name,
            need_ack_reply=bool(entry.need_ack_reply),
            acked=bool(entry.acked),
            command_status=entry.command_status,
            command_response=entry.command_response,
            error_code=entry.error_code,
            error_detail=entry.error_detail,
            source_type=entry.source_type,
            reported=bool(entry.reported),
            gmt_create=entry.gmt_create or now,
            gmt_modified=entry.gmt_modified or now,
        )

    def _entry_to_insert_tuple(self, entry: AgentCommandLogEntry) -> tuple:
        return (
            entry.tenant_id,
            entry.biz_scenario_id,
            entry.biz_scene_instance_id,
            entry.source_id,
            entry.source_type,
            entry.command_id,
            entry.command_type,
            entry.command_request,
            entry.source_agent_id,
            entry.source_agent_name,
            entry.target_agent_id,
            entry.target_agent_name,
            _serialize_bool(entry.need_ack_reply),
            _serialize_bool(entry.acked),
            _serialize_bool(entry.reported),
            _serialize_status(entry.command_status),
            entry.command_response,
            entry.error_code,
            entry.error_detail,
            _serialize_dt(entry.gmt_create),
            _serialize_dt(entry.gmt_modified),
        )

    def _row_to_entry(self, row: sqlite3.Row) -> AgentCommandLogEntry:
        return AgentCommandLogEntry(
            record_id=row["id"],
            tenant_id=row["tenant_id"],
            biz_scenario_id=row["biz_scenario_id"],
            biz_scene_instance_id=row["biz_scene_instance_id"],
            command_id=row["command_id"],
            source_id=row["source_id"],
            command_type=row["command_type"],
            command_request=row["command_request"],
            source_agent_id=row["source_agent_id"],
            source_agent_name=row["source_agent_name"],
            target_agent_id=row["target_agent_id"],
            target_agent_name=row["target_agent_name"],
            need_ack_reply=bool(row["need_ack_reply"]),
            acked=bool(row["acked"]),
            command_status=_deserialize_status(row["command_status"]),
            command_response=row["command_response"],
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            source_type=row["source_type"],
            reported=bool(row["reported"]),
            gmt_create=_deserialize_dt(row["gmt_create"]),
            gmt_modified=_deserialize_dt(row["gmt_modified"]),
        )
