from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from hydros_agent_sdk.control_algorithms import (
    ControlActuator,
    ControlActuatorTarget,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    SignalType,
)

STATION_OBJECT_TYPE = "PowerStation"
TURBINE_OBJECT_TYPE = "Turbine"
WATER_FLOW_VALUE_TYPE = "water_flow"


@dataclass(frozen=True)
class PowerControlConfig:
    algorithm_type: str = "power_station_edge_control"
    algorithm_version: str = "1.0.0"
    default_water_flow_delta: float = 200.0


class PowerControlAlgorithm:
    def __init__(self, config: Optional[PowerControlConfig] = None) -> None:
        self._config = config or PowerControlConfig()
        self.algorithm_type = self._config.algorithm_type
        self.algorithm_version = self._config.algorithm_version

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        if input_data.control_task_type != ControlTaskType.STATION_FLOW_ALLOCATION:
            return self._failed(
                input_data,
                error_code="UNSUPPORTED_CONTROL_TASK",
                error_message="Power control only supports STATION_FLOW_ALLOCATION for the first version.",
            )

        target_signals = self._select_station_target_signals(input_data)
        if not target_signals:
            return self._failed(
                input_data,
                error_code="MISSING_TARGET_SIGNAL",
                error_message="Missing PowerStation target signal for water_flow.",
            )

        actuator_targets: List[ControlActuatorTarget] = []
        results: List[ControlSignal] = []
        station_states: Dict[str, Any] = {}
        station_evidence: List[Dict[str, Any]] = []
        for target_signal in target_signals:
            station_id = target_signal.object_id
            turbines = self._select_station_actuators(
                input_data.actuators,
                station_id=station_id,
                object_type=TURBINE_OBJECT_TYPE,
            )
            if not turbines:
                return self._failed(
                    input_data,
                    error_code="NO_SUPPORTED_ACTUATORS",
                    error_message=f"No turbine water-flow actuators found for station={station_id}.",
                )
            target_flow = float(target_signal.value or 0.0)
            current_total_flow = sum(
                float(actuator.values.get(WATER_FLOW_VALUE_TYPE, 0.0))
                for actuator in turbines
            )
            target_map = self._allocate_target_values(
                actuators=turbines,
                value_type=WATER_FLOW_VALUE_TYPE,
                target_total=target_flow,
                default_delta=float(
                    input_data.parameters.get(
                        "max_adjustment_delta",
                        input_data.parameters.get(
                            "default_water_flow_delta",
                            self._config.default_water_flow_delta,
                        ),
                    )
                ),
            )
            allocated_flow = sum(target_map.values())
            actuator_targets.extend(
                ControlActuatorTarget(
                    object_type=TURBINE_OBJECT_TYPE,
                    object_id=actuator.object_id,
                    target_values={WATER_FLOW_VALUE_TYPE: target_map[actuator.object_id]},
                )
                for actuator in turbines
            )
            results.append(
                ControlSignal(
                    type=SignalType.RESULT,
                    object_type=target_signal.object_type,
                    object_id=target_signal.object_id,
                    value_type=WATER_FLOW_VALUE_TYPE,
                    value=allocated_flow,
                )
            )
            station_states[str(station_id)] = {
                "target_water_flow": target_flow,
                "allocated_turbine_water_flow": allocated_flow,
            }
            station_evidence.append(
                {
                    "station_id": station_id,
                    "target_water_flow": target_flow,
                    "current_turbine_water_flow": current_total_flow,
                    "available_turbine_count": len(turbines),
                }
            )

        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.CONTINUE,
            reason="TURBINE_FLOW_TARGET_ALLOCATED",
            actuator_targets=actuator_targets,
            results=results,
            next_state={"stations": station_states},
            evidence={"stations": station_evidence},
        )

    def _select_station_target_signals(self, input_data: ControlAlgorithmInput) -> List[ControlSignal]:
        return [
            signal
            for signal in input_data.signals
            if signal.type == SignalType.TARGET
            and signal.object_type == STATION_OBJECT_TYPE
            and signal.value is not None
            and signal.value_type == WATER_FLOW_VALUE_TYPE
        ]

    def _select_station_actuators(
        self,
        actuators: List[ControlActuator],
        *,
        station_id: int,
        object_type: str,
    ) -> List[ControlActuator]:
        selected = []
        for actuator in actuators:
            if not actuator.available or actuator.object_type != object_type:
                continue
            actuator_station_id = actuator.attributes.get("station_object_id", actuator.attributes.get("node_id"))
            if actuator_station_id is not None and int(actuator_station_id) != int(station_id):
                continue
            selected.append(actuator)
        return selected

    def _allocate_target_values(
        self,
        *,
        actuators: List[ControlActuator],
        value_type: str,
        target_total: float,
        default_delta: float,
    ) -> Dict[int, float]:
        current_values = {
            actuator.object_id: float(actuator.values.get(value_type, 0.0))
            for actuator in actuators
        }
        total_current = sum(max(value, 0.0) for value in current_values.values())
        if total_current > 0.0:
            raw_targets = {
                actuator.object_id: target_total * (max(current_values[actuator.object_id], 0.0) / total_current)
                for actuator in actuators
            }
        else:
            even_target = target_total / max(len(actuators), 1)
            raw_targets = {actuator.object_id: even_target for actuator in actuators}

        projected: Dict[int, float] = {}
        for actuator in actuators:
            current_value = current_values[actuator.object_id]
            target_value = raw_targets[actuator.object_id]
            range_config = actuator.ranges.get(value_type)
            min_value = range_config.min_value if range_config and range_config.min_value is not None else None
            max_value = range_config.max_value if range_config and range_config.max_value is not None else None
            lower_bound = current_value - default_delta
            upper_bound = current_value + default_delta
            if min_value is not None:
                lower_bound = max(lower_bound, float(min_value))
            if max_value is not None:
                upper_bound = min(upper_bound, float(max_value))
            projected[actuator.object_id] = float(min(max(target_value, lower_bound), upper_bound))
        return projected

    @staticmethod
    def _failed(
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
