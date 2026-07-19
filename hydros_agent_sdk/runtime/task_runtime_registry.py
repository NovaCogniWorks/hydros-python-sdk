"""任务范围协调运行时注册表。"""

from __future__ import annotations

import logging
from threading import Event, RLock
from typing import Callable, Dict, Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import SimCommand, SimTaskInitRequest
from hydros_agent_sdk.state_manager import AgentStateManager

from .task_runtime import TaskRuntime


logger = logging.getLogger(__name__)


class TaskRuntimeRegistry:
    """为每个任务上下文创建并路由一个 :class:`TaskRuntime`。"""

    def __init__(
        self,
        callback: SimCoordinationCallback,
        state_manager: AgentStateManager,
        outbound_submitter: Callable[[SimCommand], None],
        mailbox_size: int = 1000,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.callback = callback
        self.state_manager = state_manager
        self.outbound_submitter = outbound_submitter
        self.mailbox_size = mailbox_size
        self.logger = log or logger
        self.running = Event()
        self._runtimes: Dict[str, TaskRuntime] = {}
        self._lock = RLock()

    def start(self) -> None:
        if self.running.is_set():
            return
        self.running.set()
        with self._lock:
            runtimes = list(self._runtimes.values())
        for runtime in runtimes:
            runtime.start()

    def stop(self) -> None:
        self.running.clear()
        with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        for runtime in runtimes:
            runtime.stop()

    def enqueue(self, command: SimCommand) -> None:
        context_id = TaskRuntime.command_context_id(command)
        if not context_id:
            raise ValueError("coordination command requires biz_scene_instance_id")

        if isinstance(command, SimTaskInitRequest):
            runtime = self.get_or_create(context_id)
        else:
            runtime = self.get(context_id)
            if runtime is None:
                raise RuntimeError(f"No TaskRuntime for context {context_id!r}")

        runtime.enqueue(command)

    def get(self, context_id: str) -> Optional[TaskRuntime]:
        with self._lock:
            return self._runtimes.get(context_id)

    def get_or_create(self, context_id: str) -> TaskRuntime:
        """返回任务运行时；处理初始化指令且运行时不存在时负责创建。"""
        if not context_id:
            raise ValueError("context_id is required")

        with self._lock:
            runtime = self._runtimes.get(context_id)
            if runtime is not None:
                return runtime
            runtime = TaskRuntime(
                context_id=context_id,
                callback=self.callback,
                state_manager=self.state_manager,
                outbound_submitter=self.outbound_submitter,
                mailbox_size=self.mailbox_size,
                on_closed=self._remove_closed,
                log=self.logger,
            )
            self._runtimes[context_id] = runtime

        if self.running.is_set():
            runtime.start()
        self.logger.info("TaskRuntime created: context=%s", context_id)
        return runtime

    def context_ids(self) -> set[str]:
        with self._lock:
            return set(self._runtimes)

    def _remove_closed(self, context_id: str, runtime: TaskRuntime) -> None:
        with self._lock:
            if self._runtimes.get(context_id) is runtime:
                self._runtimes.pop(context_id, None)
                self.logger.info("TaskRuntime released: context=%s", context_id)
