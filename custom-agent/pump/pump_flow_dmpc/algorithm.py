"""将泵站流量 DMPC solver 适配为 Hydros 标准控制算法。"""

from __future__ import annotations

import math

from hydros_agent_sdk.control_algorithms import (
    ControlActuatorTarget,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    SignalType,
)

from .errors import PumpFlowDmpcError
from .resolver import PumpFlowDmpcInputResolver
from .solver import PumpFlowDmpcSolver
from .types import PumpFlowDmpcArguments, PumpFlowDmpcDecision


class PumpStationFlowDmpcAlgorithm:
    """只返回泵机组叶片角度候选值的站内流量分配算法。"""

    algorithm_type = "pump_station_flow_dmpc"
    algorithm_version = "1.0.0"

    def __init__(
        self,
        solver: PumpFlowDmpcSolver,
        resolver: PumpFlowDmpcInputResolver,
    ) -> None:
        self._solver = solver
        self._resolver = resolver

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        if input_data.control_task_type != ControlTaskType.STATION_FLOW_ALLOCATION:
            return self._failed(
                input_data,
                "UNSUPPORTED_CONTROL_TASK",
                "pump_station_flow_dmpc only supports STATION_FLOW_ALLOCATION",
            )
        try:
            arguments = self._resolver.resolve(input_data)
            decision = self._solver.solve(arguments)
            return self._project(input_data, arguments, decision)
        except PumpFlowDmpcError as exc:
            return self._failed(input_data, exc.error_code, str(exc))

    def _project(
        self,
        input_data: ControlAlgorithmInput,
        arguments: PumpFlowDmpcArguments,
        decision: PumpFlowDmpcDecision,
    ) -> ControlAlgorithmOutput:
        if not math.isfinite(decision.predicted_station_flow) or not math.isfinite(decision.objective):
            return self._failed(
                input_data,
                "NON_FINITE_SOLVER_OUTPUT",
                "solver returned a non-finite flow prediction or objective",
            )
        if decision.completed:
            return ControlAlgorithmOutput(
                schema_version=input_data.schema_version,
                request_id=input_data.context.request_id,
                status=ControlAlgorithmStatus.COMPLETED,
                reason=decision.reason,
                results=[self._flow_result(decision)],
                next_state={
                    "last_predicted_flow": decision.predicted_station_flow,
                    "stable_step_count": 1,
                },
                evidence=self._evidence(arguments, decision),
            )

        targets = []
        for unit in arguments.units:
            blade_angle = decision.blade_angles.get(unit.unit_id)
            if blade_angle is None or not math.isfinite(blade_angle):
                return self._failed(
                    input_data,
                    "INVALID_SOLVER_OUTPUT",
                    "solver did not return a finite blade_angle for pump unit %s" % unit.unit_id,
                )
            if blade_angle < unit.min_blade_angle or blade_angle > unit.max_blade_angle:
                return self._failed(
                    input_data,
                    "INVALID_SOLVER_OUTPUT",
                    "solver blade_angle exceeds the declared range for pump unit %s" % unit.unit_id,
                )
            targets.append(
                ControlActuatorTarget(
                    object_type="Pump",
                    object_id=unit.unit_id,
                    target_values={"blade_angle": blade_angle},
                )
            )

        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.CONTINUE,
            reason=decision.reason,
            actuator_targets=targets,
            results=[self._flow_result(decision)],
            next_state={
                "previous_blade_angles": {
                    str(unit_id): blade_angle
                    for unit_id, blade_angle in decision.blade_angles.items()
                },
                "last_predicted_flow": decision.predicted_station_flow,
            },
            evidence=self._evidence(arguments, decision),
        )

    @staticmethod
    def _flow_result(decision: PumpFlowDmpcDecision) -> ControlSignal:
        return ControlSignal(
            type=SignalType.RESULT,
            object_type="PumpStation",
            object_id=decision.station_id,
            value_type="water_flow",
            value=decision.predicted_station_flow,
        )

    @staticmethod
    def _evidence(
        arguments: PumpFlowDmpcArguments,
        decision: PumpFlowDmpcDecision,
    ) -> dict[str, float | int]:
        return {
            "target_flow": arguments.target_flow,
            "current_flow": arguments.current_flow,
            "predicted_flow": decision.predicted_station_flow,
            "objective": decision.objective,
            "active_unit_count": len(arguments.units),
        }

    @staticmethod
    def _failed(
        input_data: ControlAlgorithmInput,
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
