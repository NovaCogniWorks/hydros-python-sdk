"""
Minimal command log store abstractions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional, Sequence, Tuple

from hydros_agent_sdk.protocol.models import CommandStatus


@dataclass
class AgentCommandLogEntry:
    """第一版先用内存结构把状态收住。"""

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
    """后面真要接库，就换一个实现。"""

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
    def find_command_logs_by_reported(self, reported: bool, limit: int = 100) -> List[AgentCommandLogEntry]:
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


class InMemoryAgentCommandLogStore(AgentCommandLogStore):
    """默认先给个内存版，够把第一版流程跑起来。"""

    def __init__(self):
        self._entries: Dict[Tuple[str, str], AgentCommandLogEntry] = {}
        self._lock = Lock()

    def save_command_log(self, entry: AgentCommandLogEntry) -> None:
        key = (entry.command_id, entry.source_id)
        with self._lock:
            if entry.acked is None:
                entry.acked = False
            if entry.reported is None:
                entry.reported = False
            self._entries.setdefault(key, entry)

    def update_command_acked(self, command_id: str, source_id: str) -> None:
        key = (command_id, source_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.acked = True

    def find_command_log_by_request_id(self, command_id: str, source_id: str) -> Optional[AgentCommandLogEntry]:
        key = (command_id, source_id)
        with self._lock:
            return self._entries.get(key)

    def find_command_logs_by_ack(self, acked: bool, source_id: str) -> List[AgentCommandLogEntry]:
        with self._lock:
            return [
                entry
                for entry in self._entries.values()
                if entry.source_id == source_id
                and bool(entry.need_ack_reply)
                and bool(entry.acked) is acked
            ]

    def find_command_logs_by_reported(self, reported: bool, limit: int = 100) -> List[AgentCommandLogEntry]:
        with self._lock:
            results = [
                entry
                for entry in self._entries.values()
                if entry.command_status in (CommandStatus.SUCCEED, CommandStatus.FAILED)
                and bool(entry.reported) is reported
            ]
        return results[:limit]

    def update_command_reported(self, command_ids: Sequence[str], source_id: str) -> None:
        if not command_ids:
            return

        with self._lock:
            for command_id in command_ids:
                entry = self._entries.get((command_id, source_id))
                if entry is not None:
                    entry.reported = True

    def find_command_logs_by_status(
        self,
        statuses: Sequence[CommandStatus],
        source_id: str,
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        status_set = set(statuses)
        if not status_set:
            return []

        with self._lock:
            results = [
                entry
                for entry in self._entries.values()
                if entry.source_id == source_id and entry.command_status in status_set
            ]
        return results[:limit]

    def update_command_result(
        self,
        command_id: str,
        source_id: str,
        command_status: CommandStatus,
        command_response: str,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        key = (command_id, source_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.acked = True
            entry.command_status = command_status
            entry.command_response = command_response
            entry.error_code = error_code
            entry.error_detail = error_detail
            if entry.reported is None:
                entry.reported = False

    def update_command_status(self, command_id: str, source_id: str, command_status: CommandStatus) -> None:
        key = (command_id, source_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.command_status = command_status

    def close(self) -> None:
        return None
