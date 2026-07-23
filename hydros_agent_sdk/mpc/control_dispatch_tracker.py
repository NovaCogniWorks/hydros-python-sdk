"""跟踪 MPC 指令接受状态和真实的边缘执行终态。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from hydros_agent_sdk.agent_commands.runtime.control_execution_barrier import (
    ControlDispatchRecord,
    ControlExecutionBarrier,
    ControlExecutionError,
)
from hydros_agent_sdk.protocol.agent_commands import HydroStationTargetValueRequest
from hydros_agent_sdk.mpc.detail_identity import build_mpc_detail_identity


class MpcControlExecutionError(ControlExecutionError):
    """已下发的 MPC 控制指令未到达成功的边缘执行终态。"""


@dataclass
class MpcControlDispatchRecord(ControlDispatchRecord):
    optimize_step: int = 0
    horizon_step: int = 0
    biz_idem_key: str = ""
    node_id: int = 0
    dispatch_key: str = ""


class MpcControlDispatchTracker(ControlExecutionBarrier):
    """负责执行中的下发记录和终态完成屏障。"""

    def __init__(self) -> None:
        super().__init__(
            error_type=MpcControlExecutionError,
            execution_label="MPC control",
        )

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
            biz_scene_instance_id=biz_scene_instance_id,
            step=optimize_step,
            dispatched_at=datetime.now().isoformat(),
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
        )
        return self._register(record)  # type: ignore[return-value]

    def mark_dispatch_failed(
        self,
        records: Iterable[MpcControlDispatchRecord],
        error: Exception,
    ) -> List[MpcControlDispatchRecord]:
        return super().mark_dispatch_failed(
            records,
            error,
            error_code="MPC_CONTROL_COMMAND_DISPATCH_FAILED",
        )  # type: ignore[return-value]

    def await_all(
        self,
        records: List[MpcControlDispatchRecord],
        timeout_seconds: float,
    ) -> None:
        if not records:
            raise MpcControlExecutionError("MPC control dispatch produced no records")
        super().await_all(records, timeout_seconds)

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
