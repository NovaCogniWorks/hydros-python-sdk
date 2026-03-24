"""
Agent command runtime assembly layer.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from hydros_agent_sdk.protocol.models import CommandStatus
from hydros_agent_sdk.state_manager import AgentStateManager

from hydros_agent_sdk.agent_commands.models import AgentCommand
from hydros_agent_sdk.agent_commands.persistence import (
    AgentCommandLogStore,
    InMemoryAgentCommandLogStore,
    SqliteAgentCommandLogStore,
)

from .log_ops import AgentCommandLogOperations
from .queue_service import AgentCommandQueueService
from .registry import AgentCommandHandlerRegistry


class AgentCommandRuntime:
    """把 registry、queue、log store 这几块拼起来。"""

    def __init__(
        self,
        state_manager: AgentStateManager,
        sender: Callable[[AgentCommand], None],
        handler_registry: Optional[AgentCommandHandlerRegistry] = None,
        log_store: Optional[AgentCommandLogStore] = None,
        sqlite_log_db_path: Optional[str] = None,
        use_sqlite_log_store: bool = False,
        pending_command_predicate: Optional[Callable[[AgentCommand], bool]] = None,
        pending_retry_delay_ms: int = 50,
        max_workers: int = 8,
    ):
        self.state_manager = state_manager
        self.handler_registry = handler_registry or AgentCommandHandlerRegistry()
        self._owns_log_store = log_store is None
        self.log_store = self._build_log_store(
            log_store=log_store,
            sqlite_log_db_path=sqlite_log_db_path,
            use_sqlite_log_store=use_sqlite_log_store,
        )
        self.log_ops = AgentCommandLogOperations(
            log_store=self.log_store,
            state_manager=self.state_manager,
        )
        self.queue_service = AgentCommandQueueService(
            handler_registry=self.handler_registry,
            log_store=self.log_store,
            state_manager=self.state_manager,
            sender=sender,
            pending_command_predicate=pending_command_predicate,
            pending_retry_delay_ms=pending_retry_delay_ms,
            max_workers=max_workers,
        )

    def start(self) -> None:
        self.queue_service.start()

    def stop(self) -> None:
        self.queue_service.stop()
        if self._owns_log_store:
            self.log_store.close()

    def handle_incoming_command(self, command: AgentCommand) -> None:
        self.queue_service.enqueue_incoming(command)

    def send_command(self, command: AgentCommand) -> None:
        self.queue_service.enqueue_outbound(command)

    def register_handler(self, handler) -> None:
        self.handler_registry.register_handler(handler)

    def set_pending_command_predicate(
        self,
        predicate: Optional[Callable[[AgentCommand], bool]],
    ) -> None:
        self.queue_service.set_pending_command_predicate(predicate)

    def find_unreported_command_logs(self, limit: int = 100):
        return self.log_ops.find_unreported_command_logs(limit=limit)

    def report_unreported_command_logs(self, consumer, limit: int = 100):
        return self.log_ops.report_once(consumer=consumer, limit=limit)

    def find_unacked_command_logs(self, limit: int = 100):
        return self.log_ops.find_unacked_command_logs(limit=limit)

    def find_incomplete_command_logs(
        self,
        statuses: Optional[Sequence[CommandStatus]] = None,
        limit: int = 100,
    ):
        if statuses is None:
            statuses = (CommandStatus.INIT, CommandStatus.PROCESSING)
        return self.log_ops.find_incomplete_command_logs(statuses=statuses, limit=limit)

    def replay_incomplete_requests(
        self,
        statuses: Sequence[CommandStatus] = (CommandStatus.INIT,),
        limit: int = 100,
    ):
        return self.log_ops.replay_incomplete_requests(
            sender=self.send_command,
            statuses=statuses,
            limit=limit,
        )

    def collect_command_log_snapshot(
        self,
        limit: int = 100,
        incomplete_statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
    ):
        return self.log_ops.collect_snapshot(
            limit=limit,
            incomplete_statuses=incomplete_statuses,
        )

    def collect_command_log_stats(
        self,
        limit: int = 100,
        incomplete_statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
    ):
        return self.log_ops.collect_stats(
            limit=limit,
            incomplete_statuses=incomplete_statuses,
        )

    @staticmethod
    def _build_log_store(
        log_store: Optional[AgentCommandLogStore],
        sqlite_log_db_path: Optional[str],
        use_sqlite_log_store: bool,
    ) -> AgentCommandLogStore:
        if log_store is not None:
            return log_store

        if use_sqlite_log_store or sqlite_log_db_path is not None:
            return SqliteAgentCommandLogStore(db_path=sqlite_log_db_path or ":memory:")

        return InMemoryAgentCommandLogStore()
