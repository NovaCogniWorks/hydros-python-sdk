"""Coordination command inbound queue runtime."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from typing import Callable, Dict, Optional, Tuple

from hydros_agent_sdk.protocol.commands import (
    SimCommand,
    SimTaskInitRequest,
    SimTaskTerminateRequest,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundCommand:
    command: SimCommand
    received_at: float
    queue_name: str


class CoordinationInboundRuntime:
    """Owns inbound coordination command queues and worker threads."""

    def __init__(
        self,
        running: Event,
        handler: Callable[[SimCommand], None],
        context_id_getter: Callable[[SimCommand], Optional[str]],
        control_queue_size: int = 1000,
        business_queue_size: int = 1000,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.running = running
        self.handler = handler
        self.context_id_getter = context_id_getter
        self.logger = log or logger
        self.control_message_queue: Queue[InboundCommand] = Queue(maxsize=control_queue_size)
        self.business_queue_size = business_queue_size
        self.business_message_queues: Dict[str, Queue[InboundCommand]] = {}
        self.business_worker_threads: Dict[str, Thread] = {}
        self.business_workers_lock = RLock()
        self.control_worker_thread: Optional[Thread] = None

    def start_workers(self) -> None:
        """Start the control worker if it is not already running."""
        if self.control_worker_thread is None or not self.control_worker_thread.is_alive():
            self.control_worker_thread = Thread(
                target=self.worker_loop,
                args=(self.control_message_queue, "ControlWorker"),
                daemon=True,
                name="ControlWorker",
            )
            self.control_worker_thread.start()

    def stop_workers(self) -> None:
        """Wait briefly for inbound workers to stop after the running flag is cleared."""
        with self.business_workers_lock:
            business_workers = list(self.business_worker_threads.values())
            self.business_worker_threads.clear()
            self.business_message_queues.clear()

        for worker in [self.control_worker_thread, *business_workers]:
            if worker and worker.is_alive():
                worker.join(timeout=5)

    def enqueue(self, command: SimCommand) -> None:
        queue_name, target_queue = self.select_queue(command)
        item = InboundCommand(command=command, received_at=time.monotonic(), queue_name=queue_name)
        try:
            target_queue.put_nowait(item)
            self.logger.debug(
                "Inbound command enqueued: type=%s, id=%s, context=%s, queue=%s, queueSize=%s",
                command.command_type,
                command.command_id,
                self.context_id_getter(command),
                queue_name,
                target_queue.qsize(),
            )
        except Full:
            self.logger.error(
                "Inbound queue full: type=%s, id=%s, context=%s, queue=%s, capacity=%s",
                command.command_type,
                command.command_id,
                self.context_id_getter(command),
                queue_name,
                target_queue.maxsize,
            )

    def select_queue(self, command: SimCommand) -> Tuple[str, Queue[InboundCommand]]:
        if isinstance(command, (SimTaskInitRequest, SimTaskTerminateRequest)):
            return "control", self.control_message_queue

        context_id = self.context_id_getter(command) or "__no_context__"
        return f"business:{context_id}", self.get_or_start_business_queue(context_id)

    def get_or_start_business_queue(self, context_id: str) -> Queue[InboundCommand]:
        with self.business_workers_lock:
            business_queue = self.business_message_queues.get(context_id)
            if business_queue is None:
                business_queue = Queue(maxsize=self.business_queue_size)
                self.business_message_queues[context_id] = business_queue

            worker = self.business_worker_threads.get(context_id)
            if worker is None or not worker.is_alive():
                worker_name = f"BusinessWorker:{context_id}"
                worker = Thread(
                    target=self.worker_loop,
                    args=(business_queue, worker_name),
                    daemon=True,
                    name=worker_name,
                )
                self.business_worker_threads[context_id] = worker
                worker.start()
        return business_queue

    def worker_loop(self, source_queue: Queue[InboundCommand], worker_name: str) -> None:
        self.logger.info("Inbound command worker started: %s", worker_name)
        while self.running.is_set():
            try:
                item = source_queue.get(timeout=1)
            except Empty:
                continue

            queue_wait_ms = (time.monotonic() - item.received_at) * 1000
            started_at = time.monotonic()
            command = item.command
            try:
                self.logger.debug(
                    "Inbound command handling started: type=%s, id=%s, context=%s, "
                    "queue=%s, queueWaitMs=%.2f, worker=%s",
                    command.command_type,
                    command.command_id,
                    self.context_id_getter(command),
                    item.queue_name,
                    queue_wait_ms,
                    worker_name,
                )
                self.handler(command)
                duration_ms = (time.monotonic() - started_at) * 1000
                self.logger.debug(
                    "Inbound command handled: type=%s, id=%s, context=%s, "
                    "handlerDurationMs=%.2f, worker=%s",
                    command.command_type,
                    command.command_id,
                    self.context_id_getter(command),
                    duration_ms,
                    worker_name,
                )
            except Exception as exc:
                self.logger.error(
                    "Error in inbound worker %s: type=%s, id=%s, context=%s, error=%s",
                    worker_name,
                    command.command_type,
                    command.command_id,
                    self.context_id_getter(command),
                    exc,
                    exc_info=True,
                )
            finally:
                source_queue.task_done()

        self.logger.info("Inbound command worker stopped: %s", worker_name)
