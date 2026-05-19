"""
统一的 runtime 日志操作。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

from hydros_agent_sdk.protocol.models import CommandStatus

from hydros_agent_sdk.agent_commands.models import AgentCommandRequest, parse_agent_command
from hydros_agent_sdk.agent_commands.persistence.command_log_store import AgentCommandLogEntry, AgentCommandLogStore


@dataclass
class AgentCommandLogStats:
    """给启动自检和排障看的轻量统计。"""

    source_id: str
    unacked_count: int
    incomplete_count: int
    unreported_count: int


@dataclass
class AgentCommandLogSnapshot:
    """把几类关键积压一次性收出来。"""

    source_id: str
    unacked_entries: List[AgentCommandLogEntry]
    incomplete_entries: List[AgentCommandLogEntry]
    unreported_entries: List[AgentCommandLogEntry]

    def to_stats(self) -> AgentCommandLogStats:
        return AgentCommandLogStats(
            source_id=self.source_id,
            unacked_count=len(self.unacked_entries),
            incomplete_count=len(self.incomplete_entries),
            unreported_count=len(self.unreported_entries),
        )


class AgentCommandLogOperations:
    """收口恢复、上报、诊断这些围绕 log_store 的辅助操作。"""

    def __init__(self, log_store: AgentCommandLogStore, state_manager):
        self.log_store = log_store
        self.state_manager = state_manager

    def find_unacked_command_logs(self, limit: int = 100) -> List[AgentCommandLogEntry]:
        return self.log_store.find_command_logs_by_ack(False, self._get_current_source_id())[:limit]

    def find_incomplete_command_logs(
        self,
        statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        return self.log_store.find_command_logs_by_status(
            statuses=statuses,
            source_id=self._get_current_source_id(),
            limit=limit,
        )

    def find_unreported_command_logs(self, limit: int = 100) -> List[AgentCommandLogEntry]:
        current_source_id = self._get_current_source_id()
        return self.log_store.find_command_logs_by_reported(
            False,
            source_id=current_source_id,
            limit=limit,
        )

    def report_once(
        self,
        consumer: Callable[[AgentCommandLogEntry], None],
        limit: int = 100,
    ) -> List[AgentCommandLogEntry]:
        entries = self.find_unreported_command_logs(limit=limit)
        if not entries:
            return []

        reported_ids_by_source: Dict[str, List[str]] = defaultdict(list)
        for entry in entries:
            consumer(entry)
            reported_ids_by_source[entry.source_id].append(entry.command_id)

        for source_id, command_ids in reported_ids_by_source.items():
            self.log_store.update_command_reported(command_ids, source_id)

        return entries

    def mark_reported(self, entries: Sequence[AgentCommandLogEntry]) -> None:
        reported_ids_by_source: Dict[str, List[str]] = defaultdict(list)
        for entry in entries:
            reported_ids_by_source[entry.source_id].append(entry.command_id)

        for source_id, command_ids in reported_ids_by_source.items():
            self.log_store.update_command_reported(command_ids, source_id)

    def rebuild_command_from_log(self, entry: AgentCommandLogEntry):
        if not entry.command_request:
            raise ValueError(f"command_id='{entry.command_id}' 缺少 command_request，没法恢复")
        return parse_agent_command(json.loads(entry.command_request))

    def rebuild_incomplete_requests(
        self,
        statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
        limit: int = 100,
    ) -> List[AgentCommandRequest]:
        requests: List[AgentCommandRequest] = []
        for entry in self.find_incomplete_command_logs(statuses=statuses, limit=limit):
            command = self.rebuild_command_from_log(entry)
            if isinstance(command, AgentCommandRequest):
                requests.append(command)
        return requests

    def replay_incomplete_requests(
        self,
        sender: Callable[[AgentCommandRequest], None],
        statuses: Sequence[CommandStatus] = (CommandStatus.INIT,),
        limit: int = 100,
    ) -> List[AgentCommandRequest]:
        requests = self.rebuild_incomplete_requests(statuses=statuses, limit=limit)
        for request in requests:
            sender(request)
        return requests

    def collect_snapshot(
        self,
        limit: int = 100,
        incomplete_statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
    ) -> AgentCommandLogSnapshot:
        source_id = self._get_current_source_id()
        return AgentCommandLogSnapshot(
            source_id=source_id,
            unacked_entries=self.find_unacked_command_logs(limit=limit),
            incomplete_entries=self.find_incomplete_command_logs(
                statuses=incomplete_statuses,
                limit=limit,
            ),
            unreported_entries=self.find_unreported_command_logs(limit=limit),
        )

    def collect_stats(
        self,
        limit: int = 100,
        incomplete_statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
    ) -> AgentCommandLogStats:
        return self.collect_snapshot(limit=limit, incomplete_statuses=incomplete_statuses).to_stats()

    def _get_current_source_id(self) -> str:
        return self.state_manager.get_node_id() or "UNKNOWN"
