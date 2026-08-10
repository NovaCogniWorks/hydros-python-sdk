"""
Pump station flow DMPC algorithm adapted from original ODD-DMPC LocalController.
"""

from __future__ import annotations

from typing import Dict, List, Optional

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
from .console_reporter import PumpFlowDmpcConsoleReporter
from .resolver import PumpFlowDmpcInputResolver
from .solver import PumpFlowDmpcSolver
from .types import PumpFlowDmpcArguments


class PumpStationFlowDmpcAlgorithm:
    """Full lower-controller logic: mode dispatch, unit combo optimization, horizon planning."""

    algorithm_type = "pump_station_flow_dmpc"
    algorithm_version = "1.7.0"

    def __init__(
        self,
        solver: PumpFlowDmpcSolver,
        resolver: PumpFlowDmpcInputResolver,
        console_reporter: Optional[PumpFlowDmpcConsoleReporter] = None,
    ) -> None:
        self._solver = solver
        self._resolver = resolver
        self._console_reporter = console_reporter or PumpFlowDmpcConsoleReporter()

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        if input_data.control_task_type != ControlTaskType.STATION_FLOW_ALLOCATION:
            output = self._failed(
                input_data,
                "UNSUPPORTED_CONTROL_TASK",
                "pump_station_flow_dmpc only supports STATION_FLOW_ALLOCATION",
            )
            self._console_reporter.report_failure(input_data, output)
            return output
        try:
            arguments = self._resolver.resolve(input_data)
            action = self._solver.solve(arguments)
            output = self._project(input_data, arguments, action)
            self._console_reporter.report_success(
                input_data=input_data,
                arguments=arguments,
                action=action,
                output=output,
            )
            return output
        except PumpFlowDmpcError as exc:
            output = self._failed(input_data, exc.error_code, str(exc))
            self._console_reporter.report_failure(input_data, output)
            return output

    def _project(
        self,
        input_data: ControlAlgorithmInput,
        arguments: PumpFlowDmpcArguments,
        action,  # ControlAction from the service-private odd_dmpc package
    ) -> ControlAlgorithmOutput:
        station_id = arguments.station_id

        # Build results
        results: List[ControlSignal] = [
            ControlSignal(
                type=SignalType.RESULT,
                object_type="PumpStation",
                object_id=station_id,
                value_type="water_flow",
                value=float(action.selected_flow),
            ),
            ControlSignal(
                type=SignalType.RESULT,
                object_type="PumpStation",
                object_id=station_id,
                value_type="predicted_flow_error",
                value=float(getattr(action, "predicted_flow_error", 0.0)),
            ),
            ControlSignal(
                type=SignalType.RESULT,
                object_type="PumpStation",
                object_id=station_id,
                value_type="fit_score",
                value=float(getattr(action, "fit_score", 0.0)),
            ),
            ControlSignal(
                type=SignalType.RESULT,
                object_type="PumpStation",
                object_id=station_id,
                value_type="objective",
                value=float(getattr(action, "objective", 0.0)),
            ),
        ]

        # Project start/stop through the edge actuator availability contract.
        actuator_targets: List[ControlActuatorTarget] = []
        for unit_id in sorted(action.unit_status):
            is_running = int(action.unit_status[unit_id]) == 1
            target_values: Dict[str, float] = {}
            if is_running:
                target_values["blade_angle"] = float(action.unit_openings.get(unit_id, 0.0))
            actuator_targets.append(
                ControlActuatorTarget(
                    object_type="Pump",
                    object_id=unit_id,
                    available=is_running,
                    target_values=target_values,
                )
            )

        # Build next_state
        next_state: dict = {
            "mode": action.mode,
            "selected_flow": float(action.selected_flow),
            "unit_status": {str(k): int(v) for k, v in action.unit_status.items()},
            "unit_openings": {str(k): float(v) for k, v in action.unit_openings.items()},
        }

        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.CONTINUE,
            reason="FLOW_TRACKING_ACTION",
            actuator_targets=actuator_targets,
            results=results,
            next_state=next_state,
            evidence={
                "station_id": station_id,
                "mode": action.mode,
                "target_flow": float(arguments.reference_flow[0]) if arguments.reference_flow else 0.0,
                "selected_flow": float(action.selected_flow),
                "fit_score": float(getattr(action, "fit_score", 0.0)),
                "objective": float(getattr(action, "objective", 0.0)),
                "candidate_plan_count": len(getattr(action, "candidate_plans", [])),
            },
        )

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
