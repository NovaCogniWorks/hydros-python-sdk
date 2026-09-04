from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from allocation import (
    HydroSimV47PowerAllocator,
    StationPowerAllocationInput,
    TurbinePowerInput,
)
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
OUTPUT_POWER_VALUE_TYPE = "output_power"

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class PowerOutputPowerAllocationConfig:
    algorithm_type: str = "power_station_output_power_allocation"
    algorithm_version: str = "1.0.0"
    default_efficiency: float = 0.9
    default_output_power_delta: float = 1.0e9


class PowerStationOutputPowerAllocationAlgorithm:
    def __init__(self, config: Optional[PowerOutputPowerAllocationConfig] = None) -> None:
        self._config = config or PowerOutputPowerAllocationConfig()
        self.algorithm_type = self._config.algorithm_type
        self.algorithm_version = self._config.algorithm_version
        self._allocator = HydroSimV47PowerAllocator()

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        if input_data.control_task_type != ControlTaskType.STATION_POWER_ALLOCATION:
            return PowerControlAlgorithm._failed(
                input_data,
                error_code="UNSUPPORTED_CONTROL_TASK",
                error_message="Power output allocation only supports STATION_POWER_ALLOCATION.",
            )

        target_signals = self._select_station_power_targets(input_data)
        if not target_signals:
            return PowerControlAlgorithm._failed(
                input_data,
                error_code="MISSING_TARGET_SIGNAL",
                error_message="Missing PowerStation target signal for output_power.",
            )

        actuator_targets: List[ControlActuatorTarget] = []
        results: List[ControlSignal] = []
        station_states: Dict[str, Any] = {}
        station_evidence: List[Dict[str, Any]] = []
        for target_signal in target_signals:
            station_id = target_signal.object_id
            turbines = self._select_station_actuators(input_data.actuators, station_id=station_id)
            if not turbines:
                return PowerControlAlgorithm._failed(
                    input_data,
                    error_code="NO_SUPPORTED_ACTUATORS",
                    error_message=f"No turbine output-power actuators found for station={station_id}.",
                )

            target_power = max(float(target_signal.value or 0.0), 0.0)
            default_efficiency = float(
                input_data.parameters.get(
                    "default_efficiency",
                    input_data.parameters.get("efficiency", self._config.default_efficiency),
                )
            )
            allocation_result = self._allocator.allocate_station(
                StationPowerAllocationInput(
                    station_id=int(station_id),
                    target_output_power=target_power,
                    turbines=[self._to_turbine_power_input(actuator, input_data.parameters) for actuator in turbines],
                    max_output_power_delta=float(
                        input_data.parameters.get(
                            "max_output_power_delta",
                            input_data.parameters.get(
                                "max_adjustment_delta",
                                self._config.default_output_power_delta,
                            ),
                        )
                    ),
                    default_efficiency=default_efficiency,
                    stage_hints=self._stage_hints(input_data),
                    context_id=input_data.context.context_id,
                    compute_step=input_data.context.compute_step,
                    station_name=str(target_signal.attributes.get("object_name") or target_signal.attributes.get("name") or ""),
                )
            )
            allocation_by_turbine = {
                allocation.object_id: allocation
                for allocation in allocation_result.turbine_allocations
            }

            actuator_targets.extend(
                ControlActuatorTarget(
                    object_type=TURBINE_OBJECT_TYPE,
                    object_id=actuator.object_id,
                    target_values={
                        OUTPUT_POWER_VALUE_TYPE: allocation_by_turbine[actuator.object_id].target_output_power,
                    },
                )
                for actuator in turbines
            )
            results.extend(
                [
                    ControlSignal(
                        type=SignalType.RESULT,
                        object_type=target_signal.object_type,
                        object_id=target_signal.object_id,
                        value_type=OUTPUT_POWER_VALUE_TYPE,
                        value=allocation_result.allocated_output_power,
                    ),
                    ControlSignal(
                        type=SignalType.RESULT,
                        object_type=target_signal.object_type,
                        object_id=target_signal.object_id,
                        value_type=WATER_FLOW_VALUE_TYPE,
                        value=allocation_result.estimated_water_flow,
                    ),
                ]
            )
            station_states[str(station_id)] = {
                "target_output_power": target_power,
                "allocated_turbine_output_power": allocation_result.allocated_output_power,
                "estimated_turbine_water_flow": allocation_result.estimated_water_flow,
            }
            evidence = self._build_station_evidence(allocation_result)
            station_evidence.append(evidence)
            allocation_evidence = evidence["allocation"]
            logger.info(
                "Power V47 output allocation evidence: request_id=%s, station_id=%s, "
                "target_output_power=%.6f, allocated_output_power=%.6f, "
                "estimated_turbine_water_flow=%.6f, mode=%s, total_current_output_power=%s, "
                "max_output_power_delta=%s, default_efficiency=%s, feedback_used=%s, "
                "stage_hint_count=%s, allocator_source=%s, core_session_id=%s, "
                "session_created=%s, state_memory_used=%s, commitment_before=%s, "
                "commitment_after=%s, hold_remaining=%s, target_exceeds_known_capacity=%s, "
                "clipped_count=%s, turbines=%s",
                input_data.context.request_id,
                station_id,
                target_power,
                allocation_result.allocated_output_power,
                allocation_result.estimated_water_flow,
                allocation_evidence.get("mode"),
                self._format_optional_float(allocation_evidence.get("total_current_output_power")),
                self._format_optional_float(allocation_evidence.get("max_output_power_delta")),
                self._format_optional_float(default_efficiency),
                evidence["feedback_used"],
                evidence["stage_hint_count"],
                allocation_evidence.get("allocator_source"),
                allocation_evidence.get("core_session_id"),
                allocation_evidence.get("session_created"),
                allocation_evidence.get("state_memory_used"),
                allocation_evidence.get("commitment_signature_before"),
                allocation_evidence.get("commitment_signature_after"),
                allocation_evidence.get("hold_remaining"),
                allocation_evidence.get("target_exceeds_known_capacity"),
                len(allocation_evidence.get("clipped", []) or []),
                self._format_turbine_allocation_targets(allocation_evidence),
            )

        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.CONTINUE,
            reason="TURBINE_POWER_TARGET_ALLOCATED",
            actuator_targets=actuator_targets,
            results=results,
            next_state={"stations": station_states},
            evidence={
                "algorithm": "HydroSim.V47 original imported output power allocation",
                "stations": station_evidence,
            },
        )

    def _to_turbine_power_input(
        self,
        actuator: ControlActuator,
        parameters: Dict[str, Any],
    ) -> TurbinePowerInput:
        range_config = actuator.ranges.get(OUTPUT_POWER_VALUE_TYPE)
        return TurbinePowerInput(
            object_id=int(actuator.object_id),
            current_output_power=float(actuator.values.get(OUTPUT_POWER_VALUE_TYPE, 0.0)),
            min_output_power=(
                float(range_config.min_value)
                if range_config and range_config.min_value is not None
                else 0.0
            ),
            max_output_power=(
                float(range_config.max_value)
                if range_config and range_config.max_value is not None
                else None
            ),
            state=self._optional_int(
                self._first_present(
                    actuator.attributes,
                    parameters,
                    "State",
                    "state",
                    "current_state",
                    "currentState",
                )
            ),
            min_power=self._optional_float(
                self._first_present(
                    actuator.attributes,
                    parameters,
                    "min_power",
                    "min_power_mw",
                )
            ),
            max_power=self._optional_float(
                self._first_present(
                    actuator.attributes,
                    parameters,
                    "max_power",
                    "max_power_mw",
                )
            ),
            head=self._optional_float(actuator.attributes.get("head", parameters.get("head"))),
            efficiency=self._optional_float(actuator.attributes.get("efficiency", parameters.get("efficiency"))),
            water_flow_per_mw=self._optional_float(
                actuator.attributes.get("water_flow_per_mw", parameters.get("water_flow_per_mw"))
            ),
            design_head=self._optional_float(actuator.attributes.get("design_head", parameters.get("design_head"))),
            min_head=self._optional_float(actuator.attributes.get("min_head", parameters.get("min_head"))),
            max_head=self._optional_float(actuator.attributes.get("max_head", parameters.get("max_head"))),
            design_power=self._optional_float(
                actuator.attributes.get("design_power", parameters.get("design_power"))
            ),
            design_efficiency=self._optional_float(
                actuator.attributes.get("design_efficiency", parameters.get("design_efficiency"))
            ),
            eta_head_coeff=self._optional_float(
                actuator.attributes.get("eta_head_coeff", parameters.get("eta_head_coeff"))
            ),
            eta_power_coeff=self._optional_float(
                actuator.attributes.get("eta_power_coeff", parameters.get("eta_power_coeff"))
            ),
            power_ramp_rate=self._optional_float(
                self._first_present(
                    actuator.attributes,
                    parameters,
                    "power_ramp_rate",
                    "power_ramp_rate_mw",
                )
            ),
            attributes=dict(actuator.attributes),
        )

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    @staticmethod
    def _first_present(primary: Dict[str, Any], secondary: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if primary.get(key) is not None:
                return primary.get(key)
            if secondary.get(key) is not None:
                return secondary.get(key)
        return None

    @staticmethod
    def _build_station_evidence(allocation_result) -> Dict[str, Any]:
        return {
            "station_id": allocation_result.station_id,
            "target_output_power": allocation_result.target_output_power,
            "allocated_turbine_output_power": allocation_result.allocated_output_power,
            "estimated_turbine_water_flow": allocation_result.estimated_water_flow,
            "available_turbine_count": len(allocation_result.turbine_allocations),
            "turbine_allocations": [
                {
                    "object_id": allocation.object_id,
                    "target_output_power": allocation.target_output_power,
                    "estimated_water_flow": allocation.estimated_water_flow,
                    "current_output_power": allocation.current_output_power,
                }
                for allocation in allocation_result.turbine_allocations
            ],
            "allocation": allocation_result.evidence["allocation"],
            "feedback_used": allocation_result.evidence["feedback_used"],
            "stage_hint_count": allocation_result.evidence["stage_hint_count"],
        }

    @staticmethod
    def _format_optional_float(value: Any) -> str:
        if value is None:
            return "null"
        return f"{float(value):.6f}"

    @classmethod
    def _format_turbine_allocation_targets(cls, allocation_evidence: Dict[str, Any]) -> str:
        targets = allocation_evidence.get("turbine_targets", []) or []
        if not targets:
            return "[]"
        return "[" + ",".join(
            (
                f"{item.get('object_id')}:current={cls._format_optional_float(item.get('current_output_power'))}"
                f",raw={cls._format_optional_float(item.get('raw_target_output_power'))}"
                f",projected={cls._format_optional_float(item.get('projected_target_output_power'))}"
                f",state={item.get('state')}"
                f",selected={item.get('selected')}"
                f",min={cls._format_optional_float(item.get('min_output_power'))}"
                f",max={cls._format_optional_float(item.get('max_output_power'))}"
                f",v47_min={cls._format_optional_float(item.get('min_power'))}"
                f",v47_max={cls._format_optional_float(item.get('max_power'))}"
                f",lower={cls._format_optional_float(item.get('lower_bound'))}"
                f",upper={cls._format_optional_float(item.get('upper_bound'))}"
            )
            for item in targets
        ) + "]"

    def _stage_hints(self, input_data: ControlAlgorithmInput) -> List[Dict[str, Any]]:
        hints = []
        configured_hints = input_data.parameters.get("stage_hints", [])
        if isinstance(configured_hints, list):
            hints.extend(item for item in configured_hints if isinstance(item, dict))
        for signal in input_data.signals:
            if signal.type != SignalType.OBSERVATION or signal.value is None:
                continue
            hints.append(
                {
                    "object_type": signal.object_type,
                    "object_id": signal.object_id,
                    "metrics_code": signal.value_type,
                    "value": float(signal.value),
                    "attributes": dict(signal.attributes or {}),
                }
            )
        return hints

    def _select_station_power_targets(self, input_data: ControlAlgorithmInput) -> List[ControlSignal]:
        return [
            signal
            for signal in input_data.signals
            if signal.type == SignalType.TARGET
            and signal.object_type == STATION_OBJECT_TYPE
            and signal.value is not None
            and signal.value_type == OUTPUT_POWER_VALUE_TYPE
        ]

    def _select_station_actuators(
        self,
        actuators: List[ControlActuator],
        *,
        station_id: int,
    ) -> List[ControlActuator]:
        selected = []
        for actuator in actuators:
            if not actuator.available or actuator.object_type != TURBINE_OBJECT_TYPE:
                continue
            actuator_station_id = actuator.attributes.get("station_object_id", actuator.attributes.get("node_id"))
            if actuator_station_id is not None and int(actuator_station_id) != int(station_id):
                continue
            if OUTPUT_POWER_VALUE_TYPE not in actuator.values and OUTPUT_POWER_VALUE_TYPE not in actuator.ranges:
                continue
            selected.append(actuator)
        return selected
