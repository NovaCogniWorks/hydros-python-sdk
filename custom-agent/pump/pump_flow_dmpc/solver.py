"""不依赖 transport 或设备执行的泵站局部流量分配 solver。"""

from __future__ import annotations

import math
from typing import Dict, Iterable, Mapping

from .errors import PumpFlowDmpcError
from .performance import PumpPerformanceRepository
from .types import PumpFlowDmpcArguments, PumpFlowDmpcDecision, PumpUnitState


class PumpFlowDmpcSolver:
    """以坐标下降搜索分配固定运行机组的下一步叶片角度。

    这是 Python-only MVP 的局部滚动优化器：每次只给出一个可执行控制步，
    不承担多站协调、机组启停或任何设备写入行为。
    """

    def __init__(self, performance: PumpPerformanceRepository) -> None:
        self._performance = performance

    def solve(self, arguments: PumpFlowDmpcArguments) -> PumpFlowDmpcDecision:
        if abs(arguments.current_flow - arguments.target_flow) <= arguments.flow_tolerance:
            return PumpFlowDmpcDecision(
                station_id=arguments.station_id,
                blade_angles={},
                predicted_station_flow=arguments.current_flow,
                objective=0.0,
                completed=True,
                reason="FLOW_TARGET_REACHED",
            )

        angles = {
            unit.unit_id: self._bounded_current_angle(unit, arguments)
            for unit in arguments.units
        }
        best_objective = self._objective(arguments, angles)
        for _ in range(arguments.max_solver_iterations):
            improved = False
            for unit in arguments.units:
                candidate_angles = self._candidate_angles(unit, arguments)
                selected_angle = angles[unit.unit_id]
                selected_objective = best_objective
                for candidate_angle in candidate_angles:
                    candidate = dict(angles)
                    candidate[unit.unit_id] = candidate_angle
                    objective = self._objective(arguments, candidate)
                    if objective + 1e-12 < selected_objective:
                        selected_angle = candidate_angle
                        selected_objective = objective
                if selected_angle != angles[unit.unit_id]:
                    angles[unit.unit_id] = selected_angle
                    best_objective = selected_objective
                    improved = True
            if not improved:
                break

        predicted_flow = self._predicted_station_flow(arguments, angles)
        return PumpFlowDmpcDecision(
            station_id=arguments.station_id,
            blade_angles=angles,
            predicted_station_flow=predicted_flow,
            objective=best_objective,
            completed=False,
            reason="FLOW_TRACKING_ACTION",
        )

    def _objective(
        self,
        arguments: PumpFlowDmpcArguments,
        angles: Mapping[int, float],
    ) -> float:
        predicted_flow = self._predicted_station_flow(arguments, angles)
        flow_error = predicted_flow - arguments.target_flow
        movement_penalty = sum(
            (angles[unit.unit_id] - unit.current_blade_angle) ** 2
            for unit in arguments.units
        )
        objective = flow_error**2 + arguments.movement_weight * movement_penalty
        if not math.isfinite(objective):
            raise PumpFlowDmpcError(
                "NON_FINITE_SOLVER_OUTPUT",
                "pump flow objective must be finite",
            )
        return objective

    def _predicted_station_flow(
        self,
        arguments: PumpFlowDmpcArguments,
        angles: Mapping[int, float],
    ) -> float:
        predicted = sum(
            self._performance.predict_unit_flow(
                station_id=arguments.station_id,
                unit_id=unit.unit_id,
                blade_angle=angles[unit.unit_id],
                water_head=arguments.water_head,
            )
            for unit in arguments.units
        )
        if not math.isfinite(predicted):
            raise PumpFlowDmpcError(
                "NON_FINITE_SOLVER_OUTPUT",
                "predicted station flow must be finite",
            )
        return predicted

    @staticmethod
    def _bounded_current_angle(
        unit: PumpUnitState,
        arguments: PumpFlowDmpcArguments,
    ) -> float:
        lower, upper = PumpFlowDmpcSolver._adjustable_range(unit, arguments)
        return min(max(unit.current_blade_angle, lower), upper)

    @staticmethod
    def _candidate_angles(
        unit: PumpUnitState,
        arguments: PumpFlowDmpcArguments,
    ) -> Iterable[float]:
        lower, upper = PumpFlowDmpcSolver._adjustable_range(unit, arguments)
        step = arguments.candidate_angle_step
        count = int(math.floor((upper - lower) / step))
        candidates = [lower + index * step for index in range(count + 1)]
        if not candidates or abs(candidates[-1] - upper) > 1e-12:
            candidates.append(upper)
        current = min(max(unit.current_blade_angle, lower), upper)
        if all(abs(value - current) > 1e-12 for value in candidates):
            candidates.append(current)
        return tuple(sorted(set(candidates)))

    @staticmethod
    def _adjustable_range(
        unit: PumpUnitState,
        arguments: PumpFlowDmpcArguments,
    ) -> tuple[float, float]:
        lower = max(
            unit.min_blade_angle,
            unit.current_blade_angle - arguments.max_blade_delta_per_step,
        )
        upper = min(
            unit.max_blade_angle,
            unit.current_blade_angle + arguments.max_blade_delta_per_step,
        )
        if lower > upper:
            raise PumpFlowDmpcError(
                "INVALID_BLADE_ANGLE_RANGE",
                "pump unit %s has no adjustable blade-angle range" % unit.unit_id,
            )
        return lower, upper
