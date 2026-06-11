"""
轻量级 runtime 队列与路由服务。
"""

from __future__ import annotations

import logging
import time
from queue import Empty, Queue
from threading import Event, Thread
from typing import Callable, Optional

from hydros_agent_sdk.protocol.models import CommandStatus

from hydros_agent_sdk.agent_commands.models import (
    AgentCommand,
    AgentCommandRequest,
    AgentCommandResponse,
    HydroCommandReceivedAckReply,
)

from .execution_service import AgentCommandExecutionService
from .routing import AgentCommandRoutePlanner
from .registry import AgentCommandHandlerRegistry

logger = logging.getLogger(__name__)


class AgentCommandQueueService:
    """把本地执行和远端发送收口到一个地方。"""

    def __init__(
        self,
        handler_registry: AgentCommandHandlerRegistry,
        state_manager,
        sender: Callable[[AgentCommand], None],
        pending_command_predicate: Optional[Callable[[AgentCommand], bool]] = None,
        pending_retry_delay_ms: int = 50,
        max_workers: int = 8,
    ):
        self.handler_registry = handler_registry
        self.state_manager = state_manager
        self.sender = sender
        self.pending_retry_delay_ms = pending_retry_delay_ms
        self.max_workers = max_workers

        self._command_queue: Queue[AgentCommand] = Queue()
        self._queue_thread: Optional[Thread] = None
        self._running = Event()
        self.route_planner = AgentCommandRoutePlanner(
            state_manager=self.state_manager,
            pending_command_predicate=pending_command_predicate,
        )
        self.execution_service = AgentCommandExecutionService(
            handler_registry=self.handler_registry,
            enqueue_command=self._command_queue.put,
            max_workers=self.max_workers,
        )

    def start(self) -> None:
        if self._running.is_set():
            return
        self.execution_service.start()
        self._running.set()
        self._queue_thread = Thread(target=self._queue_loop, daemon=True, name="AgentCommandQueue")
        self._queue_thread.start()

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        if self._queue_thread and self._queue_thread.is_alive():
            self._queue_thread.join(timeout=5)
        self._queue_thread = None
        self.execution_service.stop()

    def enqueue_incoming(self, command: AgentCommand) -> None:
        """从这里接收 MQTT 收到的命令。"""
        command.auth()

        if isinstance(command, AgentCommandRequest):
            if not self.route_planner.should_execute_locally(command):
                logger.debug("忽略非本地 request: type=%s id=%s", command.command_type, command.command_id)
                return
            command.command_status = CommandStatus.INIT
            self._command_queue.put(command)
            return

        if isinstance(command, HydroCommandReceivedAckReply):
            if not self.route_planner.should_track_inbound(command):
                logger.debug("忽略非本地 ACK: type=%s id=%s", command.command_type, command.command_id)
            return

        if isinstance(command, AgentCommandResponse):
            if not self.route_planner.should_track_inbound(command):
                logger.debug("忽略非本地 response: type=%s id=%s", command.command_type, command.command_id)
            return

        logger.debug("忽略未知入站命令: type=%s id=%s", command.command_type, command.command_id)

    def enqueue_outbound(self, command: AgentCommand) -> None:
        """本地业务代码想发命令，就从这里进。"""
        command.auth()

        if isinstance(command, AgentCommandRequest):
            command.command_status = command.command_status or CommandStatus.INIT

        self._command_queue.put(command)

    def set_pending_command_predicate(
        self,
        predicate: Optional[Callable[[AgentCommand], bool]],
    ) -> None:
        self.route_planner.set_pending_command_predicate(predicate)

    def _queue_loop(self) -> None:
        while self._running.is_set():
            try:
                command = self._command_queue.get(timeout=1)
                self._dispatch_queued_command(command)
            except Empty:
                continue
            except Exception as exc:
                logger.error("Agent command queue loop 处理失败: %s", exc, exc_info=True)

    def _dispatch_queued_command(self, command: AgentCommand) -> None:
        if self.route_planner.should_send_remote(command):
            if self.route_planner.is_pending(command):
                time.sleep(max(self.pending_retry_delay_ms, 0) / 1000.0)
                self._command_queue.put(command)
                return
            self.sender(command)
            return

        if isinstance(command, AgentCommandRequest):
            if not self.route_planner.should_execute_locally(command):
                logger.debug("跳过非本地 request: type=%s id=%s", command.command_type, command.command_id)
                return
            self.execution_service.execute(command)
            return

        if isinstance(command, (HydroCommandReceivedAckReply, AgentCommandResponse)):
            self.enqueue_incoming(command)
            return

        logger.debug("跳过无法路由的命令: type=%s id=%s", command.command_type, command.command_id)
