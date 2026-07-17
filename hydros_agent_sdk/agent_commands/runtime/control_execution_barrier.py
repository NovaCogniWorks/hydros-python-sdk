"""Generic central-side barrier for asynchronous edge control execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, RLock
from time import monotonic
from typing import Dict, Iterable, List, Optional, Tuple, Type

from hydros_agent_sdk.protocol.agent_commands import (
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.protocol.commands import EdgeControlExecutionReport


class ControlExecutionError(RuntimeError):
    """A control dispatched by central did not reach a successful edge terminal state."""


@dataclass
class ControlDispatchRecord:
    """One terminal-report-producing station control command registered before dispatch."""

    command: HydroStationTargetValueRequest
    biz_scene_instance_id: str
    step: int
    dispatched_at: str
    terminal_status: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    timed_out: bool = False
    completion: Event = field(default_factory=Event, repr=False, compare=False)


class ControlExecutionBarrier:
    """Track station controls until edge reports their terminal execution state.

    A station-target response only proves that the target accepted or started a
    command.  The barrier is released exclusively by the corresponding
    :class:`EdgeControlExecutionReport`, correlated with ``exec_command_id``.
    """

    def __init__(
        self,
        error_type: Type[ControlExecutionError] = ControlExecutionError,
        execution_label: str = "Control",
    ) -> None:
        self._records: Dict[str, ControlDispatchRecord] = {}
        self._lock = RLock()
        self._error_type = error_type
        self._execution_label = execution_label

    def register(
        self,
        command: HydroStationTargetValueRequest,
        biz_scene_instance_id: str,
        step: int,
    ) -> ControlDispatchRecord:
        return self._register(
            ControlDispatchRecord(
                command=command,
                biz_scene_instance_id=biz_scene_instance_id,
                step=step,
                dispatched_at=datetime.now().isoformat(),
            )
        )

    def _register(self, record: ControlDispatchRecord) -> ControlDispatchRecord:
        command_id = record.command.command_id
        if not command_id:
            raise ValueError("Control command must have a command_id before dispatch")
        with self._lock:
            if command_id in self._records:
                raise ValueError(f"Control command is already registered: {command_id}")
            self._records[command_id] = record
        return record

    def handle_response(
        self,
        response: HydroStationTargetValueResponse,
    ) -> Optional[Tuple[ControlDispatchRecord, str]]:
        """Record acceptance/rejection without treating acceptance as completion."""
        with self._lock:
            record = self._records.get(response.command_id)
            if record is None or record.terminal_status is not None:
                return None
            if response.command_status == "SUCCEED":
                return record, "STARTED"
            record.terminal_status = "FAILED"
            record.error_code = response.error_code
            record.error_message = response.error_message
            record.completion.set()
            return record, "FAILED"

    def handle_execution_report(
        self,
        report: EdgeControlExecutionReport,
    ) -> Optional[Tuple[ControlDispatchRecord, str]]:
        """Complete a registered command only when edge reports a terminal state."""
        with self._lock:
            record = self._records.get(report.exec_command_id)
            if record is None or record.terminal_status is not None:
                return None
            status = "COMPLETED" if report.exec_status == "COMPLETED" else "FAILED"
            record.terminal_status = status
            record.error_code = report.error_code
            record.error_message = report.error_message
            record.completion.set()
            if record.timed_out:
                self._records.pop(report.exec_command_id, None)
            return record, status

    def mark_dispatch_failed(
        self,
        records: Iterable[ControlDispatchRecord],
        error: Exception,
        error_code: str = "CONTROL_COMMAND_DISPATCH_FAILED",
    ) -> List[ControlDispatchRecord]:
        failed: List[ControlDispatchRecord] = []
        with self._lock:
            for record in records:
                if record.terminal_status is not None:
                    continue
                record.terminal_status = "FAILED"
                record.error_code = error_code
                record.error_message = str(error)
                record.completion.set()
                failed.append(record)
        return failed

    def await_all(
        self,
        records: List[ControlDispatchRecord],
        timeout_seconds: float,
    ) -> None:
        """Wait for every record, preserving unfinished records for late reports."""
        if not records:
            return

        deadline = monotonic() + max(0.001, timeout_seconds)
        for record in records:
            remaining = deadline - monotonic()
            if remaining <= 0 or not record.completion.wait(remaining):
                with self._lock:
                    for pending in records:
                        if not pending.completion.is_set():
                            pending.timed_out = True
                    self._cleanup_completed(records)
                raise self._error_type(
                    f"{self._execution_label} execution timed out: "
                    f"command_id={record.command.command_id}, timeout_seconds={timeout_seconds}"
                )

        failures = [record for record in records if record.terminal_status != "COMPLETED"]
        with self._lock:
            self._cleanup(records)
        if failures:
            failure = failures[0]
            raise self._error_type(
                f"{self._execution_label} execution failed: "
                f"command_id={failure.command.command_id}, "
                f"error_code={failure.error_code}, error_message={failure.error_message}"
            )

    def discard_by_biz_scene_instance_id(self, biz_scene_instance_id: str) -> None:
        """Discard task-scoped records during a completed task termination."""
        with self._lock:
            self._cleanup(
                record
                for record in self._records.values()
                if record.biz_scene_instance_id == biz_scene_instance_id
            )

    def _cleanup_completed(self, records: Iterable[ControlDispatchRecord]) -> None:
        self._cleanup(record for record in records if record.completion.is_set())

    def _cleanup(self, records: Iterable[ControlDispatchRecord]) -> None:
        for record in list(records):
            self._records.pop(record.command.command_id, None)
