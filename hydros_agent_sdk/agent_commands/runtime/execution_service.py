"""
Agent command handler 执行服务。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Callable, Dict, Optional

from hydros_agent_sdk.protocol.models import CommandStatus

from hydros_agent_sdk.agent_commands.models import (
    AgentCommand,
    AgentCommandRequest,
    build_ack_reply,
)
from hydros_agent_sdk.agent_commands.persistence import AgentCommandLogStore

from .handlers import AgentCommandHandler
from .registry import AgentCommandHandlerRegistry


logger = logging.getLogger(__name__)


class AgentCommandExecutionService:
    """把本地 handler 执行、状态更新和响应回写集中起来。"""

    def __init__(
        self,
        handler_registry: AgentCommandHandlerRegistry,
        command_log_store: AgentCommandLogStore,
        state_manager,
        enqueue_command: Callable[[AgentCommand], None],
        max_workers: int = 8,
    ):
        self.handler_registry = handler_registry
        self.command_log_store = command_log_store
        self.state_manager = state_manager
        self.enqueue_command = enqueue_command
        self.max_workers = max_workers

        self._worker_executor: Optional[ThreadPoolExecutor] = None
        self._inflight_requests: Dict[str, AgentCommandRequest] = {}
        self._lock = Lock()

    def start(self) -> None:
        if self._worker_executor is not None:
            return
        self._worker_executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="AgentCmdWorker",
        )

    def stop(self) -> None:
        if self._worker_executor is None:
            return
        self._worker_executor.shutdown(wait=True)
        self._worker_executor = None

    def execute(self, request: AgentCommandRequest) -> None:
        if self._worker_executor is None:
            raise RuntimeError("AgentCommandExecutionService 尚未启动")
        handler = self.handler_registry.get_handler(request.command_type)
        self._worker_executor.submit(self._run_handler, handler, request)

    def _run_handler(self, handler: AgentCommandHandler, request: AgentCommandRequest) -> None:
        command_id = request.command_id
        current_node_id = self._get_current_node_id()

        with self._lock:
            self._inflight_requests[command_id] = request

        try:
            request.command_status = CommandStatus.PROCESSING
            self.command_log_store.update_command_status(command_id, current_node_id, CommandStatus.PROCESSING)

            if request.need_ack_reply and request.source is not None:
                self.enqueue_command(build_ack_reply(request))

            response = handler.execute(request)
            if response is None:
                logger.warning("handler 没有返回响应: type=%s id=%s", request.command_type, command_id)
                return

        except Exception as exc:
            logger.error("执行 agent command handler 失败: type=%s id=%s", request.command_type, command_id, exc_info=True)
            response = handler.build_failure_response(request, exc)

        finally:
            with self._lock:
                self._inflight_requests.pop(command_id, None)

        self.command_log_store.update_command_result(
            command_id,
            current_node_id,
            response.command_status or CommandStatus.FAILED,
            response.model_dump_json(by_alias=True),
            response.error_code,
            response.error_message,
        )
        self.enqueue_command(response)

    def _get_current_node_id(self) -> str:
        return self.state_manager.get_node_id() or "UNKNOWN"
