from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from v47_adapter import ImportedV47StationAllocator

from .nhq import HydroNHQGenerator


@dataclass(frozen=True)
class TurbinePowerInput:
    object_id: int
    current_output_power: float = 0.0
    min_output_power: float = 0.0
    max_output_power: Optional[float] = None
    state: Optional[int] = None
    min_power: Optional[float] = None
    max_power: Optional[float] = None
    head: Optional[float] = None
    efficiency: Optional[float] = None
    water_flow_per_mw: Optional[float] = None
    design_head: Optional[float] = None
    min_head: Optional[float] = None
    max_head: Optional[float] = None
    design_power: Optional[float] = None
    design_efficiency: Optional[float] = None
    eta_head_coeff: Optional[float] = None
    eta_power_coeff: Optional[float] = None
    power_ramp_rate: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StationPowerAllocationInput:
    station_id: int
    target_output_power: float
    turbines: List[TurbinePowerInput]
    max_output_power_delta: float = 1.0e9
    default_efficiency: float = 0.9
    stage_hints: Sequence[Dict[str, Any]] = field(default_factory=list)
    context_id: Optional[str] = None
    compute_step: Optional[int] = None
    station_name: Optional[str] = None


@dataclass(frozen=True)
class TurbinePowerAllocation:
    object_id: int
    target_output_power: float
    estimated_water_flow: float
    current_output_power: float


@dataclass(frozen=True)
class StationPowerAllocationResult:
    station_id: int
    target_output_power: float
    allocated_output_power: float
    estimated_water_flow: float
    turbine_allocations: List[TurbinePowerAllocation]
    evidence: Dict[str, Any]


class HydroSimV47PowerAllocator:
    """Hydros compatibility boundary for the imported HydroSim V47 algorithm.

    The public DTOs in this file are kept stable for Edge and tests. The actual
    station allocation path delegates to ``v47_original.HydroSim_V47`` through a
    thin adapter so V47 unit commitment, min-power and state memory semantics are
    provided by the original algorithm implementation.
    """

    algorithm_name = "HydroSim.V47 original imported power allocation"

    def __init__(self) -> None:
        self._imported_allocator = ImportedV47StationAllocator()

    def allocate_station(self, request: StationPowerAllocationInput) -> StationPowerAllocationResult:
        imported_result = self._imported_allocator.allocate_station(request)
        allocations = [
            TurbinePowerAllocation(
                object_id=item.object_id,
                target_output_power=item.target_output_power,
                estimated_water_flow=item.estimated_water_flow,
                current_output_power=item.current_output_power,
            )
            for item in imported_result.turbine_allocations
        ]
        return StationPowerAllocationResult(
            station_id=imported_result.station_id,
            target_output_power=imported_result.target_output_power,
            allocated_output_power=imported_result.allocated_output_power,
            estimated_water_flow=imported_result.estimated_water_flow,
            turbine_allocations=allocations,
            evidence=imported_result.evidence,
        )

    def _allocate_output_power(
        self,
        request: StationPowerAllocationInput,
        target_power: float,
    ) -> tuple[Dict[int, float], Dict[str, Any]]:
        if target_power <= 0.0:
            return {
                turbine.object_id: 0.0
                for turbine in request.turbines
            }, self._zero_target_evidence(request)

        unit_states = [self._unit_state(turbine) for turbine in request.turbines]
        selected_indices, commitment_evidence = self._select_commitment_indices(target_power, unit_states)
        target_by_index, allocation_evidence = self._allocate_committed_units(
            target_power=target_power,
            unit_states=unit_states,
            selected_indices=selected_indices,
            max_delta=float(request.max_output_power_delta),
        )

        projected: Dict[int, float] = {}
        turbine_targets = []
        for index, unit in enumerate(unit_states):
            projected_value = float(target_by_index.get(index, 0.0))
            projected[unit["object_id"]] = projected_value
            turbine_targets.append(
                {
                    "object_id": unit["object_id"],
                    "current_output_power": unit["current"],
                    "state": unit["state"],
                    "selected": index in selected_indices,
                    "raw_target_output_power": allocation_evidence["raw_targets_by_index"].get(index, 0.0),
                    "projected_target_output_power": projected_value,
                    "min_output_power": unit["min_output_power"],
                    "max_output_power": unit["max_output_power"],
                    "min_power": unit["min_power"],
                    "max_power": unit["max_power"],
                    "min_start_power": unit["min_start_power"],
                    "design_power": unit["design_power"],
                    "power_ramp_rate": unit["power_ramp_rate"],
                    "lower_bound": allocation_evidence["lower_bounds_by_index"].get(index),
                    "upper_bound": allocation_evidence["upper_bounds_by_index"].get(index),
                    "head": unit["turbine"].head,
                    "efficiency": unit["turbine"].efficiency,
                    "water_flow_per_mw": unit["turbine"].water_flow_per_mw,
                    "design_efficiency": unit["turbine"].design_efficiency,
                }
            )

        allocated_total = sum(projected.values())
        clipped = allocation_evidence["clipped"]
        known_capacity = all(unit["known_capacity"] for unit in unit_states)
        total_max_output_power = sum(unit["max_power"] for unit in unit_states if unit["known_capacity"])
        return projected, {
            "mode": allocation_evidence["mode"],
            "target_output_power": target_power,
            "total_current_output_power": sum(unit["current"] for unit in unit_states),
            "allocated_output_power": allocated_total,
            "unallocated_output_power": max(float(target_power) - allocated_total, 0.0),
            "total_min_output_power": sum(unit["min_power"] for unit in unit_states),
            "total_min_start_power": sum(unit["min_start_power"] for unit in unit_states),
            "total_max_output_power": total_max_output_power if known_capacity else None,
            "known_capacity": known_capacity,
            "target_exceeds_known_capacity": bool(
                known_capacity and target_power > total_max_output_power + 1e-9
            ),
            "max_output_power_delta": float(request.max_output_power_delta),
            "commitment": commitment_evidence,
            "selected_turbine_ids": [unit_states[index]["object_id"] for index in selected_indices],
            "offline_turbine_ids": [
                unit["object_id"]
                for index, unit in enumerate(unit_states)
                if index not in selected_indices
            ],
            "turbine_targets": turbine_targets,
            "clipped": clipped,
        }

    def _zero_target_evidence(self, request: StationPowerAllocationInput) -> Dict[str, Any]:
        turbine_targets = []
        for turbine in request.turbines:
            unit = self._unit_state(turbine)
            turbine_targets.append(
                {
                    "object_id": unit["object_id"],
                    "current_output_power": unit["current"],
                    "state": unit["state"],
                    "selected": False,
                    "raw_target_output_power": 0.0,
                    "projected_target_output_power": 0.0,
                    "min_output_power": unit["min_output_power"],
                    "max_output_power": unit["max_output_power"],
                    "min_power": unit["min_power"],
                    "max_power": unit["max_power"],
                    "min_start_power": unit["min_start_power"],
                    "design_power": unit["design_power"],
                    "power_ramp_rate": unit["power_ramp_rate"],
                    "lower_bound": 0.0,
                    "upper_bound": 0.0,
                }
            )
        return {
            "mode": "zero_target",
            "target_output_power": 0.0,
            "total_current_output_power": sum(max(float(t.current_output_power), 0.0) for t in request.turbines),
            "allocated_output_power": 0.0,
            "unallocated_output_power": 0.0,
            "total_min_output_power": sum(self._resolved_min_power(t) for t in request.turbines),
            "total_min_start_power": sum(self._min_start_power(t) for t in request.turbines),
            "total_max_output_power": (
                sum(self._resolved_max_power(t) or 0.0 for t in request.turbines)
                if all(self._resolved_max_power(t) is not None for t in request.turbines)
                else None
            ),
            "known_capacity": all(self._resolved_max_power(t) is not None for t in request.turbines),
            "target_exceeds_known_capacity": False,
            "max_output_power_delta": float(request.max_output_power_delta),
            "commitment": {
                "mode": "zero_target",
                "reason": "target_output_power_is_zero",
                "online_turbine_ids_before": [
                    turbine.object_id
                    for turbine in request.turbines
                    if self._is_online(turbine)
                ],
                "selected_turbine_ids": [],
                "offline_turbine_ids": [turbine.object_id for turbine in request.turbines],
            },
            "selected_turbine_ids": [],
            "offline_turbine_ids": [turbine.object_id for turbine in request.turbines],
            "turbine_targets": turbine_targets,
            "clipped": [],
        }

    def _unit_state(self, turbine: TurbinePowerInput) -> Dict[str, Any]:
        max_power = self._resolved_max_power(turbine)
        design_power = self._resolved_design_power(turbine, max_power)
        min_power = self._resolved_min_power(turbine)
        return {
            "object_id": turbine.object_id,
            "turbine": turbine,
            "current": max(float(turbine.current_output_power), 0.0),
            "state": turbine.state,
            "online": self._is_online(turbine),
            "min_output_power": max(float(turbine.min_output_power), 0.0),
            "max_output_power": turbine.max_output_power,
            "min_power": min_power,
            "max_power": max_power if max_power is not None else 1.0e12,
            "known_capacity": max_power is not None,
            "design_power": design_power,
            "min_start_power": max(0.0, design_power * 0.10) if design_power > 0.0 else max(0.0, min_power),
            "power_ramp_rate": self._resolved_power_ramp_rate(turbine, design_power),
        }

    @staticmethod
    def _is_online(turbine: TurbinePowerInput) -> bool:
        if turbine.state is not None:
            return int(turbine.state) == 1
        return max(float(turbine.current_output_power), 0.0) > 1e-6

    @staticmethod
    def _resolved_design_power(turbine: TurbinePowerInput, max_power: Optional[float]) -> float:
        if turbine.design_power is not None and float(turbine.design_power) > 0.0:
            return float(turbine.design_power)
        if max_power is not None and float(max_power) > 0.0:
            return float(max_power)
        if turbine.current_output_power > 0.0:
            return float(turbine.current_output_power)
        return 0.0

    @staticmethod
    def _resolved_min_power(turbine: TurbinePowerInput) -> float:
        if turbine.min_power is not None:
            return max(0.0, float(turbine.min_power))
        return max(0.0, float(turbine.min_output_power))

    @staticmethod
    def _resolved_max_power(turbine: TurbinePowerInput) -> Optional[float]:
        if turbine.max_power is not None:
            return max(0.0, float(turbine.max_power))
        if turbine.max_output_power is not None:
            return max(0.0, float(turbine.max_output_power))
        if turbine.design_power is not None and float(turbine.design_power) > 0.0:
            return float(turbine.design_power)
        return None

    @staticmethod
    def _resolved_power_ramp_rate(turbine: TurbinePowerInput, design_power: float) -> float:
        if turbine.power_ramp_rate is not None and float(turbine.power_ramp_rate) > 0.0:
            return float(turbine.power_ramp_rate)
        if design_power > 0.0:
            return max(10.0, design_power * 0.10)
        return 1.0e12

    def _min_start_power(self, turbine: TurbinePowerInput) -> float:
        max_power = self._resolved_max_power(turbine)
        design_power = self._resolved_design_power(turbine, max_power)
        return max(0.0, design_power * 0.10) if design_power > 0.0 else self._resolved_min_power(turbine)

    def _select_commitment_indices(
        self,
        target_power: float,
        unit_states: List[Dict[str, Any]],
    ) -> tuple[List[int], Dict[str, Any]]:
        total_units = len(unit_states)
        online_indices = [
            index
            for index, unit in enumerate(unit_states)
            if unit["online"]
        ]
        design_values = [unit["design_power"] for unit in unit_states if unit["design_power"] > 0.0]
        unit_design = sorted(design_values)[len(design_values) // 2] if design_values else target_power
        current_count = len(online_indices)
        if current_count > 0:
            count = current_count
            initial_reason = "current_online_state"
        else:
            count = max(1, min(total_units, round(target_power / max(unit_design, 1e-6))))
            initial_reason = "target_design_band"

        min_start_values = [unit["min_start_power"] for unit in unit_states if unit["min_start_power"] > 0.0]
        close_deadband = max(
            min(min_start_values) if min_start_values else 0.0,
            unit_design * 0.10,
        )
        while count < total_units and target_power >= unit_design * count - 1e-9:
            count += 1
        while count > 1 and target_power < unit_design * (count - 1) - close_deadband - 1e-9:
            count -= 1

        adjustments = []
        while count < total_units:
            indices = self._indices_for_count(count, unit_states)
            max_sum = sum(unit_states[index]["max_power"] for index in indices)
            if target_power <= max_sum + 1e-9:
                break
            adjustments.append("increase_for_capacity")
            count += 1
        while count > 1:
            indices = self._indices_for_count(count, unit_states)
            min_start_sum = sum(unit_states[index]["min_start_power"] for index in indices)
            if target_power >= min_start_sum - 1e-9:
                break
            adjustments.append("decrease_for_min_start")
            count -= 1

        selected_indices = self._indices_for_count(count, unit_states)
        return selected_indices, {
            "mode": "v47_unit_commitment",
            "reason": initial_reason,
            "target_output_power": target_power,
            "unit_design_power": unit_design,
            "close_deadband": close_deadband,
            "requested_online_count": count,
            "online_turbine_ids_before": [
                unit_states[index]["object_id"]
                for index in online_indices
            ],
            "selected_turbine_ids": [
                unit_states[index]["object_id"]
                for index in selected_indices
            ],
            "offline_turbine_ids": [
                unit["object_id"]
                for index, unit in enumerate(unit_states)
                if index not in selected_indices
            ],
            "adjustments": adjustments,
        }

    @staticmethod
    def _indices_for_count(count: int, unit_states: List[Dict[str, Any]]) -> List[int]:
        count = max(0, min(len(unit_states), int(count)))
        if count <= 0:
            return []
        online = [
            index
            for index, unit in enumerate(unit_states)
            if unit["online"]
        ]
        online = sorted(online, key=lambda index: (-unit_states[index]["current"], unit_states[index]["object_id"]))
        offline = [index for index in range(len(unit_states)) if index not in set(online)]
        return sorted((online[:count] + offline[: max(0, count - len(online))])[:count])

    def _allocate_committed_units(
        self,
        *,
        target_power: float,
        unit_states: List[Dict[str, Any]],
        selected_indices: List[int],
        max_delta: float,
    ) -> tuple[Dict[int, float], Dict[str, Any]]:
        target_by_index = {index: 0.0 for index in range(len(unit_states))}
        if not selected_indices:
            return target_by_index, {
                "mode": "zero_committed_units",
                "raw_targets_by_index": target_by_index.copy(),
                "lower_bounds_by_index": {index: 0.0 for index in range(len(unit_states))},
                "upper_bounds_by_index": {index: 0.0 for index in range(len(unit_states))},
                "clipped": [],
            }

        max_powers = {index: unit_states[index]["max_power"] for index in selected_indices}
        stable_powers = {
            index: max(unit_states[index]["min_start_power"], unit_states[index]["design_power"] * 0.35)
            for index in selected_indices
        }
        min_start_powers = {
            index: unit_states[index]["min_start_power"]
            for index in selected_indices
        }
        lower = stable_powers if target_power >= sum(stable_powers.values()) - 1e-9 else min_start_powers
        raw_targets = {
            index: target_power / max(len(selected_indices), 1)
            for index in selected_indices
        }
        allocated = {
            index: min(max(raw_targets[index], lower[index]), max_powers[index])
            for index in selected_indices
        }
        allocated = self._redistribute_residual(target_power, selected_indices, allocated, lower, max_powers)
        allocated = self._apply_ramp_limits(target_power, selected_indices, allocated, lower, max_powers, unit_states, max_delta)

        if abs(sum(allocated.values()) - target_power) > 1e-5:
            fallback = self._low_target_fallback(target_power, unit_states)
            if fallback is not None:
                selected_index, selected_target = fallback
                allocated = {selected_index: selected_target}
                selected_indices = [selected_index]
                lower = {selected_index: 0.0}
                max_powers = {selected_index: unit_states[selected_index]["max_power"]}
                raw_targets = {selected_index: target_power}
                mode = "v47_low_target_single_unit_fallback"
            else:
                mode = "v47_unit_commitment_capacity_limited"
        else:
            mode = "v47_unit_commitment"

        clipped = []
        lower_bounds = {index: 0.0 for index in range(len(unit_states))}
        upper_bounds = {index: 0.0 for index in range(len(unit_states))}
        raw_targets_by_index = {index: 0.0 for index in range(len(unit_states))}
        for index in selected_indices:
            raw_value = raw_targets.get(index, target_power / max(len(selected_indices), 1))
            lower_value = lower.get(index, 0.0)
            upper_value = max_powers.get(index, unit_states[index]["max_power"])
            projected_value = allocated.get(index, 0.0)
            lower_bounds[index] = lower_value
            upper_bounds[index] = upper_value
            raw_targets_by_index[index] = raw_value
            target_by_index[index] = projected_value
            if abs(projected_value - raw_value) > 1e-9:
                clipped.append(
                    {
                        "object_id": unit_states[index]["object_id"],
                        "raw_target": raw_value,
                        "projected_target": projected_value,
                        "min_value": lower_value,
                        "max_value": upper_value if unit_states[index]["known_capacity"] else None,
                        "lower_bound": lower_value,
                        "upper_bound": upper_value if unit_states[index]["known_capacity"] else None,
                        "reason": self._clip_reason(projected_value, raw_value, lower_value, upper_value),
                    }
                )
        return target_by_index, {
            "mode": mode,
            "raw_targets_by_index": raw_targets_by_index,
            "lower_bounds_by_index": lower_bounds,
            "upper_bounds_by_index": upper_bounds,
            "clipped": clipped,
        }

    @staticmethod
    def _redistribute_residual(
        target_power: float,
        selected_indices: List[int],
        allocated: Dict[int, float],
        lower: Dict[int, float],
        upper: Dict[int, float],
    ) -> Dict[int, float]:
        result = dict(allocated)
        residual = target_power - sum(result.values())
        while residual > 1e-6:
            candidates = [index for index in selected_indices if result[index] < upper[index] - 1e-9]
            if not candidates:
                break
            index = min(candidates, key=lambda item: result[item])
            inc = min(residual, upper[index] - result[index])
            result[index] += inc
            residual -= inc
        while residual < -1e-6:
            candidates = [index for index in selected_indices if result[index] > lower[index] + 1e-9]
            if not candidates:
                break
            index = max(candidates, key=lambda item: result[item])
            dec = min(-residual, result[index] - lower[index])
            result[index] -= dec
            residual += dec
        return result

    def _apply_ramp_limits(
        self,
        target_power: float,
        selected_indices: List[int],
        allocated: Dict[int, float],
        lower: Dict[int, float],
        upper: Dict[int, float],
        unit_states: List[Dict[str, Any]],
        max_delta: float,
    ) -> Dict[int, float]:
        if max_delta >= 1.0e12:
            return allocated
        ramp_lower = dict(lower)
        ramp_upper = dict(upper)
        for index in selected_indices:
            unit = unit_states[index]
            prev = unit["current"]
            ramp = min(max_delta, unit["power_ramp_rate"])
            if prev > 1e-6 or unit["online"]:
                ramp_lower[index] = max(ramp_lower[index], prev - ramp)
                ramp_upper[index] = min(ramp_upper[index], prev + ramp)
            else:
                ramp_upper[index] = min(ramp_upper[index], max(ramp_lower[index], ramp))
            if ramp_upper[index] < ramp_lower[index] - 1e-9:
                ramp_upper[index] = ramp_lower[index]
        if sum(ramp_lower.values()) > target_power + 1e-6 or sum(ramp_upper.values()) < target_power - 1e-6:
            return allocated
        smoothed = {
            index: min(max(allocated[index], ramp_lower[index]), ramp_upper[index])
            for index in selected_indices
        }
        return self._redistribute_residual(target_power, selected_indices, smoothed, ramp_lower, ramp_upper)

    @staticmethod
    def _low_target_fallback(
        target_power: float,
        unit_states: List[Dict[str, Any]],
    ) -> Optional[tuple[int, float]]:
        feasible = [
            (index, unit["max_power"])
            for index, unit in enumerate(unit_states)
            if target_power <= unit["max_power"] + 1e-9
        ]
        if not feasible:
            return None
        selected_index = min(feasible, key=lambda item: (unit_states[item[0]]["current"] <= 1e-6, unit_states[item[0]]["object_id"]))[0]
        return selected_index, target_power

    @staticmethod
    def _clip_reason(projected_value: float, target_value: float, lower_bound: float, upper_bound: float) -> str:
        if projected_value >= upper_bound and target_value > upper_bound:
            return "above_upper_bound"
        if projected_value <= lower_bound and target_value < lower_bound:
            return "below_lower_bound"
        return "projected_to_bounds"

    @staticmethod
    def _estimate_water_flow(
        *,
        power_mw: float,
        turbine: TurbinePowerInput,
        default_efficiency: float,
    ) -> float:
        if power_mw <= 0.0:
            return 0.0
        if turbine.water_flow_per_mw is not None:
            return float(power_mw) * float(turbine.water_flow_per_mw)
        if turbine.head is None or float(turbine.head) <= 0.0:
            return 0.0
        if turbine.design_head is None and turbine.design_power is None and turbine.design_efficiency is None:
            efficiency = turbine.efficiency if turbine.efficiency is not None else default_efficiency
            efficiency = min(max(float(efficiency), 1e-6), 1.0)
            return float(power_mw) * 1000.0 / (9.81 * float(turbine.head) * efficiency)
        min_power = HydroSimV47PowerAllocator._resolved_min_power(turbine)
        nhq = HydroNHQGenerator(
            design_head=turbine.design_head if turbine.design_head is not None else float(turbine.head),
            min_head=turbine.min_head if turbine.min_head is not None else max(float(turbine.head) * 0.6, 1e-6),
            max_head=turbine.max_head if turbine.max_head is not None else max(float(turbine.head) * 1.4, float(turbine.head) + 1e-6),
            design_power=turbine.design_power if turbine.design_power is not None else max(float(power_mw), 1e-6),
            min_power=min_power if min_power > 0.0 else max(float(power_mw) * 0.2, 1e-6),
            max_power=HydroSimV47PowerAllocator._resolved_max_power(turbine) or max(float(power_mw) * 1.2, float(power_mw) + 1e-6),
            design_efficiency=turbine.design_efficiency if turbine.design_efficiency is not None else default_efficiency,
            eta_head_coeff=turbine.eta_head_coeff if turbine.eta_head_coeff is not None else 0.20,
            eta_power_coeff=turbine.eta_power_coeff if turbine.eta_power_coeff is not None else 0.40,
        )
        if 0.0 < power_mw < min_power:
            min_flow, _ = nhq.query(float(turbine.head), min_power)
            return float(min_flow * float(power_mw) / min_power)
        flow, _ = nhq.query(float(turbine.head), float(power_mw))
        return flow
