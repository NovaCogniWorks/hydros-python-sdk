"""Track MPC command acceptance and real edge execution terminal state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, RLock
from time import monotonic
from typing import Dict, Iterable, List, Optional, Tuple

from hydros_agent_sdk.protocol.agent_commands import (
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.protocol.commands import EdgeControlExecutionReport
from hydros_agent_sdk.mpc.detail_identity import build_mpc_detail_identity


class MpcControlExecutionError(RuntimeError):
    """A dispatched MPC control did not reach a successful edge terminal state."""


@dataclass
class MpcControlDispatchRecord:
    command: HydroStationTargetValueRequest
    optimize_step: int
    horizon_step: int
    biz_idem_key: str
    node_id: int
    dispatch_key: str
    dispatched_at: str
    terminal_status: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    timed_out: bool = False
    completion: Event = field(default_factory=Event, repr=False, compare=False)


class MpcControlDispatchTracker:
    """Owns in-flight dispatch records and the terminal completion barrier."""

    def __init__(self) -> None:
        self._records: Dict[str, MpcControlDispatchRecord] = {}
        self._lock = RLock()

    def register(
        self,
        command: HydroStationTargetValueRequest,
        biz_scene_instance_id: str,
        optimize_step: int,
        horizon_step: int,
    ) -> MpcControlDispatchRecord:
        dispatch_key = self.build_dispatch_key(
            biz_scene_instance_id,
            optimize_step,
            horizon_step,
            command.object_id,
            command.target_value_type,
        )
        record = MpcControlDispatchRecord(
            command=command,
            optimize_step=optimize_step,
            horizon_step=horizon_step,
            biz_idem_key=build_mpc_detail_identity(
                optimize_step,
                horizon_step,
                command.object_id,
                command.object_id,
                command.target_value_type,
            ),
            node_id=command.object_id,
            dispatch_key=dispatch_key,
            dispatched_at=datetime.now().isoformat(),
        )
        with self._lock:
            self._records[command.command_id] = record
        return record

    def handle_response(
        self,
        response: HydroStationTargetValueResponse,
    ) -> Optional[Tuple[MpcControlDispatchRecord, str]]:
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
    ) -> Optional[Tuple[MpcControlDispatchRecord, str]]:
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
        records: Iterable[MpcControlDispatchRecord],
        error: Exception,
    ) -> List[MpcControlDispatchRecord]:
        failed: List[MpcControlDispatchRecord] = []
        with self._lock:
            for record in records:
                if record.terminal_status is not None:
                    continue
                record.terminal_status = "FAILED"
                record.error_code = "MPC_CONTROL_COMMAND_DISPATCH_FAILED"
                record.error_message = str(error)
                record.completion.set()
                failed.append(record)
        return failed

    def await_all(
        self,
        records: List[MpcControlDispatchRecord],
        timeout_seconds: float,
    ) -> None:
        if not records:
            raise MpcControlExecutionError("MPC control dispatch produced no records")

        deadline = monotonic() + max(0.001, timeout_seconds)
        for record in records:
            remaining = deadline - monotonic()
            if remaining <= 0 or not record.completion.wait(remaining):
                with self._lock:
                    for pending in records:
                        if not pending.completion.is_set():
                            pending.timed_out = True
                    self._cleanup_completed(records)
                raise MpcControlExecutionError(
                    "MPC control execution timed out: "
                    f"command_id={record.command.command_id}, timeout_seconds={timeout_seconds}"
                )

        failures = [record for record in records if record.terminal_status != "COMPLETED"]
        with self._lock:
            self._cleanup(records)
        if failures:
            failure = failures[0]
            raise MpcControlExecutionError(
                "MPC control execution failed: "
                f"command_id={failure.command.command_id}, "
                f"error_code={failure.error_code}, error_message={failure.error_message}"
            )

    def _cleanup_completed(self, records: Iterable[MpcControlDispatchRecord]) -> None:
        self._cleanup(record for record in records if record.completion.is_set())

    def _cleanup(self, records: Iterable[MpcControlDispatchRecord]) -> None:
        for record in records:
            self._records.pop(record.command.command_id, None)

    @staticmethod
    def build_dispatch_key(
        biz_scene_instance_id: str,
        optimize_step: int,
        horizon_step: int,
        object_id: Optional[int],
        target_value_type: Optional[str],
    ) -> str:
        return ":".join(
            (
                "MPC_CTRL",
                str(biz_scene_instance_id),
                str(optimize_step),
                str(horizon_step),
                str(object_id),
                str(target_value_type),
            )
        )
