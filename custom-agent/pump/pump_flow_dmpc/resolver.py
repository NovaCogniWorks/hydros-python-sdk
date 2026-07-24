"""
Resolve Hydros standard ControlAlgorithmInput into PumpFlowDmpcArguments.
"""

from __future__ import annotations

import math
from typing import Dict, List

import pandas as pd

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
        active_unit_ids = list(st_mem_attr.get("active_unit_ids", []))

        # ---- available units: include ALL station units, let LocalController decide start/stop ----
        # Determine which unit IDs belong to this station
        station_unit_ids: List[int] = list(active_unit_ids)  # from station_memory
        if not station_unit_ids:
            # fallback: derive from unit ID pattern (station_id + 1 .. station_id + 99)
            lo = station_id + 1
            hi = station_id + 99
            station_unit_ids = [uid for uid in [a.object_id for a in input_data.actuators if a.object_type == "Pump"] if lo <= uid <= hi]

        available_unit_ids: List[int] = []
        unit_openings: Dict[int, float] = {}
        unit_status: Dict[int, int] = {}
        time_since_adjust: Dict[int, int] = {}
        time_since_switch: Dict[int, int] = {}

        actuator_by_id = {a.object_id: a for a in input_data.actuators if a.object_type == "Pump"}
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
            # blade_angle=100 means stopped
            running = min_val <= blade_val <= max_val
            available_unit_ids.append(uid)
            unit_openings[uid] = blade_val if running else 0.0
            unit_status[uid] = 1 if running else 0

        # ---- per-unit memory from unit_memory signals ----
        for uid in list(station_unit_ids):
            um = _get_attr("OBSERVATION", "Pump", uid, "unit_memory")
            if um:
                unit_status[uid] = int(um.get("unit_status", unit_status.get(uid, 1)))
                unit_openings[uid] = float(um.get("unit_opening", unit_openings.get(uid, 0.0)))
                time_since_adjust[uid] = int(um.get("time_since_adjust", 999))
                time_since_switch[uid] = int(um.get("time_since_switch", 999))

        # ---- transfer bundle from REFERENCE series ----
        reference_front_level = _get_series("REFERENCE", "PumpStation", station_id, "station_front_water_level")
        reference_back_level = _get_series("REFERENCE", "PumpStation", station_id, "station_back_water_level")
        reference_head = [f - b for f, b in zip(reference_front_level, reference_back_level)] if reference_front_level and reference_back_level else []

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

        # head = front - back (positive if front is upstream)
        current_head = abs(current_front_level - current_back_level) if current_front_level and current_back_level else 0.0

        current_flow_val = _get_value("OBSERVATION", "PumpStation", station_id, "water_flow")
        current_flow = float(current_flow_val) if current_flow_val is not None else last_selected_flow

        # ---- environment from env signals ----
        basin_levels = _get_attr("OBSERVATION", "PumpStation", station_id, "basin_levels")
        pool_areas_raw = _get_attr("OBSERVATION", "PumpStation", station_id, "pool_areas")
        pool_areas: Dict[int, float] = {}
        for k, v in pool_areas_raw.items():
            try:
                pool_areas[int(k)] = float(v)
            except (ValueError, TypeError):
                pass
        anchor_basin_levels = _get_attr("OBSERVATION", "PumpStation", station_id, "anchor_basin_levels")

        # boundary_level_plan
        blp_attr = _get_attr("REFERENCE", "PumpStation", station_id, "boundary_level_plan")
        boundary_level_plan = None
        if blp_attr and "columns" in blp_attr and "data" in blp_attr:
            try:
                boundary_level_plan = pd.DataFrame(
                    blp_attr["data"],
                    columns=blp_attr["columns"],
                    index=blp_attr.get("index"),
                )
            except Exception:
                pass

        disturbance_estimate = _get_attr("OBSERVATION", "PumpStation", station_id, "disturbance_estimate")

        # demand_plan
        dp_attr = _get_attr("OBSERVATION", "PumpStation", station_id, "demand_plan")
        demand_plan = None
        if dp_attr and "columns" in dp_attr and "data" in dp_attr:
            try:
                demand_plan = pd.DataFrame(
                    dp_attr["data"],
                    columns=dp_attr["columns"],
                    index=dp_attr.get("index"),
                )
            except Exception:
                pass

        start_time_hours_val = _get_value("OBSERVATION", "PumpStation", station_id, "start_time_hours")
        start_time_hours = float(start_time_hours_val) if start_time_hours_val is not None else 0.0

        step_hours_val = _get_value("OBSERVATION", "PumpStation", station_id, "step_hours")
        step_hours = float(step_hours_val) if step_hours_val is not None else 1.0

        config_path_attr = _get_attr("OBSERVATION", "PumpStation", station_id, "config_path")
        config_path = config_path_attr.get("path", "") if config_path_attr else ""

        # ---- upper_flow_refs (other stations) ----
        upper_flow_refs: Dict[int, List[float]] = {}
        for sig in input_data.signals:
            if (sig.type.value if hasattr(sig.type, "value") else sig.type) == "TARGET":
                if sig.object_type == "PumpStation" and sig.object_id != station_id:
                    upper_flow_refs[sig.object_id] = [float(sig.value)] if sig.value is not None else []

        # ---- flow_history ----
        fh_attr = _get_attr("OBSERVATION", "PumpStation", station_id, "flow_history")
        flow_history = [float(v) for v in fh_attr.get("history", [])]

        if not available_unit_ids:
            raise PumpFlowDmpcError(
                "NO_AVAILABLE_PUMP_UNIT",
                "no available running pump unit for station %s" % station_id,
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
            current_front_level=current_front_level,
            current_back_level=current_back_level,
            current_head=current_head,
            current_flow=current_flow,
            basin_levels=basin_levels,
            pool_areas=pool_areas,
            anchor_basin_levels=anchor_basin_levels,
            boundary_level_plan=boundary_level_plan,
            disturbance_estimate=disturbance_estimate,
            demand_plan=demand_plan,
            start_time_hours=start_time_hours,
            step_hours=step_hours,
            upper_flow_refs=upper_flow_refs,
            flow_history=flow_history,
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
