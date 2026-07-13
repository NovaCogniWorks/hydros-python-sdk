"""将 Hydros 标准控制输入解析为泵站流量 DMPC 的领域输入。"""

from __future__ import annotations

import math
from typing import Iterable

from hydros_agent_sdk.control_algorithms import (
    ControlAlgorithmInput,
    SignalType,
)

from .errors import PumpFlowDmpcError
from .types import PumpFlowDmpcArguments, PumpUnitState


class PumpFlowDmpcInputResolver:
    """只依赖标准 DTO 解析一次泵站流量分配求解的输入事实。"""

    def resolve(self, input_data: ControlAlgorithmInput) -> PumpFlowDmpcArguments:
        station_id = self._target_station_id(input_data)
        units = tuple(self._available_units(input_data, station_id))
        if not units:
            raise PumpFlowDmpcError(
                "NO_AVAILABLE_PUMP_UNIT",
                "no available running pump unit belongs to station %s" % station_id,
            )
        return PumpFlowDmpcArguments(
            station_id=station_id,
            target_flow=self._required_signal(
                input_data, SignalType.TARGET, station_id, "water_flow"
            ),
            current_flow=self._required_signal(
                input_data, SignalType.OBSERVATION, station_id, "water_flow"
            ),
            water_head=self._required_signal(
                input_data, SignalType.OBSERVATION, station_id, "water_head"
            ),
            units=units,
            flow_tolerance=self._positive_float(
                input_data.parameters.get("flow_tolerance", 1.0),
                "flow_tolerance",
            ),
            max_blade_delta_per_step=self._positive_float(
                input_data.parameters.get("max_blade_delta_per_step", 2.0),
                "max_blade_delta_per_step",
            ),
            candidate_angle_step=self._positive_float(
                input_data.parameters.get("candidate_angle_step", 0.5),
                "candidate_angle_step",
            ),
            max_solver_iterations=self._positive_integer(
                input_data.parameters.get("max_solver_iterations", 8),
                "max_solver_iterations",
            ),
            movement_weight=self._non_negative_float(
                input_data.parameters.get("movement_weight", 0.1),
                "movement_weight",
            ),
        )

    @staticmethod
    def _target_station_id(input_data: ControlAlgorithmInput) -> int:
        if input_data.context.target_object_type != "PumpStation":
            raise PumpFlowDmpcError(
                "UNSUPPORTED_TARGET_OBJECT",
                "pump flow DMPC requires target_object_type PumpStation",
            )
        station_id = input_data.context.target_object_id
        if station_id is None or station_id <= 0:
            raise PumpFlowDmpcError(
                "TARGET_STATION_REQUIRED",
                "pump flow DMPC requires a positive target station id",
            )
        return station_id

    def _available_units(
        self,
        input_data: ControlAlgorithmInput,
        station_id: int,
    ) -> Iterable[PumpUnitState]:
        for actuator in input_data.actuators:
            if actuator.object_type != "Pump" or not actuator.available:
                continue
            if actuator.attributes.get("station_object_id") != station_id:
                continue
            if not self._is_running(actuator.values.get("unit_status", 1.0)):
                continue
            current_angle = actuator.values.get("blade_angle")
            angle_range = actuator.ranges.get("blade_angle")
            if current_angle is None or angle_range is None:
                raise PumpFlowDmpcError(
                    "MISSING_BLADE_ANGLE",
                    "pump unit %s requires blade_angle and its range" % actuator.object_id,
                )
            if angle_range.min_value is None or angle_range.max_value is None:
                raise PumpFlowDmpcError(
                    "MISSING_BLADE_ANGLE_RANGE",
                    "pump unit %s requires blade_angle min/max values" % actuator.object_id,
                )
            current = self._finite_float(current_angle, "blade_angle")
            minimum = self._finite_float(angle_range.min_value, "blade_angle min_value")
            maximum = self._finite_float(angle_range.max_value, "blade_angle max_value")
            if minimum > maximum:
                raise PumpFlowDmpcError(
                    "INVALID_BLADE_ANGLE_RANGE",
                    "pump unit %s blade_angle min_value exceeds max_value" % actuator.object_id,
                )
            yield PumpUnitState(
                unit_id=actuator.object_id,
                current_blade_angle=current,
                min_blade_angle=minimum,
                max_blade_angle=maximum,
            )

    def _required_signal(
        self,
        input_data: ControlAlgorithmInput,
        signal_type: SignalType,
        station_id: int,
        value_type: str,
    ) -> float:
        matches = [
            signal
            for signal in input_data.signals
            if signal.type == signal_type
            and signal.object_type == "PumpStation"
            and signal.object_id == station_id
            and signal.value_type == value_type
            and signal.value is not None
        ]
        if len(matches) != 1:
            raise PumpFlowDmpcError(
                "MISSING_OR_AMBIGUOUS_SIGNAL",
                "expected one %s PumpStation/%s signal for station %s"
                % (signal_type.value, value_type, station_id),
            )
        return self._finite_float(matches[0].value, value_type)

    @staticmethod
    def _is_running(value: object) -> bool:
        try:
            return float(value) == 1.0
        except (TypeError, ValueError):
            raise PumpFlowDmpcError(
                "INVALID_UNIT_STATUS",
                "unit_status must be numeric",
            )

    @staticmethod
    def _finite_float(value: object, label: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_INPUT",
                "%s must be numeric" % label,
            ) from exc
        if not math.isfinite(parsed):
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_INPUT",
                "%s must be finite" % label,
            )
        return parsed

    def _positive_float(self, value: object, label: str) -> float:
        parsed = self._finite_float(value, label)
        if parsed <= 0.0:
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_PARAMETER",
                "%s must be positive" % label,
            )
        return parsed

    def _non_negative_float(self, value: object, label: str) -> float:
        parsed = self._finite_float(value, label)
        if parsed < 0.0:
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_PARAMETER",
                "%s must not be negative" % label,
            )
        return parsed

    @staticmethod
    def _positive_integer(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_PARAMETER",
                "%s must be an integer" % label,
            ) from exc
        if parsed <= 0:
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_PARAMETER",
                "%s must be positive" % label,
            )
        return parsed
