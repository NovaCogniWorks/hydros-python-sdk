"""
智能体指令 runtime 装配层。
"""

from __future__ import annotations

from typing import Callable, Optional

from hydros_agent_sdk.state_manager import AgentStateManager

from hydros_agent_sdk.agent_commands.models import AgentCommand

from .queue_service import AgentCommandQueueService
from .registry import AgentCommandHandlerRegistry


class AgentCommandRuntime:
    """把 registry 和 queue 拼起来。"""

    def __init__(
        self,
        state_manager: AgentStateManager,
        sender: Callable[[AgentCommand], None],
        handler_registry: Optional[AgentCommandHandlerRegistry] = None,
        pending_command_predicate: Optional[Callable[[AgentCommand], bool]] = None,
        pending_retry_delay_ms: int = 50,
        max_workers: int = 8,
    ):
        self.state_manager = state_manager
        self.handler_registry = handler_registry or AgentCommandHandlerRegistry()
        self.queue_service = AgentCommandQueueService(
            handler_registry=self.handler_registry,
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

    def add_ack_listener(self, listener) -> None:
        self.queue_service.add_ack_listener(listener)

    def add_response_listener(self, listener) -> None:
        self.queue_service.add_response_listener(listener)
