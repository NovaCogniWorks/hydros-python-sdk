"""
Resolve Hydros standard ControlAlgorithmInput into PumpFlowDmpcArguments.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Tuple

from hydros_agent_sdk.control_algorithms import (
    ControlAlgorithmInput,
    SignalType,
)

from .errors import PumpFlowDmpcError
from .types import PumpFlowDmpcArguments


class PumpFlowDmpcInputResolver:
    """Extract full lower-controller domain input from ControlAlgorithmInput signals."""

    def resolve(self, input_data: ControlAlgorithmInput) -> PumpFlowDmpcArguments:
        station_id = self._target_station_id(input_data)
        algorithm_params = self._algorithm_params(input_data)
        lower_controller_params = self._lower_controller_params(algorithm_params)

        # ---- signal lookups ----
        sig_by_type: Dict[str, dict] = {}
        for sig in input_data.signals:
            key = (sig.type.value if hasattr(sig.type, "value") else sig.type,
                   sig.object_type, sig.object_id, sig.value_type)
            sig_by_type.setdefault(key, []).append(sig)

        def _get_signal(stype: str, otype: str, oid: int, vtype: str):
            key = (stype, otype, oid, vtype)
            items = sig_by_type.get(key, [])
            if len(items) != 1:
                return None
            return items[0]

        def _get_value(stype: str, otype: str, oid: int, vtype: str):
            sig = _get_signal(stype, otype, oid, vtype)
            return sig.value if sig is not None else None

        def _get_attr(stype: str, otype: str, oid: int, vtype: str) -> dict:
            sig = _get_signal(stype, otype, oid, vtype)
            return dict(sig.attributes) if sig is not None and sig.attributes else {}

        def _get_series(stype: str, otype: str, oid: int, vtype: str) -> List[float]:
            sig = _get_signal(stype, otype, oid, vtype)
            return list(sig.series) if sig is not None else []

        # ---- station memory ----
        st_mem_attr = _get_attr("OBSERVATION", "PumpStation", station_id, "station_memory")
        mode = str(st_mem_attr.get("mode", "ODD2"))
        last_selected_flow = float(st_mem_attr.get("last_selected_flow", 0.0))
        # station_memory is algorithm history. Current actuator facts from edge
        # remain authoritative for availability, running state and blade angle.
        active_unit_ids: List[int] = []

        # ---- available units: include every station actuator supplied by edge ----
        lo = station_id + 1
        hi = station_id + 99
        station_actuators = [
            actuator
            for actuator in input_data.actuators
            if actuator.object_type == "Pump"
            and (
                int(actuator.attributes.get("station_object_id", station_id)) == station_id
                if actuator.attributes.get("station_object_id") is not None
                else lo <= actuator.object_id <= hi
            )
        ]
        station_unit_ids = sorted({actuator.object_id for actuator in station_actuators})

        available_unit_ids: List[int] = []
        unit_openings: Dict[int, float] = {}
        unit_status: Dict[int, int] = {}
        unit_blade_bounds: Dict[int, Tuple[float, float]] = {}
        time_since_adjust: Dict[int, int] = {}
        time_since_switch: Dict[int, int] = {}

        actuator_by_id = {actuator.object_id: actuator for actuator in station_actuators}
        for uid in station_unit_ids:
            actuator = actuator_by_id.get(uid)
            if actuator is None or not actuator.available:
                continue
            blade = actuator.values.get("blade_angle")
            blade_range = actuator.ranges.get("blade_angle") if actuator.ranges else None
            if blade is None or blade_range is None:
                continue
            blade_val = float(blade)
            min_val = float(blade_range.min_value) if blade_range.min_value is not None else -7.0
            max_val = float(blade_range.max_value) if blade_range.max_value is not None else 5.0
            if (
                not math.isfinite(min_val)
                or not math.isfinite(max_val)
                or min_val > max_val
            ):
                raise PumpFlowDmpcError(
                    "INVALID_ACTUATOR_BLADE_RANGE",
                    "invalid blade_angle range [%s, %s] for pump %s"
                    % (min_val, max_val, uid),
                )
            # blade_angle=100 means stopped
            running = min_val <= blade_val <= max_val
            available_unit_ids.append(uid)
            unit_blade_bounds[uid] = (min_val, max_val)
            unit_openings[uid] = blade_val if running else 0.0
            unit_status[uid] = 1 if running else 0
            if running:
                active_unit_ids.append(uid)

        # ---- per-unit history from unit_memory signals ----
        # Never let stale algorithm memory overwrite edge actuator facts.
        for uid in list(station_unit_ids):
            um = _get_attr("OBSERVATION", "Pump", uid, "unit_memory")
            if not um:
                um = _get_attr("OBSERVATION", "PUMP", uid, "unit_memory")
            if um:
                time_since_adjust[uid] = int(um.get("time_since_adjust", 999))
                time_since_switch[uid] = int(um.get("time_since_switch", 999))

        # ---- transfer bundle from REFERENCE series ----
        reference_front_level = _get_series("REFERENCE", "PumpStation", station_id, "station_front_water_level")
        reference_back_level = _get_series("REFERENCE", "PumpStation", station_id, "station_back_water_level")
        if not reference_front_level or not reference_back_level:
            raise PumpFlowDmpcError(
                "MISSING_REFERENCE_WATER_LEVEL",
                "upper-model front/back water-level references are required for station %s" % station_id,
            )
        if len(reference_front_level) != len(reference_back_level):
            raise PumpFlowDmpcError(
                "INVALID_REFERENCE_WATER_LEVEL_HORIZON",
                "front/back water-level reference lengths differ for station %s" % station_id,
            )
        if not all(
            math.isfinite(float(value))
            for value in reference_front_level + reference_back_level
        ):
            raise PumpFlowDmpcError(
                "INVALID_REFERENCE_WATER_LEVEL",
                "upper-model water-level references must be finite for station %s" % station_id,
            )
        reference_head = [
            float(back) - float(front)
            for front, back in zip(reference_front_level, reference_back_level)
        ]

        # target_flow from TARGET signal
        target_flow = _get_value("TARGET", "PumpStation", station_id, "water_flow")
        if target_flow is None:
            raise PumpFlowDmpcError("MISSING_TARGET_FLOW", "no TARGET water_flow for station %s" % station_id)
        reference_flow = [float(target_flow)] + [float(target_flow)] * (len(reference_front_level) - 1) if reference_front_level else [float(target_flow)]

        # ---- current observation ----
        current_front_level_val = _get_value("OBSERVATION", "PumpStation", station_id, "water_level")
        current_front_level = float(current_front_level_val) if current_front_level_val is not None else (reference_front_level[0] if reference_front_level else 0.0)

        # back level: from REFERENCE series[0]
        current_back_level = reference_back_level[0] if reference_back_level else 0.0

        # Lower control uses the upper model's first-step head directly.
        current_head = reference_head[0]

        current_flow_val = _get_value("OBSERVATION", "PumpStation", station_id, "water_flow")
        current_flow = float(current_flow_val) if current_flow_val is not None else last_selected_flow

        raw_max_delta = self._parameter_value(
            input_data.parameters,
            algorithm_params,
            lower_controller_params,
            "max_blade_delta_per_step",
            input_data.parameters.get("max_adjustment_delta", 2.0),
        )
        try:
            max_blade_delta_per_step = float(raw_max_delta)
        except (TypeError, ValueError) as exc:
            raise PumpFlowDmpcError(
                "INVALID_MAX_BLADE_DELTA_PER_STEP",
                "max_blade_delta_per_step must be a positive finite number",
            ) from exc
        if not math.isfinite(max_blade_delta_per_step) or max_blade_delta_per_step <= 0.0:
            raise PumpFlowDmpcError(
                "INVALID_MAX_BLADE_DELTA_PER_STEP",
                "max_blade_delta_per_step must be a positive finite number",
            )

        config_path_attr = _get_attr("OBSERVATION", "PumpStation", station_id, "config_path")
        config_path = config_path_attr.get("path", "") if config_path_attr else ""

        if not available_unit_ids:
            raise PumpFlowDmpcError(
                "NO_AVAILABLE_PUMP_UNIT",
                "no available pump actuator for station %s" % station_id,
            )

        return PumpFlowDmpcArguments(
            station_id=station_id,
            mode=mode,
            config_path=config_path,
            active_unit_ids=active_unit_ids,
            unit_openings=unit_openings,
            unit_status=unit_status,
            time_since_adjust=time_since_adjust,
            time_since_switch=time_since_switch,
            last_selected_flow=last_selected_flow,
            reference_flow=reference_flow,
            reference_front_level=reference_front_level,
            reference_back_level=reference_back_level,
            reference_head=reference_head,
            available_unit_ids=available_unit_ids,
            unit_blade_bounds=unit_blade_bounds,
            current_front_level=current_front_level,
            current_back_level=current_back_level,
            current_head=current_head,
            current_flow=current_flow,
            max_blade_delta_per_step=max_blade_delta_per_step,
            algorithm_params=algorithm_params,
        )

    @staticmethod
    def _algorithm_params(input_data: ControlAlgorithmInput) -> Dict[str, Any]:
        raw = input_data.parameters.get("algorithm_params", {})
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_PARAMS",
                "parameters.algorithm_params must be a mapping",
            )
        return dict(raw)

    @staticmethod
    def _lower_controller_params(algorithm_params: Mapping[str, Any]) -> Dict[str, Any]:
        raw_lower = algorithm_params.get("lower_controller", {})
        raw_odd = algorithm_params.get("odd", {})
        if not raw_lower and isinstance(raw_odd, Mapping):
            raw_lower = raw_odd.get("lower_controller", {})
        if raw_lower is None:
            return {}
        if not isinstance(raw_lower, Mapping):
            raise PumpFlowDmpcError(
                "INVALID_ALGORITHM_PARAMS",
                "parameters.algorithm_params.lower_controller must be a mapping",
            )
        return dict(raw_lower)

    @staticmethod
    def _parameter_value(
        flat_parameters: Mapping[str, Any],
        algorithm_params: Mapping[str, Any],
        lower_controller_params: Mapping[str, Any],
        key: str,
        default: Any,
    ) -> Any:
        if key in lower_controller_params:
            return lower_controller_params[key]
        if key in algorithm_params:
            return algorithm_params[key]
        return flat_parameters.get(key, default)

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
