from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .nhq import HydroNHQGenerator


@dataclass(frozen=True)
class TurbinePowerInput:
    object_id: int
    current_output_power: float = 0.0
    min_output_power: float = 0.0
    max_output_power: Optional[float] = None
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
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StationPowerAllocationInput:
    station_id: int
    target_output_power: float
    turbines: List[TurbinePowerInput]
    max_output_power_delta: float = 1.0e9
    default_efficiency: float = 0.9
    stage_hints: Sequence[Dict[str, Any]] = field(default_factory=list)


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
    """Pure V47-compatible station output-power allocator.

    This module is the production-facing boundary for the Edge control algorithm.
    It intentionally excludes plotting, file IO, demos and CLI behavior from the
    original HydroSim.V47 script.
    """

    algorithm_name = "HydroSim.V47-compatible power allocation"

    def allocate_station(self, request: StationPowerAllocationInput) -> StationPowerAllocationResult:
        if not request.turbines:
            raise ValueError(f"No turbines configured for station={request.station_id}.")

        target_power = max(float(request.target_output_power), 0.0)
        target_map, allocation_evidence = self._allocate_output_power(request, target_power)
        allocations = [
            TurbinePowerAllocation(
                object_id=turbine.object_id,
                target_output_power=target_map[turbine.object_id],
                estimated_water_flow=self._estimate_water_flow(
                    power_mw=target_map[turbine.object_id],
                    turbine=turbine,
                    default_efficiency=request.default_efficiency,
                ),
                current_output_power=max(float(turbine.current_output_power), 0.0),
            )
            for turbine in request.turbines
        ]
        allocated_power = sum(item.target_output_power for item in allocations)
        estimated_flow = sum(item.estimated_water_flow for item in allocations)
        evidence = {
            "algorithm": self.algorithm_name,
            "station_id": request.station_id,
            "target_output_power": target_power,
            "allocated_output_power": allocated_power,
            "estimated_turbine_water_flow": estimated_flow,
            "available_turbine_count": len(request.turbines),
            "feedback_used": bool(request.stage_hints),
            "stage_hint_count": len(request.stage_hints),
            "allocation": allocation_evidence,
        }
        return StationPowerAllocationResult(
            station_id=request.station_id,
            target_output_power=target_power,
            allocated_output_power=allocated_power,
            estimated_water_flow=estimated_flow,
            turbine_allocations=allocations,
            evidence=evidence,
        )

    def _allocate_output_power(
        self,
        request: StationPowerAllocationInput,
        target_power: float,
    ) -> tuple[Dict[int, float], Dict[str, Any]]:
        current_values = {
            turbine.object_id: max(float(turbine.current_output_power), 0.0)
            for turbine in request.turbines
        }
        total_current = sum(current_values.values())
        if target_power <= 0.0:
            raw_targets = {turbine.object_id: 0.0 for turbine in request.turbines}
            mode = "zero_target"
        elif total_current > 0.0:
            raw_targets = {
                turbine.object_id: target_power * (current_values[turbine.object_id] / total_current)
                for turbine in request.turbines
            }
            mode = "current_power_ratio"
        else:
            even_target = target_power / max(len(request.turbines), 1)
            raw_targets = {turbine.object_id: even_target for turbine in request.turbines}
            mode = "even"

        projected: Dict[int, float] = {}
        clipped = []
        turbine_targets = []
        known_capacity = True
        total_min_output_power = 0.0
        total_max_output_power = 0.0
        for turbine in request.turbines:
            current_value = current_values[turbine.object_id]
            target_value = raw_targets[turbine.object_id]
            min_value = max(0.0, float(turbine.min_output_power))
            max_value = turbine.max_output_power
            total_min_output_power += min_value
            if max_value is None:
                known_capacity = False
            else:
                total_max_output_power += max(0.0, float(max_value))

            lower_bound = max(0.0, min_value, current_value - float(request.max_output_power_delta))
            upper_bound = current_value + float(request.max_output_power_delta)
            if max_value is not None:
                upper_bound = min(upper_bound, float(max_value))
            projected_value = float(min(max(target_value, lower_bound), upper_bound))
            if abs(projected_value - target_value) > 1e-9:
                clipped.append(
                    {
                        "object_id": turbine.object_id,
                        "raw_target": target_value,
                        "projected_target": projected_value,
                        "min_value": min_value,
                        "max_value": max_value,
                        "lower_bound": lower_bound,
                        "upper_bound": upper_bound,
                        "reason": self._clip_reason(projected_value, target_value, lower_bound, upper_bound),
                    }
                )
            projected[turbine.object_id] = projected_value
            turbine_targets.append(
                {
                    "object_id": turbine.object_id,
                    "current_output_power": current_value,
                    "raw_target_output_power": target_value,
                    "projected_target_output_power": projected_value,
                    "min_output_power": min_value,
                    "max_output_power": max_value,
                    "lower_bound": lower_bound,
                    "upper_bound": upper_bound,
                    "head": turbine.head,
                    "efficiency": turbine.efficiency,
                    "water_flow_per_mw": turbine.water_flow_per_mw,
                    "design_power": turbine.design_power,
                    "design_efficiency": turbine.design_efficiency,
                }
            )

        allocated_total = sum(projected.values())
        return projected, {
            "mode": mode,
            "target_output_power": target_power,
            "total_current_output_power": total_current,
            "allocated_output_power": allocated_total,
            "unallocated_output_power": max(float(target_power) - allocated_total, 0.0),
            "total_min_output_power": total_min_output_power,
            "total_max_output_power": total_max_output_power if known_capacity else None,
            "known_capacity": known_capacity,
            "target_exceeds_known_capacity": bool(
                known_capacity and target_power > total_max_output_power + 1e-9
            ),
            "max_output_power_delta": float(request.max_output_power_delta),
            "turbine_targets": turbine_targets,
            "clipped": clipped,
        }

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
        nhq = HydroNHQGenerator(
            design_head=turbine.design_head if turbine.design_head is not None else float(turbine.head),
            min_head=turbine.min_head if turbine.min_head is not None else max(float(turbine.head) * 0.6, 1e-6),
            max_head=turbine.max_head if turbine.max_head is not None else max(float(turbine.head) * 1.4, float(turbine.head) + 1e-6),
            design_power=turbine.design_power if turbine.design_power is not None else max(float(power_mw), 1e-6),
            min_power=turbine.min_output_power if turbine.min_output_power > 0.0 else max(float(power_mw) * 0.2, 1e-6),
            max_power=turbine.max_output_power if turbine.max_output_power is not None else max(float(power_mw) * 1.2, float(power_mw) + 1e-6),
            design_efficiency=turbine.design_efficiency if turbine.design_efficiency is not None else default_efficiency,
            eta_head_coeff=turbine.eta_head_coeff if turbine.eta_head_coeff is not None else 0.20,
            eta_power_coeff=turbine.eta_power_coeff if turbine.eta_power_coeff is not None else 0.40,
        )
        flow, _ = nhq.query(float(turbine.head), float(power_mw))
        return flow
