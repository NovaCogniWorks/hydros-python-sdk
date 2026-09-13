from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from v47_original import HydroSim_V47 as v47


@dataclass(frozen=True)
class ImportedV47TurbineAllocation:
    object_id: int
    target_output_power: float
    estimated_water_flow: float
    current_output_power: float


@dataclass(frozen=True)
class ImportedV47StationAllocationResult:
    station_id: int
    target_output_power: float
    allocated_output_power: float
    estimated_water_flow: float
    turbine_allocations: List[ImportedV47TurbineAllocation]
    evidence: Dict[str, Any]


class ImportedV47StationAllocator:
    """Thin Hydros adapter over the imported HydroSim V47 station algorithm.

    Algorithm semantics stay in ``HydroSim_V47.HydroStation``. This adapter only
    maps Hydros control inputs into original V47 objects and keeps per-task
    station instances so V47 commitment memory is not lost between calls.
    """

    algorithm_name = "HydroSim.V47 original imported station allocation"

    def __init__(self) -> None:
        self._sessions: Dict[str, v47.HydroStation] = {}
        self._config_signatures: Dict[str, str] = {}

    def allocate_station(self, request: Any) -> ImportedV47StationAllocationResult:
        if not request.turbines:
            raise ValueError(f"No turbines configured for station={request.station_id}.")

        target_power = max(float(request.target_output_power), 0.0)
        session_key = self._session_key(request)
        unit_resolutions = [
            self._resolve_unit_config(
                turbine,
                station_max_output_power_delta=getattr(request, "max_output_power_delta", None),
                default_efficiency=getattr(request, "default_efficiency", None),
            )
            for turbine in request.turbines
        ]
        unit_cfgs = [config for config, _ in unit_resolutions]
        unit_parameter_evidence = [evidence for _, evidence in unit_resolutions]
        config_signature = self._config_signature(request, unit_cfgs)
        station_created = session_key not in self._sessions or self._config_signatures.get(session_key) != config_signature
        if station_created:
            station = self._create_station(request, unit_cfgs)
            self._sessions[session_key] = station
            self._config_signatures[session_key] = config_signature
        else:
            station = self._sessions[session_key]

        self._apply_runtime_state(station, request.turbines, initialize_memory=station_created)
        before_signature = self._commitment_signature(station)
        before_hold = int(getattr(station, "_commitment_hold_remaining", 0))
        result = v47.allocate_intra_station_power(
            station,
            target_power,
            update_commitment_memory=True,
        )
        after_signature = self._commitment_signature(station)
        after_hold = int(getattr(station, "_commitment_hold_remaining", 0))

        selected_indices, selected_powers = self._selected_units_from_station(station, result)
        selected_index_set = set(selected_indices)
        target_by_index = {index: 0.0 for index in range(len(request.turbines))}
        for index, power in zip(selected_indices, selected_powers):
            target_by_index[int(index)] = float(power)
        raw_targets = [max(float(target_by_index.get(index, 0.0)), 0.0) for index in range(len(request.turbines))]
        projected_targets, target_bounds = self._project_targets(
            request.turbines,
            unit_cfgs,
            raw_targets,
            unit_parameter_evidence,
        )

        allocations: List[ImportedV47TurbineAllocation] = []
        turbine_targets: List[Dict[str, Any]] = []
        for index, turbine in enumerate(request.turbines):
            unit = station.multi_station[index]
            raw_target = raw_targets[index]
            target = projected_targets[index]
            flow = float(station._unit_flow_for_power(unit, target))
            allocations.append(
                ImportedV47TurbineAllocation(
                    object_id=int(turbine.object_id),
                    target_output_power=target,
                    estimated_water_flow=flow,
                    current_output_power=max(float(turbine.current_output_power), 0.0),
                )
            )
            turbine_targets.append(self._turbine_target_evidence(
                turbine,
                unit,
                index,
                raw_target,
                target,
                flow,
                selected_index_set,
                unit_parameter_evidence[index],
                self._runtime_observation_evidence(turbine, unit),
                target_bounds[index],
            ))

        allocated_power = sum(item.target_output_power for item in allocations)
        estimated_flow = sum(item.estimated_water_flow for item in allocations)
        mode = "zero_target" if target_power <= 1e-6 else "v47_unit_commitment"
        evidence = {
            "algorithm": self.algorithm_name,
            "allocator_source": "imported_v47_original",
            "core_session_id": session_key,
            "station_id": int(request.station_id),
            "target_output_power": target_power,
            "allocated_output_power": allocated_power,
            "estimated_turbine_water_flow": estimated_flow,
            "available_turbine_count": len(request.turbines),
            "allocation": {
                "mode": mode,
                "allocator_source": "imported_v47_original",
                "core_session_id": session_key,
                "session_created": station_created,
                "state_memory_used": not station_created,
                "commitment_signature_before": before_signature,
                "commitment_signature_after": after_signature,
                "hold_remaining_before": before_hold,
                "hold_remaining": after_hold,
                "target_output_power": target_power,
                "total_current_output_power": sum(max(float(t.current_output_power), 0.0) for t in request.turbines),
                "allocated_output_power": allocated_power,
                "unallocated_output_power": max(target_power - allocated_power, 0.0),
                "overallocated_output_power": max(allocated_power - target_power, 0.0),
                "allocation_gap": target_power - allocated_power,
                "total_min_output_power": sum(float(cfg["min_power"]) for cfg in unit_cfgs),
                "total_min_start_power": sum(float(cfg["design_power"]) * 0.10 for cfg in unit_cfgs),
                "total_max_output_power": sum(float(cfg["max_power"]) for cfg in unit_cfgs),
                "known_capacity": True,
                "target_exceeds_known_capacity": target_power > sum(float(cfg["max_power"]) for cfg in unit_cfgs) + 1e-9,
                "max_output_power_delta": float(getattr(request, "max_output_power_delta", 0.0)),
                "commitment": {
                    "mode": "imported_v47_original",
                    "reason": "HydroStation.allocate_power",
                    "online_turbine_ids_before": [
                        int(request.turbines[index].object_id)
                        for index in before_signature
                        if 0 <= index < len(request.turbines)
                    ],
                    "selected_turbine_ids": [
                        int(request.turbines[index].object_id)
                        for index in selected_indices
                        if 0 <= index < len(request.turbines)
                    ],
                    "offline_turbine_ids": [
                        int(turbine.object_id)
                        for index, turbine in enumerate(request.turbines)
                        if index not in selected_index_set
                    ],
                    "hold_remaining_before": before_hold,
                    "hold_remaining": after_hold,
                },
                "selected_turbine_ids": [
                    int(request.turbines[index].object_id)
                    for index in selected_indices
                    if 0 <= index < len(request.turbines)
                ],
                "offline_turbine_ids": [
                    int(turbine.object_id)
                    for index, turbine in enumerate(request.turbines)
                    if index not in selected_index_set
                ],
                "turbine_targets": turbine_targets,
                "clipped": self._clipped_evidence(target_power, turbine_targets, unit_cfgs),
                "v47_original_result": result,
            },
        }
        return ImportedV47StationAllocationResult(
            station_id=int(request.station_id),
            target_output_power=target_power,
            allocated_output_power=allocated_power,
            estimated_water_flow=estimated_flow,
            turbine_allocations=allocations,
            evidence=evidence,
        )

    def _create_station(self, request: Any, unit_cfgs: Sequence[Dict[str, Any]]) -> v47.HydroStation:
        station_design_head = self._station_design_head(request.turbines)
        station_design_power = sum(float(cfg["design_power"]) for cfg in unit_cfgs)
        station_min_power = sum(float(cfg["min_power"]) for cfg in unit_cfgs)
        station_max_power = sum(float(cfg["max_power"]) for cfg in unit_cfgs)
        unit_dispatch_min_p = min(float(cfg["design_power"]) * 0.10 for cfg in unit_cfgs)
        return v47.HydroStation(
            station_id=int(request.station_id),
            name=str(getattr(request, "station_name", None) or f"station-{request.station_id}"),
            design_head=station_design_head,
            design_power=station_design_power,
            min_power=station_min_power,
            max_power=station_max_power,
            unit_cfgs=unit_cfgs,
            unit_dispatch_min_p=unit_dispatch_min_p,
            station_target_ramp_rate=float(getattr(request, "max_output_power_delta", 120.0) or 120.0),
        )

    def _apply_runtime_state(self, station: v47.HydroStation, turbines: Sequence[Any], *, initialize_memory: bool) -> None:
        total_power = 0.0
        for index, turbine in enumerate(turbines):
            unit = station.multi_station[index]
            head = self._positive_float(
                getattr(turbine, "head", None),
                getattr(turbine, "design_head", None),
                unit.design_head,
            )
            unit.set_head(head)
            current = max(float(getattr(turbine, "current_output_power", 0.0) or 0.0), 0.0)
            unit.current_power = min(current, unit.max_power)
            unit.target_power = unit.current_power
            unit.state = self._runtime_state(turbine, unit.current_power)
            unit.flow, unit.efficiency = unit._query_flow_for_current_power() if unit.current_power > 1e-6 else (0.0, 0.0)
            total_power += unit.current_power
        station.current_p = float(total_power)
        station.target_p = float(total_power)
        station.num_current = sum(1 for unit in station.multi_station if unit.current_power > 1e-6 or unit.state == 1)
        station.head = self._station_design_head(turbines)
        if initialize_memory:
            station._last_commitment_signature = station._current_commitment_signature()
            station._commitment_hold_remaining = 0

    def _unit_config(self, turbine: Any) -> Dict[str, Any]:
        config, _ = self._resolve_unit_config(turbine)
        return config

    def _resolve_unit_config(
        self,
        turbine: Any,
        *,
        station_max_output_power_delta: Any = None,
        default_efficiency: Any = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        sources = dict(getattr(turbine, "parameter_sources", {}) or {})
        fallback_fields: List[str] = []

        design_head_input = self._positive_or_none(getattr(turbine, "design_head", None))
        head_input = self._positive_or_none(getattr(turbine, "head", None))
        if design_head_input is not None:
            design_head = design_head_input
            design_head_source = sources.get("design_head", "control_input")
        elif head_input is not None:
            design_head = head_input
            design_head_source = f"derived_from:{sources.get('head', 'control_input')}"
            fallback_fields.append("design_head")
        else:
            design_head = 50.0
            design_head_source = "algorithm_fallback:50.0"
            fallback_fields.append("design_head")

        min_head_input = self._positive_or_none(getattr(turbine, "min_head", None))
        if min_head_input is not None:
            min_head = min_head_input
            min_head_source = sources.get("min_head", "control_input")
        else:
            min_head = design_head * 0.6
            min_head_source = "algorithm_fallback:design_head*0.6"
            fallback_fields.append("min_head")

        max_head_input = self._positive_or_none(getattr(turbine, "max_head", None))
        if max_head_input is not None:
            max_head = max_head_input
            max_head_source = sources.get("max_head", "control_input")
        else:
            max_head = design_head * 1.4
            max_head_source = "algorithm_fallback:design_head*1.4"
            fallback_fields.append("max_head")
        if max_head <= min_head:
            max_head = min_head + 1e-6
            max_head_source = "algorithm_adjustment:min_head+1e-6"
            if "max_head" not in fallback_fields:
                fallback_fields.append("max_head")

        design_power_input = self._positive_or_none(getattr(turbine, "design_power", None))
        runtime_max_power = self._positive_or_none(getattr(turbine, "max_output_power", None))
        physical_max_power = self._positive_or_none(getattr(turbine, "max_power", None))
        physical_max_fallback = False
        if physical_max_power is not None:
            physical_max_source = sources.get("max_power", "control_input")
        elif design_power_input is not None:
            physical_max_power = design_power_input
            physical_max_source = f"derived_from:{sources.get('design_power', 'control_input')}"
            physical_max_fallback = True
        elif runtime_max_power is not None:
            physical_max_power = runtime_max_power
            physical_max_source = f"derived_from:{sources.get('max_output_power', 'runtime_range')}"
            physical_max_fallback = True
        else:
            physical_max_power = max(float(getattr(turbine, "current_output_power", 0.0) or 0.0), 1.0)
            physical_max_source = "algorithm_fallback:max(current_output_power,1.0)"
            physical_max_fallback = True

        if design_power_input is not None:
            design_power = design_power_input
            design_power_source = sources.get("design_power", "control_input")
        else:
            design_power = physical_max_power
            design_power_source = f"derived_from:{physical_max_source}"
            fallback_fields.append("design_power")

        physical_min_power = self._positive_or_none(getattr(turbine, "min_power", None))
        physical_min_fallback = False
        if physical_min_power is not None:
            physical_min_source = sources.get("min_power", "control_input")
        else:
            physical_min_power = min(physical_max_power, max(design_power * 0.10, 1e-6))
            physical_min_source = "algorithm_fallback:min(physical_max_power,design_power*0.10)"
            physical_min_fallback = True

        runtime_min_power = self._non_negative_or_none(getattr(turbine, "min_output_power", None))
        effective_min_power = max(physical_min_power, runtime_min_power or 0.0)
        effective_max_power = min(
            value for value in (physical_max_power, runtime_max_power) if value is not None
        )
        effective_min_source = (
            sources.get("min_output_power", "runtime_range")
            if runtime_min_power is not None and runtime_min_power > physical_min_power
            else physical_min_source
        )
        effective_max_source = (
            sources.get("max_output_power", "runtime_range")
            if runtime_max_power is not None and runtime_max_power < physical_max_power
            else physical_max_source
        )
        if effective_min_power > effective_max_power + 1e-9:
            raise ValueError(
                "Empty turbine output-power constraint intersection: "
                f"object_id={turbine.object_id}, physical=[{physical_min_power},{physical_max_power}], "
                f"runtime=[{runtime_min_power},{runtime_max_power}]."
            )

        if physical_max_fallback:
            fallback_fields.append("max_power")
        if physical_min_fallback:
            fallback_fields.append("min_power")

        power_ramp_rate_input = self._positive_or_none(getattr(turbine, "power_ramp_rate", None))
        physical_ramp_rate = power_ramp_rate_input or max(10.0, design_power * 0.10)
        physical_ramp_source = (
            sources.get("power_ramp_rate", "control_input")
            if power_ramp_rate_input is not None
            else "algorithm_fallback:max(10.0,design_power*0.10)"
        )
        if power_ramp_rate_input is None:
            fallback_fields.append("power_ramp_rate")
        profile_ramp_rate = self._positive_or_none(station_max_output_power_delta)
        power_ramp_rate = min(
            value for value in (physical_ramp_rate, profile_ramp_rate) if value is not None
        )
        power_ramp_rate_source = (
            physical_ramp_source
            if profile_ramp_rate is None or physical_ramp_rate <= profile_ramp_rate
            else "station_profile:max_output_power_delta"
        )

        default_design_efficiency = self._positive_or_none(default_efficiency) or 0.93
        default_design_efficiency_source = (
            "station_profile:default_efficiency"
            if self._positive_or_none(default_efficiency) is not None
            else "algorithm_fallback:0.93"
        )
        efficiency_defaults = {
            "design_efficiency": (default_design_efficiency, default_design_efficiency_source),
            "eta_head_coeff": (0.20, "algorithm_fallback:0.20"),
            "eta_power_coeff": (0.40, "algorithm_fallback:0.40"),
        }
        efficiency_values: Dict[str, float] = {}
        efficiency_sources: Dict[str, str] = {}
        for field_name, (default_value, default_source) in efficiency_defaults.items():
            configured = self._positive_or_none(getattr(turbine, field_name, None))
            if configured is not None:
                efficiency_values[field_name] = configured
                efficiency_sources[field_name] = sources.get(field_name, "control_input")
            else:
                efficiency_values[field_name] = default_value
                efficiency_sources[field_name] = default_source
                fallback_fields.append(field_name)

        config = {
            "ID": int(turbine.object_id),
            "Name": str(getattr(turbine, "attributes", {}).get("object_name") or f"turbine-{turbine.object_id}"),
            "State": self._runtime_state(turbine, float(getattr(turbine, "current_output_power", 0.0) or 0.0)),
            "design_head": design_head,
            "min_head": min_head,
            "max_head": max_head,
            "design_power": design_power,
            "min_power": effective_min_power,
            "max_power": effective_max_power,
            "power_ramp_rate": power_ramp_rate,
            "design_efficiency": efficiency_values["design_efficiency"],
            "eta_head_coeff": efficiency_values["eta_head_coeff"],
            "eta_power_coeff": efficiency_values["eta_power_coeff"],
        }
        parameter_sources = {
            "design_head": design_head_source,
            "min_head": min_head_source,
            "max_head": max_head_source,
            "design_power": design_power_source,
            "min_power": effective_min_source,
            "max_power": effective_max_source,
            "power_ramp_rate": power_ramp_rate_source,
            **efficiency_sources,
        }
        parameter_evidence = {
            field_name: {
                "value": float(config[field_name]),
                "source": parameter_sources[field_name],
                "fallback": field_name in fallback_fields,
            }
            for field_name in parameter_sources
        }
        return config, {
            "parameters": parameter_evidence,
            "fallback_fields": fallback_fields,
            "constraints": {
                "physical": {
                    "min": float(physical_min_power),
                    "max": float(physical_max_power),
                    "min_source": physical_min_source,
                    "max_source": physical_max_source,
                    "ramp": float(physical_ramp_rate),
                    "ramp_source": physical_ramp_source,
                },
                "runtime": {
                    "min": float(runtime_min_power or 0.0),
                    "max": float(runtime_max_power) if runtime_max_power is not None else None,
                    "min_source": sources.get("min_output_power", "runtime_range"),
                    "max_source": sources.get("max_output_power", "runtime_range"),
                },
                "effective": {
                    "min": float(effective_min_power),
                    "max": float(effective_max_power),
                },
                "profile_ramp": float(profile_ramp_rate) if profile_ramp_rate is not None else None,
                "effective_ramp": float(power_ramp_rate),
                "effective_ramp_source": power_ramp_rate_source,
            },
        }

    def _turbine_target_evidence(
        self,
        turbine: Any,
        unit: Any,
        index: int,
        raw_target: float,
        target: float,
        flow: float,
        selected_indices: Sequence[int],
        parameter_evidence: Dict[str, Any],
        runtime_observation_evidence: Dict[str, Any],
        target_bound: Dict[str, float],
    ) -> Dict[str, Any]:
        return {
            "object_id": int(turbine.object_id),
            "current_output_power": max(float(getattr(turbine, "current_output_power", 0.0) or 0.0), 0.0),
            "state": getattr(turbine, "state", None),
            "selected": index in selected_indices,
            "commanded_on": target > 1e-9,
            "raw_target_output_power": raw_target,
            "projected_target_output_power": target,
            "target_output_power": target,
            "estimated_water_flow": flow,
            "min_output_power": float(getattr(turbine, "min_output_power", 0.0) or 0.0),
            "max_output_power": getattr(turbine, "max_output_power", None),
            "min_power": unit.min_power,
            "max_power": unit.max_power,
            "min_start_power": unit.min_start_power,
            "design_power": unit.design_power,
            "power_ramp_rate": unit.power_ramp_rate,
            "lower_bound": target_bound["lower"],
            "upper_bound": target_bound["upper"],
            "head": unit.head,
            "efficiency": unit.efficiency,
            "design_efficiency": getattr(unit.nhq, "design_efficiency", None),
            "v47_parameters": parameter_evidence["parameters"],
            "v47_parameter_fallback_fields": parameter_evidence["fallback_fields"],
            "constraints": parameter_evidence["constraints"],
            "v47_runtime_observations": runtime_observation_evidence["observations"],
            "v47_runtime_observation_fallback_fields": runtime_observation_evidence["fallback_fields"],
        }

    def _runtime_observation_evidence(self, turbine: Any, unit: Any) -> Dict[str, Any]:
        sources = dict(getattr(turbine, "parameter_sources", {}) or {})
        fallback_fields: List[str] = []

        head_input = self._positive_or_none(getattr(turbine, "head", None))
        if head_input is not None:
            head_source = sources.get("head", "control_input")
        else:
            head_source = f"derived_from:{sources.get('design_head', 'v47_unit_config')}"
            fallback_fields.append("head")

        state_input = getattr(turbine, "state", None)
        if state_input is not None:
            state_source = sources.get("state", "control_input")
        elif getattr(turbine, "attributes", {}).get("status") is not None:
            state_source = "derived_from:actuator_status"
            fallback_fields.append("state")
        else:
            state_source = "derived_from:current_output_power"
            fallback_fields.append("state")

        observations = {
            "current_output_power": {
                "value": max(float(getattr(turbine, "current_output_power", 0.0) or 0.0), 0.0),
                "source": sources.get("current_output_power", "control_input"),
                "fallback": False,
            },
            "head": {
                "value": float(unit.head),
                "source": head_source,
                "fallback": "head" in fallback_fields,
            },
            "state": {
                "value": int(unit.state),
                "source": state_source,
                "fallback": "state" in fallback_fields,
            },
        }
        return {"observations": observations, "fallback_fields": fallback_fields}

    @staticmethod
    def _positive_or_none(value: Any) -> Optional[float]:
        if value is None:
            return None
        candidate = float(value)
        return candidate if candidate > 0.0 else None

    @staticmethod
    def _non_negative_or_none(value: Any) -> Optional[float]:
        if value is None:
            return None
        candidate = float(value)
        return candidate if candidate >= 0.0 else None

    @classmethod
    def _project_targets(
        cls,
        turbines: Sequence[Any],
        unit_cfgs: Sequence[Dict[str, Any]],
        raw_targets: Sequence[float],
        unit_parameter_evidence: Sequence[Dict[str, Any]],
    ) -> tuple[List[float], List[Dict[str, float]]]:
        projected: List[float] = []
        bounds: List[Dict[str, float]] = []
        for turbine, cfg, raw_target, parameter_evidence in zip(
            turbines,
            unit_cfgs,
            raw_targets,
            unit_parameter_evidence,
        ):
            current = max(float(getattr(turbine, "current_output_power", 0.0) or 0.0), 0.0)
            effective_min = float(cfg["min_power"])
            effective_max = float(cfg["max_power"])
            effective_ramp = float(cfg["power_ramp_rate"])
            runtime_min = float(parameter_evidence["constraints"]["runtime"]["min"])
            ramp_lower = max(0.0, current - effective_ramp)
            ramp_upper = current + effective_ramp

            lower = ramp_lower
            upper = min(effective_max, ramp_upper)
            if lower > upper + 1e-9:
                raise ValueError(
                    "No feasible turbine output-power target: "
                    f"object_id={turbine.object_id}, current={current}, "
                    f"effective=[{effective_min},{effective_max}], effective_ramp={effective_ramp}."
                )
            target = max(lower, min(upper, float(raw_target)))
            if runtime_min > 0.0 and 1e-9 < target < runtime_min:
                online_lower = max(runtime_min, lower)
                online_feasible = online_lower <= upper + 1e-9
                off_feasible = lower <= 1e-9
                if not online_feasible and not off_feasible:
                    raise ValueError(
                        "No feasible turbine runtime-range target: "
                        f"object_id={turbine.object_id}, current={current}, "
                        f"runtime_min={runtime_min}, upper={upper}, effective_ramp={effective_ramp}."
                    )
                if not online_feasible:
                    target = 0.0
                elif not off_feasible:
                    target = online_lower
                else:
                    online_target = max(online_lower, min(upper, float(raw_target)))
                    target = 0.0 if raw_target <= online_lower / 2.0 else online_target

            projected.append(float(target))
            bounds.append({"lower": float(lower), "upper": float(upper)})
        return projected, bounds

    @staticmethod
    def _runtime_state(turbine: Any, current_power: float) -> int:
        state = getattr(turbine, "state", None)
        if state is not None:
            return int(state)
        status = getattr(turbine, "attributes", {}).get("status")
        if isinstance(status, str):
            return 0 if status.upper() == "OFF" else 1
        return 1 if current_power > 1e-6 else 0

    @staticmethod
    def _station_design_head(turbines: Sequence[Any]) -> float:
        heads = [
            float(value)
            for turbine in turbines
            for value in (getattr(turbine, "head", None), getattr(turbine, "design_head", None))
            if value is not None and float(value) > 0.0
        ]
        return sum(heads) / len(heads) if heads else 50.0

    @staticmethod
    def _positive_float(*values: Any) -> float:
        for value in values:
            if value is None:
                continue
            candidate = float(value)
            if candidate > 0.0:
                return candidate
        return 1e-6

    @staticmethod
    def _session_key(request: Any) -> str:
        context_id = getattr(request, "context_id", None) or "local"
        return f"{context_id}:{int(request.station_id)}"

    @staticmethod
    def _config_signature(request: Any, unit_cfgs: Sequence[Dict[str, Any]]) -> str:
        payload = {
            "station_id": int(request.station_id),
            "units": [
                {
                    key: cfg[key]
                    for key in (
                        "ID",
                        "design_head",
                        "min_head",
                        "max_head",
                        "design_power",
                        "min_power",
                        "max_power",
                        "power_ramp_rate",
                        "design_efficiency",
                        "eta_head_coeff",
                        "eta_power_coeff",
                    )
                }
                for cfg in unit_cfgs
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _commitment_signature(station: v47.HydroStation) -> List[int]:
        signature = getattr(station, "_last_commitment_signature", tuple())
        return [int(index) for index in signature]

    @staticmethod
    def _selected_units_from_station(station: v47.HydroStation, result: Dict[str, Any]) -> tuple[List[int], List[float]]:
        selected_indices: List[int] = []
        selected_powers: List[float] = []
        unit_array = getattr(station, "unit_array", None)
        if unit_array is not None:
            for row in unit_array:
                power = float(row[0])
                if power <= 1e-9:
                    continue
                original_index = int(row[5])
                if 0 <= original_index < len(station.multi_station):
                    selected_indices.append(original_index)
                    selected_powers.append(power)
        if selected_indices:
            return selected_indices, selected_powers

        return (
            [int(index) for index in result.get("unit_indices", [])],
            [float(value) for value in result.get("unit_power_mw", [])],
        )

    @staticmethod
    def _clipped_evidence(
        target_power: float,
        turbine_targets: Sequence[Dict[str, Any]],
        unit_cfgs: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        clipped = []
        for target in turbine_targets:
            raw = float(target["raw_target_output_power"])
            projected = float(target["projected_target_output_power"])
            if abs(raw - projected) <= 1e-9:
                continue
            lower = float(target["lower_bound"])
            upper = float(target["upper_bound"])
            if raw > upper + 1e-9:
                reason = "above_upper_bound"
            elif raw < lower - 1e-9:
                reason = "below_lower_bound"
            else:
                reason = "projected_to_feasible_target"
            clipped.append({
                "object_id": int(target["object_id"]),
                "reason": reason,
                "raw_value": raw,
                "projected_value": projected,
                "min_value": lower,
                "max_value": upper,
            })
        total_max = sum(float(cfg["max_power"]) for cfg in unit_cfgs)
        if target_power > total_max + 1e-9 and not clipped:
            clipped.extend(
                {
                    "object_id": int(cfg["ID"]),
                    "reason": "above_upper_bound",
                    "max_value": float(cfg["max_power"]),
                }
                for cfg in unit_cfgs
            )
        return clipped
