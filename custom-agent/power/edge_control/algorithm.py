from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .models import (
    ControlActuator,
    ControlActuatorTarget,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    SignalType,
)

STATION_OBJECT_TYPE = "Station"
TURBINE_OBJECT_TYPE = "Turbine"
GATE_OBJECT_TYPE = "Gate"
OUTPUT_POWER_VALUE_TYPE = "output_power"
WATER_FLOW_VALUE_TYPE = "water_flow"
GATE_OPENING_VALUE_TYPE = "gate_opening"


@dataclass(frozen=True)
class PowerControlConfig:
    algorithm_type: str = "power_station_edge_control"
    algorithm_version: str = "1.0.0"
    default_output_power_delta: float = 20.0
    default_gate_opening_delta: float = 0.2


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

        target_signal = self._select_station_target_signal(input_data)
        if target_signal is None:
            return self._failed(
                input_data,
                error_code="MISSING_TARGET_SIGNAL",
                error_message="Missing Station target signal for output_power or water_flow.",
            )

        station_id = target_signal.object_id
        turbines = self._select_station_actuators(
            input_data.actuators,
            station_id=station_id,
            object_type=TURBINE_OBJECT_TYPE,
        )
        gates = self._select_station_actuators(
            input_data.actuators,
            station_id=station_id,
            object_type=GATE_OBJECT_TYPE,
        )

        if target_signal.value_type == OUTPUT_POWER_VALUE_TYPE and turbines:
            return self._solve_turbine_output_power(input_data, target_signal, turbines)
        if target_signal.value_type == WATER_FLOW_VALUE_TYPE and gates:
            return self._solve_gate_opening(input_data, target_signal, gates)

        return self._failed(
            input_data,
            error_code="NO_SUPPORTED_ACTUATORS",
            error_message=(
                f"No supported actuators found for station={station_id}, "
                f"target_value_type={target_signal.value_type}."
            ),
        )

    def _solve_turbine_output_power(
        self,
        input_data: ControlAlgorithmInput,
        target_signal: ControlSignal,
        turbines: List[ControlActuator],
    ) -> ControlAlgorithmOutput:
        target_power = float(target_signal.value or 0.0)
        current_total_power = sum(float(actuator.values.get(OUTPUT_POWER_VALUE_TYPE, 0.0)) for actuator in turbines)
        target_map = self._allocate_target_values(
            actuators=turbines,
            value_type=OUTPUT_POWER_VALUE_TYPE,
            target_total=target_power,
            default_delta=float(input_data.parameters.get("default_output_power_delta", self._config.default_output_power_delta)),
        )
        results = [
            ControlSignal(
                type=SignalType.RESULT,
                object_type=STATION_OBJECT_TYPE,
                object_id=target_signal.object_id,
                value_type=OUTPUT_POWER_VALUE_TYPE,
                value=sum(target_map.values()),
            )
        ]
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.CONTINUE,
            reason="POWER_TARGET_ALLOCATED",
            actuator_targets=[
                ControlActuatorTarget(
                    object_type=TURBINE_OBJECT_TYPE,
                    object_id=actuator.object_id,
                    target_values={OUTPUT_POWER_VALUE_TYPE: target_map[actuator.object_id]},
                )
                for actuator in turbines
            ],
            results=results,
            next_state={
                "last_station_target_type": target_signal.value_type,
                "last_station_target_value": target_power,
                "last_station_output_power": sum(target_map.values()),
            },
            evidence={
                "station_id": target_signal.object_id,
                "target_output_power": target_power,
                "current_output_power": current_total_power,
                "available_turbine_count": len(turbines),
            },
        )

    def _solve_gate_opening(
        self,
        input_data: ControlAlgorithmInput,
        target_signal: ControlSignal,
        gates: List[ControlActuator],
    ) -> ControlAlgorithmOutput:
        target_flow = float(target_signal.value or 0.0)
        target_map = self._allocate_target_values(
            actuators=gates,
            value_type=GATE_OPENING_VALUE_TYPE,
            target_total=target_flow,
            default_delta=float(input_data.parameters.get("default_gate_opening_delta", self._config.default_gate_opening_delta)),
        )
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.CONTINUE,
            reason="GATE_TARGET_ALLOCATED",
            actuator_targets=[
                ControlActuatorTarget(
                    object_type=GATE_OBJECT_TYPE,
                    object_id=actuator.object_id,
                    target_values={GATE_OPENING_VALUE_TYPE: target_map[actuator.object_id]},
                )
                for actuator in gates
            ],
            results=[
                ControlSignal(
                    type=SignalType.RESULT,
                    object_type=STATION_OBJECT_TYPE,
                    object_id=target_signal.object_id,
                    value_type=WATER_FLOW_VALUE_TYPE,
                    value=target_flow,
                )
            ],
            next_state={
                "last_station_target_type": target_signal.value_type,
                "last_station_target_value": target_flow,
            },
            evidence={
                "station_id": target_signal.object_id,
                "target_water_flow": target_flow,
                "available_gate_count": len(gates),
            },
        )

    def _select_station_target_signal(self, input_data: ControlAlgorithmInput) -> Optional[ControlSignal]:
        station_id = input_data.context.target_object_id
        station_type = input_data.context.target_object_type or STATION_OBJECT_TYPE
        candidates = [
            signal
            for signal in input_data.signals
            if signal.type == SignalType.TARGET
            and signal.object_type == station_type
            and (station_id is None or signal.object_id == station_id)
            and signal.value is not None
            and signal.value_type in {OUTPUT_POWER_VALUE_TYPE, WATER_FLOW_VALUE_TYPE}
        ]
        if not candidates:
            return None
        return candidates[0]

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
