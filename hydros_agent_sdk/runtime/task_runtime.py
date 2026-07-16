"""Runtime for one coordination task."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Thread, current_thread
from typing import Callable, Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.logging_config import (
    set_biz_component,
    set_biz_scene_instance_id,
    set_hydros_cluster_id,
    set_hydros_node_id,
)
from hydros_agent_sdk.protocol.commands import (
    HydroEventCommand,
    SimCommand,
    SimTaskInitRequest,
    SimTaskTerminateRequest,
)
from hydros_agent_sdk.state_manager import AgentStateManager

from .coordination_error_response_factory import CoordinationErrorResponseFactory
from .coordination_router import CoordinationCommandRouter


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundCommand:
    command: SimCommand
    received_at: float


class TaskRuntime:
    """Own the ordered command mailbox and callback dispatch for one task."""

    def __init__(
        self,
        context_id: str,
        callback: SimCoordinationCallback,
        state_manager: AgentStateManager,
        outbound_submitter: Callable[[SimCommand], None],
        mailbox_size: int = 1000,
        on_closed: Optional[Callable[[str, "TaskRuntime"], None]] = None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        if not context_id:
            raise ValueError("context_id is required")

        self.context_id = context_id
        self.callback = callback
        self.state_manager = state_manager
        self.outbound_submitter = outbound_submitter
        self.on_closed = on_closed
        self.logger = log or logger
        self.running = Event()
        self.closed = Event()
        self.mailbox: Queue[InboundCommand] = Queue(maxsize=mailbox_size)
        self.worker_thread: Optional[Thread] = None
        self.router = CoordinationCommandRouter(
            callback=self.callback,
            context_id_getter=self.command_context_id,
            event_type_getter=self.command_event_type,
            log=self.logger,
        )
        self.error_response_factory = CoordinationErrorResponseFactory(
            state_manager=self.state_manager,
            callback=self.callback,
            log=self.logger,
        )

    def start(self) -> None:
        if self.closed.is_set():
            raise RuntimeError(f"TaskRuntime {self.context_id!r} is closed")
        if self.running.is_set():
            return
        self.running.set()
        self.worker_thread = Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"TaskWorker:{self.context_id}",
        )
        self.worker_thread.start()

    def stop(self) -> None:
        self._close()
        worker = self.worker_thread
        if worker is not None and worker is not current_thread() and worker.is_alive():
            worker.join(timeout=5)

    def enqueue(self, command: SimCommand) -> None:
        """Add a parsed command to this task's ordered mailbox."""
        self._require_own_context(command)
        if not self.running.is_set():
            raise RuntimeError(f"TaskRuntime {self.context_id!r} is not running")

        item = InboundCommand(command=command, received_at=time.monotonic())
        try:
            self.mailbox.put_nowait(item)
        except Full as error:
            raise RuntimeError(
                f"TaskRuntime mailbox is full: context={self.context_id}, "
                f"capacity={self.mailbox.maxsize}"
            ) from error

        self.logger.debug(
            "Task command enqueued: type=%s, id=%s, context=%s, queueSize=%s",
            command.command_type,
            command.command_id,
            self.context_id,
            self.mailbox.qsize(),
        )

    def handle(self, command: SimCommand) -> None:
        """Dispatch one command and convert callback failures into responses."""
        self._require_own_context(command)
        self._set_logging_context()
        try:
            self._submit_result(self.router.dispatch(command))
        except Exception as error:
            self.logger.error(
                "Error handling command %s: %s", command.command_type, error, exc_info=True
            )
            error_response = self.error_response_factory.create(command, error)
            if error_response is not None:
                self.outbound_submitter(error_response)
        finally:
            if isinstance(command, SimTaskTerminateRequest):
                self._close()
            elif isinstance(command, SimTaskInitRequest):
                if not self.state_manager.has_active_context(command.context):
                    self._close()

    def _worker_loop(self) -> None:
        worker_name = current_thread().name
        self.logger.info("Task command worker started: %s", worker_name)
        while self.running.is_set():
            try:
                item = self.mailbox.get(timeout=0.2)
            except Empty:
                continue

            command = item.command
            started_at = time.monotonic()
            try:
                self.logger.debug(
                    "Task command handling started: type=%s, id=%s, context=%s, "
                    "queueWaitMs=%.2f, worker=%s",
                    command.command_type,
                    command.command_id,
                    self.context_id,
                    (started_at - item.received_at) * 1000,
                    worker_name,
                )
                self.handle(command)
                self.logger.debug(
                    "Task command handled: type=%s, id=%s, context=%s, "
                    "handlerDurationMs=%.2f, worker=%s",
                    command.command_type,
                    command.command_id,
                    self.context_id,
                    (time.monotonic() - started_at) * 1000,
                    worker_name,
                )
            except Exception as error:
                self.logger.error(
                    "Error in task worker %s: type=%s, id=%s, context=%s, error=%s",
                    worker_name,
                    command.command_type,
                    command.command_id,
                    self.context_id,
                    error,
                    exc_info=True,
                )
            finally:
                self.mailbox.task_done()

        self.logger.info("Task command worker stopped: %s", worker_name)

    def _close(self) -> None:
        if self.closed.is_set():
            return
        self.running.clear()
        self.closed.set()
        if self.on_closed is not None:
            self.on_closed(self.context_id, self)

    def _require_own_context(self, command: SimCommand) -> None:
        command_context_id = self.command_context_id(command)
        if command_context_id != self.context_id:
            raise ValueError(
                f"Command context {command_context_id!r} does not belong to "
                f"TaskRuntime {self.context_id!r}"
            )

    def _submit_result(self, result) -> None:
        if result is None:
            return
        if isinstance(result, SimCommand):
            self.outbound_submitter(result)
            return
        if isinstance(result, (list, tuple)):
            for item in result:
                self._submit_result(item)
            return
        self.logger.debug("Ignoring unsupported callback result type: %s", type(result).__name__)

    def _set_logging_context(self) -> None:
        cluster_id = self.state_manager.get_cluster_id()
        if cluster_id:
            set_hydros_cluster_id(cluster_id)
        node_id = self.state_manager.get_node_id()
        if node_id:
            set_hydros_node_id(node_id)
        set_biz_scene_instance_id(self.context_id)
        component = self.callback.get_component()
        if component:
            set_biz_component(component)

    @staticmethod
    def command_context_id(command: SimCommand) -> Optional[str]:
        context = getattr(command, "context", None)
        return getattr(context, "biz_scene_instance_id", None)

    @staticmethod
    def command_event_type(command: SimCommand) -> Optional[str]:
        if isinstance(command, HydroEventCommand):
            return getattr(command.payload, "hydro_event_type", None)
        for attribute in (
            "time_series_data_changed_event",
            "outflow_time_series_data_changed_event",
            "hydro_event",
        ):
            event = getattr(command, attribute, None)
            if event is not None:
                return getattr(event, "hydro_event_type", None)
        return None
