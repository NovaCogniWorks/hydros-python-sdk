"""ODD-DMPC 到 SDK 标准控制算法接口的适配器。

本模块只负责将 ODD-DMPC 的私有运行时对象映射为标准输入/输出，不承担
edge 设备写入、控制会话推进或跨进程 transport。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from hydros_agent_sdk.control_algorithms import (
    ControlActuatorTarget,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    SignalType,
)

from .local_controller import LocalController, StationControlContext
from .types import ControlAction, StationMemory, TransferBundle


@dataclass(frozen=True)
class OddDmpcSolveArguments:
    """调用 ``LocalController.solve`` 所需的 ODD-DMPC 私有运行时对象。"""

    mode: str
    station_ctx: StationControlContext
    upstream_prediction: Mapping[int, float]
    disturbance_forecast: Mapping[int, object]
    transfer_bundle: TransferBundle
    station_memory: StationMemory


class OddDmpcInputResolver(Protocol):
    """由 PumpCentralSchedulingAgent 将标准输入解析为 ODD-DMPC 私有对象。"""

    def resolve(self, input_data: ControlAlgorithmInput) -> OddDmpcSolveArguments:
        """解析一次 ODD-DMPC 计算所需的本地运行态。"""


class OddDmpcControlAlgorithm:
    """复用既有 ``LocalController`` 的站内流量分配标准算法实现。"""

    algorithm_type = "odd_dmpc"

    def __init__(
        self,
        local_controller: LocalController,
        input_resolver: OddDmpcInputResolver,
        algorithm_version: str = "1.0.0",
    ) -> None:
        self._local_controller = local_controller
        self._input_resolver = input_resolver
        self.algorithm_version = algorithm_version

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        """执行一次 ODD-DMPC，并把候选泵组控制值投影为标准输出。"""
        if input_data.control_task_type != ControlTaskType.STATION_FLOW_ALLOCATION:
            return self._failed_output(
                input_data,
                error_code="UNSUPPORTED_CONTROL_TASK",
                error_message="odd_dmpc only supports station flow allocation",
            )

        arguments = self._input_resolver.resolve(input_data)
        target_object_id = input_data.context.target_object_id
        if target_object_id is not None and target_object_id != arguments.station_ctx.station_id:
            return self._failed_output(
                input_data,
                error_code="TARGET_STATION_MISMATCH",
                error_message="input target_object_id does not match ODD-DMPC station context",
            )

        action = self._local_controller.solve(
            mode=arguments.mode,
            station_ctx=arguments.station_ctx,
            upstream_prediction=arguments.upstream_prediction,
            disturbance_forecast=arguments.disturbance_forecast,
            transfer_bundle=arguments.transfer_bundle,
            station_memory=arguments.station_memory,
        )
        return self._to_output(input_data, action)

    @staticmethod
    def _to_output(
        input_data: ControlAlgorithmInput,
        action: ControlAction,
    ) -> ControlAlgorithmOutput:
        actuator_targets = [
            ControlActuatorTarget(
                object_type="Pump",
                object_id=unit_id,
                target_values={
                    "unit_status": float(action.unit_status.get(unit_id, 0)),
                    "blade_angle": float(action.unit_openings.get(unit_id, 0.0)),
                    "water_flow": float(action.unit_flows.get(unit_id, 0.0)),
                },
            )
            for unit_id in sorted(action.unit_status)
        ]
        results = [
            ControlSignal(
                type=SignalType.RESULT,
                object_type="PumpStation",
                object_id=action.station_id,
                value_type="water_flow",
                value=float(action.selected_flow),
            )
        ]
        for value_type, value in (
            ("back_water_level", action.predicted_back_level),
            ("front_water_level", action.predicted_front_level),
            ("water_head", action.predicted_head),
        ):
            if value is not None:
                results.append(
                    ControlSignal(
                        type=SignalType.RESULT,
                        object_type="PumpStation",
                        object_id=action.station_id,
                        value_type=value_type,
                        value=float(value),
                    )
                )

        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=(
                ControlAlgorithmStatus.HOLD
                if action.mode == "ODD1"
                else ControlAlgorithmStatus.CONTINUE
            ),
            reason=f"ODD_DMPC_{action.mode}",
            actuator_targets=actuator_targets,
            results=results,
            next_state={
                "mode": action.mode,
                "last_selected_flow": float(action.selected_flow),
                "unit_status": {str(unit_id): int(status) for unit_id, status in action.unit_status.items()},
                "unit_openings": {
                    str(unit_id): float(opening)
                    for unit_id, opening in action.unit_openings.items()
                },
            },
            evidence={
                "fit_score": float(action.fit_score),
                "objective": float(action.objective),
                "predicted_flow_error": float(action.predicted_flow_error),
                "predicted_level_error": float(action.predicted_level_error),
                "candidate_plan_count": len(action.candidate_plans),
            },
        )

    @staticmethod
    def _failed_output(
        input_data: ControlAlgorithmInput,
        *,
        error_code: str,
        error_message: str,
    ) -> ControlAlgorithmOutput:
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )
