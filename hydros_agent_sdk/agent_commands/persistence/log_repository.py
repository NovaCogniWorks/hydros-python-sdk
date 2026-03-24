"""
SQLite-backed command log persistence.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from threading import Lock
from typing import List, Optional, Sequence

from hydros_agent_sdk.protocol.models import CommandStatus

from .log_store import AgentCommandLogEntry, AgentCommandLogStore


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


class AgentCommandLogRepository(ABC):
    """仓储层只负责存取，不管上层业务语义。"""

    @abstractmethod
    def save(self, entry: AgentCommandLogEntry) -> AgentCommandLogEntry:
        raise NotImplementedError

    @abstractmethod
    def batch_save(self, entries: Sequence[AgentCommandLogEntry]) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def find_by_command_id(self, command_id: str, source_id: str) -> Optional[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def find_by_command_ids(self, command_ids: Sequence[str], source_id: str) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def find_by_acked(self, acked: bool, source_id: str) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def find_by_reported(self, reported: bool, limit: int = 100) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def find_by_status(
        self,
        statuses: Sequence[CommandStatus],
        source_id: str,
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        raise NotImplementedError

    @abstractmethod
    def update_command_acked(self, command_id: str, source_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_reported(self, command_ids: Sequence[str], source_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_command_result(self, entry: AgentCommandLogEntry) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_command_status(self, command_id: str, command_status: CommandStatus, source_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class SqliteAgentCommandLogRepository(AgentCommandLogRepository):
    """先给一个 sqlite 版，够本地持久化和后续演进。"""

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

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = Lock()
        self._closed = False
        with self._conn:
            self._conn.execute(self.SCHEMA_SQL)

    def save(self, entry: AgentCommandLogEntry) -> AgentCommandLogEntry:
        now = _utc_now()
        prepared = self._prepare_entry(entry, now=now)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO command_log (
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
        saved = self.find_by_command_id(prepared.command_id, prepared.source_id)
        return saved if saved is not None else prepared

    def batch_save(self, entries: Sequence[AgentCommandLogEntry]) -> List[AgentCommandLogEntry]:
        if not entries:
            return []

        now = _utc_now()
        prepared_entries = [self._prepare_entry(entry, now=now) for entry in entries]
        with self._lock, self._conn:
            self._conn.executemany(
                """
                INSERT INTO command_log (
                    tenant_id, biz_scenario_id, biz_scene_instance_id, source_id, source_type,
                    command_id, command_type, command_request,
                    source_agent_id, source_agent_name, target_agent_id, target_agent_name,
                    need_ack_reply, acked, reported,
                    command_status, command_response, error_code, error_detail,
                    gmt_create, gmt_modified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._entry_to_insert_tuple(entry) for entry in prepared_entries],
            )
        command_ids = [entry.command_id for entry in prepared_entries]
        return self.find_by_command_ids(command_ids, prepared_entries[0].source_id)

    def find_by_command_id(self, command_id: str, source_id: str) -> Optional[AgentCommandLogEntry]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM command_log WHERE command_id = ? AND source_id = ?",
                (command_id, source_id),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def find_by_command_ids(self, command_ids: Sequence[str], source_id: str) -> List[AgentCommandLogEntry]:
        if not command_ids:
            return []

        placeholders = ",".join("?" for _ in command_ids)
        params = list(command_ids) + [source_id]
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM command_log WHERE command_id IN ({placeholders}) AND source_id = ?",
                params,
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def find_by_acked(self, acked: bool, source_id: str) -> List[AgentCommandLogEntry]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM command_log
                WHERE acked = ? AND need_ack_reply = 1 AND source_id = ?
                """,
                (1 if acked else 0, source_id),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def find_by_reported(self, reported: bool, limit: int = 100) -> List[AgentCommandLogEntry]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM command_log
                WHERE command_status IN (?, ?) AND reported = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (CommandStatus.SUCCEED.value, CommandStatus.FAILED.value, 1 if reported else 0, limit),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def find_by_status(
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

    def update_reported(self, command_ids: Sequence[str], source_id: str) -> None:
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

    def update_command_result(self, entry: AgentCommandLogEntry) -> None:
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
                    _serialize_status(entry.command_status),
                    entry.command_response,
                    entry.error_code,
                    entry.error_detail,
                    _serialize_dt(_utc_now()),
                    entry.command_id,
                    entry.source_id,
                ),
            )

    def update_command_status(self, command_id: str, command_status: CommandStatus, source_id: str) -> None:
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


class SqliteAgentCommandLogStore(AgentCommandLogStore):
    """Runtime-facing sqlite log store without the extra service layer."""

    def __init__(
        self,
        db_path: str = ":memory:",
        repository: Optional[AgentCommandLogRepository] = None,
    ):
        self.repository = repository or SqliteAgentCommandLogRepository(db_path=db_path)

    def save_command_log(self, entry: AgentCommandLogEntry) -> None:
        existing = self.repository.find_by_command_id(entry.command_id, entry.source_id)
        if existing is None:
            self.repository.save(entry)

    def update_command_acked(self, command_id: str, source_id: str) -> None:
        self.repository.update_command_acked(command_id, source_id)

    def find_command_log_by_request_id(self, command_id: str, source_id: str) -> Optional[AgentCommandLogEntry]:
        return self.repository.find_by_command_id(command_id, source_id)

    def find_command_logs_by_ack(self, acked: bool, source_id: str) -> List[AgentCommandLogEntry]:
        return self.repository.find_by_acked(acked, source_id)

    def find_command_logs_by_reported(self, reported: bool, limit: int = 100) -> List[AgentCommandLogEntry]:
        return self.repository.find_by_reported(reported, limit=limit)

    def update_command_reported(self, command_ids: Sequence[str], source_id: str) -> None:
        self.repository.update_reported(command_ids, source_id)

    def find_command_logs_by_status(
        self,
        statuses: Sequence[CommandStatus],
        source_id: str,
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        return self.repository.find_by_status(statuses, source_id, limit=limit)

    def update_command_result(
        self,
        command_id: str,
        source_id: str,
        command_status: CommandStatus,
        command_response: str,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        self.repository.update_command_result(
            AgentCommandLogEntry(
                command_id=command_id,
                source_id=source_id,
                command_status=command_status,
                command_response=command_response,
                error_code=error_code,
                error_detail=error_detail,
            )
        )

    def update_command_status(self, command_id: str, source_id: str, command_status: CommandStatus) -> None:
        self.repository.update_command_status(command_id, command_status, source_id)

    def close(self) -> None:
        self.repository.close()
