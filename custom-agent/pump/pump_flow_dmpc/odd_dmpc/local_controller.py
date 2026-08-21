from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .flow_service import FlowDepartService
from .station_model import PumpStationModel
from .types import ControlAction, PoolProfileState, RuntimeParameters, StationMemory, TransferBundle


@dataclass
class StationControlContext:
    station_id: int
    station_model: Optional[PumpStationModel]
    available_unit_ids: List[int]
    basin_levels: Dict[str, float]
    basin_profiles: Dict[int, PoolProfileState]
    pool_areas: Dict[int, float]
    anchor_basin_levels: Dict[str, float]
    boundary_nominal_flows: Dict[str, float]
    current_back_level: float
    current_front_level: float
    current_head: float
    upper_flow_refs: Dict[int, List[float]]
    flow_history: Dict[int, List[Tuple[float, float]]]
    boundary_level_plan: pd.DataFrame
    start_time_hours: float
    step_hours: float
    demand_plan: pd.DataFrame
    unit_blade_bounds: Dict[int, Tuple[float, float]] = field(default_factory=dict)
    max_blade_delta_per_step: float = float("inf")


class LocalController:
    def __init__(
        self,
        system_config,
        runtime: RuntimeParameters,
        flow_service: Optional[FlowDepartService] = None,
    ):
        self.system_config = system_config
        self.runtime = runtime
        self.flow_service = flow_service or FlowDepartService(
            system_config,
            config_path=system_config.source_config_path,
        )

    def hold_action(
        self, 
        station_ctx: StationControlContext, 
        transfer_bundle: TransferBundle, 
        memory: StationMemory, 
        mode: str = "ODD1"
    ) -> ControlAction:
        station_id = station_ctx.station_id
        avg_opening = self._average_opening(memory.unit_status, memory.unit_openings)
        
        active_count = max(1, sum(1 for st in memory.unit_status.values() if st == 1))
        avg_flow = float(memory.last_selected_flow) / active_count
        unit_flows = {u: (avg_flow if st == 1 else 0.0) for u, st in memory.unit_status.items()}
        
        current_head = float(transfer_bundle.reference_head[0])
        eff_dict = {}
        for u, st in memory.unit_status.items():
            if st == 1:
                try:
                    u_model = self.flow_service.get_unit_model(station_id, u)
                    eff_dict[u] = float(u_model.predict_efficiency(unit_flows[u], current_head))
                except Exception:
                    eff_dict[u] = 0.0
            else:
                eff_dict[u] = 0.0
        avg_eff = float(__import__("numpy").mean([eff for eff in eff_dict.values() if eff > 0])) if any(eff > 0 for eff in eff_dict.values()) else 0.0

        return ControlAction(
            station_id=station_id,
            mode=mode,
            selected_flow=float(memory.last_selected_flow),
            unit_status=memory.unit_status.copy(),
            unit_openings=memory.unit_openings.copy(),
            unit_flows=unit_flows,
            fit_score=0.0 if mode != "ODD1" else 1.0,
            objective=0.0,
            predicted_flow_error=0.0,
            predicted_level_error=0.0,
            predicted_back_level=float(transfer_bundle.reference_back_level[0]),
            predicted_front_level=float(transfer_bundle.reference_front_level[0]),
            predicted_head=current_head,
            predicted_openings=[avg_opening] * self.runtime.control_horizon_lower,
            predicted_efficiencies=[avg_eff] * self.runtime.control_horizon_lower,
            predicted_unit_openings={
                unit_id: [float(memory.unit_openings.get(unit_id, 0.0))] * self.runtime.control_horizon_lower
                for unit_id in memory.unit_status
            },
            predicted_unit_flows={
                unit_id: [unit_flows[unit_id]] * self.runtime.control_horizon_lower
                for unit_id in memory.unit_status
            },
            predicted_unit_status={
                unit_id: [int(memory.unit_status.get(unit_id, 0))] * self.runtime.control_horizon_lower
                for unit_id in memory.unit_status
            },
            predicted_unit_efficiencies={
                unit_id: [eff_dict[unit_id]] * self.runtime.control_horizon_lower
                for unit_id in memory.unit_status
            },
            candidate_plans=[],
        )

    def solve(
        self,
        mode: str,
        station_ctx: StationControlContext,
        upstream_prediction: Mapping[int, float],
        disturbance_forecast: Mapping[int, object],
        transfer_bundle: TransferBundle,
        station_memory: StationMemory,
    ) -> ControlAction:
        del upstream_prediction, disturbance_forecast
        if mode == "ODD1":
            return self.hold_action(station_ctx, transfer_bundle, station_memory, mode="ODD1")

        if mode == "ODD3":
            cached_action = self._solve_odd3_from_cache(
                station_ctx=station_ctx,
                transfer_bundle=transfer_bundle,
            )
            if cached_action is not None:
                return cached_action

        candidate_sets = self._candidate_active_sets(
            mode=mode,
            available_unit_ids=station_ctx.available_unit_ids,
            current_active_unit_ids=station_memory.active_unit_ids,
            station_ctx=station_ctx,
            transfer_bundle=transfer_bundle,
        )
        if not candidate_sets:
            return self.hold_action(station_ctx, transfer_bundle, station_memory, mode=mode)

        best = None
        candidate_plans = []
        for active_unit_ids in candidate_sets:
            plan = self._optimize_combo_over_horizon(
                station_ctx=station_ctx,
                transfer_bundle=transfer_bundle,
                station_memory=station_memory,
                active_unit_ids=active_unit_ids,
                mode=mode,
            )
            if plan is None:
                candidate_plans.append(
                    {
                        "active_unit_ids": list(active_unit_ids),
                        "success": False,
                        "fit_score": 0.0,
                        "objective": float("inf"),
                        "selected_flow": None,
                        "predicted_flow_error": None,
                        "normalized_flow_error": None,
                        "normalized_adjust_count": None,
                        "normalized_switch_penalty": None,
                        "unit_status": {},
                        "unit_openings": {},
                        "reason": "solve_failed",
                    }
                )
                continue
            candidate_plans.append(
                {
                    "active_unit_ids": list(active_unit_ids),
                    "success": True,
                    "fit_score": float(plan["fit_score"]),
                    "objective": float(plan["objective"]),
                    "selected_flow": float(plan["selected_flow"]),
                    "predicted_flow_error": float(plan["predicted_flow_error"]),
                    "normalized_flow_error": float(plan.get("normalized_flow_error", 0.0)),
                    "normalized_adjust_count": float(plan.get("normalized_adjust_count", 0.0)),
                    "normalized_switch_penalty": float(plan.get("normalized_switch_penalty", 0.0)),
                    "unit_status": plan["unit_status"].copy(),
                    "unit_openings": plan["unit_openings"].copy(),
                    "reason": "ok",
                }
            )
            if best is None or float(plan["fit_score"]) > float(best["fit_score"]):
                best = plan

        if best is None:
            action = self.hold_action(station_ctx, transfer_bundle, station_memory, mode=mode)
            action.candidate_plans = candidate_plans
            return action

        return ControlAction(
            station_id=station_ctx.station_id,
            mode=mode,
            selected_flow=float(best["selected_flow"]),
            unit_status=best["unit_status"].copy(),
            unit_openings=best["unit_openings"].copy(),
            unit_flows=best["unit_flows"].copy(),
            fit_score=float(best["fit_score"]),
            objective=float(best["objective"]),
            predicted_flow_error=float(best["predicted_flow_error"]),
            predicted_level_error=float(best["predicted_level_error"]),
            predicted_back_level=float(best["predicted_back_level"]),
            predicted_front_level=float(best["predicted_front_level"]),
            predicted_head=float(best["predicted_head"]),
            predicted_openings=list(best["predicted_openings"]),
            predicted_efficiencies=list(best["predicted_efficiencies"]),
            predicted_unit_openings={unit_id: list(values) for unit_id, values in best["predicted_unit_openings"].items()},
            predicted_unit_flows={unit_id: list(values) for unit_id, values in best["predicted_unit_flows"].items()},
            predicted_unit_status={unit_id: list(values) for unit_id, values in best["predicted_unit_status"].items()},
            predicted_unit_efficiencies={unit_id: list(values) for unit_id, values in best["predicted_unit_efficiencies"].items()},
            candidate_plans=candidate_plans,
        )

    def _candidate_active_sets(
        self,
        mode: str,
        available_unit_ids: List[int],
        current_active_unit_ids: List[int],
        station_ctx: Optional[StationControlContext] = None,
        transfer_bundle: Optional[TransferBundle] = None,
    ) -> List[List[int]]:
        available_ids = sorted(int(unit_id) for unit_id in available_unit_ids)
        available_set = set(available_ids)
        current_active = sorted(unit_id for unit_id in current_active_unit_ids if unit_id in available_set)
        if mode == "ODD2":
            return [current_active] if current_active else []
        candidate_sets = [
            list(combo)
            for size in range(1, len(available_ids) + 1)
            for combo in combinations(available_ids, size)
        ]
        screened = self._screen_candidates_by_flow_head(
            candidate_sets,
            station_ctx=station_ctx,
            transfer_bundle=transfer_bundle,
        )
        return screened if screened else candidate_sets

    def _screen_candidates_by_flow_head(
        self,
        candidate_sets: List[List[int]],
        *,
        station_ctx: Optional[StationControlContext],
        transfer_bundle: Optional[TransferBundle],
    ) -> List[List[int]]:
        """跳过无法命中目标流量/扬程范围的机组组合，减少在线 NLP 次数。

        仅在能够取得目标规划（流量/扬程序列）时启用；筛选结果为空时由调用方
        回退到全量组合，保留原来的 best-effort 行为。
        """
        if (
            station_ctx is None
            or transfer_bundle is None
            or not transfer_bundle.reference_flow
            or not transfer_bundle.reference_head
        ):
            return candidate_sets

        horizon = min(
            self.runtime.control_horizon_lower,
            len(transfer_bundle.reference_flow),
            len(transfer_bundle.reference_head),
        )
        if horizon <= 0:
            return candidate_sets

        unit_models = {
            unit_id: self.flow_service.get_unit_model(station_ctx.station_id, unit_id)
            for unit_id in station_ctx.available_unit_ids
        }

        flow_plan = transfer_bundle.reference_flow
        head_plan = transfer_bundle.reference_head
        screened: List[List[int]] = []
        for combo in candidate_sets:
            if self._combo_can_track_plan(
                combo,
                unit_models=unit_models,
                flow_plan=flow_plan,
                head_plan=head_plan,
                horizon=horizon,
            ):
                screened.append(combo)
        return screened

    @staticmethod
    def _combo_can_track_plan(
        combo: List[int],
        *,
        unit_models,
        flow_plan: list,
        head_plan: list,
        horizon: int,
    ) -> bool:
        eps = 1e-9
        for step in range(horizon):
            target_flow = float(flow_plan[step])
            head = float(head_plan[step])
            if not np.isfinite(target_flow) or not np.isfinite(head):
                return False
            sum_q_min = 0.0
            sum_q_max = 0.0
            for unit_id in combo:
                unit = unit_models[unit_id]
                if not (float(unit.h_min) <= head <= float(unit.h_max)):
                    return False
                sum_q_min += float(unit.q_min)
                sum_q_max += float(unit.q_max)
            if not (sum_q_min - eps <= target_flow <= sum_q_max + eps):
                return False
        return True

    def _solve_odd3_from_cache(
        self,
        station_ctx: StationControlContext,
        transfer_bundle: TransferBundle,
    ) -> Optional[ControlAction]:
        """ODD3 优先复用离线最优流量分配表，跳过全组合在线 NLP。

        返回 ControlAction 表示命中缓存候选；返回 None 表示离线表或候选不可用，
        由调用方回退到在线机组组合 NLP 路径。
        """
        station_model = station_ctx.station_model
        if station_model is None:
            return None

        horizon = min(
            self.runtime.control_horizon_lower,
            len(transfer_bundle.reference_flow),
            len(transfer_bundle.reference_head),
        )
        available_ids = [int(unit_id) for unit_id in station_ctx.available_unit_ids]
        if horizon <= 0 or not available_ids:
            return None

        selected_rows = []
        for step in range(horizon):
            target_flow = float(transfer_bundle.reference_flow[step])
            head = float(transfer_bundle.reference_head[step])
            row = self._best_cached_row(
                station_model=station_model,
                target_flow=target_flow,
                head=head,
                available_unit_ids=available_ids,
            )
            if row is None:
                return None
            selected_rows.append(row)

        step0_row = selected_rows[0]
        step0_status = {
            unit_id: int(step0_row.unit_status.get(unit_id, 0))
            for unit_id in available_ids
        }
        step0_openings = {
            unit_id: float(step0_row.unit_openings.get(unit_id, 0.0))
            for unit_id in available_ids
        }
        step0_flows = {
            unit_id: float(step0_row.unit_flows.get(unit_id, 0.0))
            for unit_id in available_ids
        }

        normalized_flow_errors = []
        predicted_openings = []
        predicted_efficiencies = []
        predicted_unit_openings = {unit_id: [] for unit_id in available_ids}
        predicted_unit_flows = {unit_id: [] for unit_id in available_ids}
        predicted_unit_status = {unit_id: [] for unit_id in available_ids}
        predicted_unit_efficiencies = {unit_id: [] for unit_id in available_ids}

        for step, row in enumerate(selected_rows):
            target_flow = float(transfer_bundle.reference_flow[step])
            normalized_flow_errors.append(
                abs(float(row.flow) - target_flow) / max(abs(target_flow), 1.0)
            )
            active_ids = [
                unit_id
                for unit_id in available_ids
                if int(row.unit_status.get(unit_id, 0)) == 1
            ]
            if active_ids:
                predicted_openings.append(
                    float(np.mean([
                        float(row.unit_openings.get(unit_id, 0.0))
                        for unit_id in active_ids
                    ]))
                )
            else:
                predicted_openings.append(0.0)
            predicted_efficiencies.append(float(row.efficiency))
            for unit_id in available_ids:
                predicted_unit_openings[unit_id].append(
                    float(row.unit_openings.get(unit_id, 0.0))
                )
                predicted_unit_flows[unit_id].append(
                    float(row.unit_flows.get(unit_id, 0.0))
                )
                predicted_unit_status[unit_id].append(
                    int(row.unit_status.get(unit_id, 0))
                )
                flow_u = float(row.unit_flows.get(unit_id, 0.0))
                head_step = float(transfer_bundle.reference_head[step])
                eff_u = (
                    float(self.flow_service.get_unit_model(
                        station_ctx.station_id, unit_id
                    ).predict_efficiency(flow_u, head_step))
                    if flow_u > 0
                    else 0.0
                )
                predicted_unit_efficiencies[unit_id].append(eff_u)

        mean_flow_error = float(np.mean(normalized_flow_errors)) if normalized_flow_errors else 0.0
        first_step_flow_error = abs(
            float(step0_row.flow) - float(transfer_bundle.reference_flow[0])
        )
        objective = self._weighted_normalized_objective(
            flow_error=mean_flow_error,
            adjust_count=0.0,
            switch_penalty=0.0,
        )
        candidate_plans = self._odd3_candidate_plans(
            station_model=station_model,
            target_flow=float(transfer_bundle.reference_flow[0]),
            head=float(transfer_bundle.reference_head[0]),
            available_unit_ids=available_ids,
        )

        return ControlAction(
            station_id=station_ctx.station_id,
            mode="ODD3",
            selected_flow=float(step0_row.flow),
            unit_status=step0_status,
            unit_openings=step0_openings,
            unit_flows=step0_flows,
            fit_score=float(np.exp(-objective)),
            objective=float(objective),
            predicted_flow_error=float(first_step_flow_error),
            predicted_level_error=0.0,
            predicted_back_level=float(transfer_bundle.reference_back_level[0]),
            predicted_front_level=float(transfer_bundle.reference_front_level[0]),
            predicted_head=float(transfer_bundle.reference_head[0]),
            predicted_openings=predicted_openings,
            predicted_efficiencies=predicted_efficiencies,
            predicted_unit_openings=predicted_unit_openings,
            predicted_unit_flows=predicted_unit_flows,
            predicted_unit_status=predicted_unit_status,
            predicted_unit_efficiencies=predicted_unit_efficiencies,
            candidate_plans=candidate_plans,
        )

    def _best_cached_row(
        self,
        station_model,
        target_flow: float,
        head: float,
        available_unit_ids: List[int],
    ):
        row = station_model.best_row_for_target(
            target_flow=target_flow,
            head=head,
            available_unit_ids=available_unit_ids,
            tolerance=getattr(self.runtime, "head_search_tolerance", 0.35),
        )
        if row is not None:
            return row
        fallback_candidates = station_model.candidate_rows(
            head=head,
            available_unit_ids=available_unit_ids,
            tolerance=1.0e9,
        )
        if not fallback_candidates:
            return None
        return min(
            fallback_candidates,
            key=lambda item: (
                abs(item.flow - target_flow),
                abs(item.head - head),
                -item.efficiency,
            ),
        )

    def _odd3_candidate_plans(
        self,
        station_model,
        target_flow: float,
        head: float,
        available_unit_ids: List[int],
    ) -> List[Dict[str, object]]:
        candidates = station_model.candidate_rows(
            head=head,
            available_unit_ids=available_unit_ids,
            tolerance=getattr(self.runtime, "head_search_tolerance", 0.35),
        )
        if not candidates:
            candidates = station_model.candidate_rows(
                head=head,
                available_unit_ids=available_unit_ids,
                tolerance=1.0e9,
            )
        ordered_candidates = sorted(
            candidates,
            key=lambda item: (
                abs(item.flow - target_flow),
                abs(item.head - head),
                -item.efficiency,
            ),
        )
        candidate_plans: List[Dict[str, object]] = []
        for row in ordered_candidates:
            active_ids = [
                unit_id
                for unit_id in available_unit_ids
                if int(row.unit_status.get(unit_id, 0)) == 1
            ]
            flow_error = abs(float(row.flow) - target_flow)
            normalized_flow_error = flow_error / max(abs(target_flow), 1.0)
            candidate_plans.append(
                {
                    "active_unit_ids": active_ids,
                    "success": True,
                    "fit_score": float(np.exp(-normalized_flow_error)),
                    "objective": float(normalized_flow_error),
                    "selected_flow": float(row.flow),
                    "predicted_flow_error": float(flow_error),
                    "normalized_flow_error": float(normalized_flow_error),
                    "normalized_level_error": 0.0,
                    "normalized_adjust_count": 0.0,
                    "normalized_switch_penalty": 0.0,
                    "unit_status": {
                        unit_id: int(row.unit_status.get(unit_id, 0))
                        for unit_id in available_unit_ids
                    },
                    "unit_openings": {
                        unit_id: float(row.unit_openings.get(unit_id, 0.0))
                        for unit_id in available_unit_ids
                    },
                    "reason": "cache_row",
                }
            )
        return candidate_plans

    def _optimize_combo_over_horizon(
        self,
        station_ctx: StationControlContext,
        transfer_bundle: TransferBundle,
        station_memory: StationMemory,
        active_unit_ids: List[int],
        mode: str,
    ) -> Optional[Dict[str, object]]:
        horizon = min(self.runtime.control_horizon_lower, len(transfer_bundle.reference_flow))
        available_ids = [int(unit_id) for unit_id in station_ctx.available_unit_ids]
        active_ids = [int(unit_id) for unit_id in active_unit_ids]

        if not active_ids:
            return None

        unit_models = {
            unit_id: self.flow_service.get_unit_model(station_ctx.station_id, unit_id)
            for unit_id in active_ids
        }
        previous_openings = {
            unit_id: float(station_memory.unit_openings.get(unit_id, (unit_models[unit_id].angle_min + unit_models[unit_id].angle_max) / 2.0))
            for unit_id in active_ids
        }

        step_openings: List[Dict[int, float]] = []
        step_unit_flows: List[Dict[int, float]] = []
        step_unit_status: List[Dict[int, int]] = []
        step_total_flows: List[float] = []
        step_avg_openings: List[float] = []
        step_avg_efficiencies: List[float] = []
        step_unit_efficiencies: List[Dict[int, float]] = []

        for step in range(horizon):
            target_flow = float(transfer_bundle.reference_flow[step])
            head = float(transfer_bundle.reference_head[step])
            optimized = self._optimize_single_step(
                active_unit_ids=active_ids,
                unit_models=unit_models,
                head=head,
                target_flow=target_flow,
                initial_openings=previous_openings,
                blade_angle_bounds=getattr(station_ctx, "unit_blade_bounds", {}),
                max_opening_delta=float(station_ctx.max_blade_delta_per_step),
            )
            if optimized is None:
                return None
            step_openings.append(optimized["openings"])
            step_unit_flows.append(optimized["unit_flows"])
            step_unit_status.append({unit_id: 1 if unit_id in active_ids else 0 for unit_id in available_ids})
            step_total_flows.append(float(optimized["total_flow"]))
            step_avg_openings.append(float(np.mean([optimized["openings"][unit_id] for unit_id in active_ids])))
            step_avg_efficiencies.append(float(optimized["avg_efficiency"]))
            step_unit_efficiencies.append(optimized["unit_efficiencies"])
            previous_openings = optimized["openings"]

        step0_openings = {unit_id: 0.0 for unit_id in available_ids}
        step0_status = {unit_id: 0 for unit_id in available_ids}
        step0_flows = {unit_id: 0.0 for unit_id in available_ids}
        for unit_id in active_ids:
            step0_openings[unit_id] = float(step_openings[0][unit_id])
            step0_status[unit_id] = 1
            step0_flows[unit_id] = float(step_unit_flows[0][unit_id])
        predicted_unit_openings = {unit_id: [] for unit_id in available_ids}
        predicted_unit_flows = {unit_id: [] for unit_id in available_ids}
        predicted_unit_status = {unit_id: [] for unit_id in available_ids}
        predicted_unit_efficiencies = {unit_id: [] for unit_id in available_ids}
        for step in range(horizon):
            for unit_id in available_ids:
                predicted_unit_openings[unit_id].append(float(step_openings[step].get(unit_id, 0.0)))
                predicted_unit_flows[unit_id].append(float(step_unit_flows[step].get(unit_id, 0.0)))
                predicted_unit_status[unit_id].append(int(step_unit_status[step].get(unit_id, 0)))
                predicted_unit_efficiencies[unit_id].append(float(step_unit_efficiencies[step].get(unit_id, 0.0)))

        normalized_flow_errors = []
        for step in range(horizon):
            target_flow = float(transfer_bundle.reference_flow[step])
            actual_flow = float(step_total_flows[step])
            normalized_flow_errors.append(abs(actual_flow - target_flow) / max(abs(target_flow), 1.0))
        mean_flow_error = float(np.mean(normalized_flow_errors)) if normalized_flow_errors else 0.0
        first_step_flow_error = abs(step_total_flows[0] - float(transfer_bundle.reference_flow[0]))
        adjust_count = 0
        switch_penalty = 0.0

        for unit_id in available_ids:
            current_open = float(station_memory.unit_openings.get(unit_id, 0.0))
            new_open = float(step0_openings.get(unit_id, 0.0))
            open_delta = abs(new_open - current_open)
            switch_age = float(station_memory.time_since_switch.get(unit_id, 0))
            if open_delta > 0.0:
                adjust_count += 1

            current_status = int(station_memory.unit_status.get(unit_id, 0))
            new_status = int(step0_status.get(unit_id, 0))
            if current_status != new_status:
                switch_penalty += 1.0 / (1.0 + switch_age)

        normalized_adjust_count = adjust_count / max(len(available_ids), 1)
        normalized_switch_penalty = switch_penalty / max(len(available_ids), 1)
        objective = self._weighted_normalized_objective(
            flow_error=mean_flow_error,
            adjust_count=normalized_adjust_count,
            switch_penalty=normalized_switch_penalty,
        )
        fit_score = float(np.exp(-objective))

        return {
            "selected_flow": float(step_total_flows[0]),
            "unit_status": step0_status,
            "unit_openings": step0_openings,
            "unit_flows": step0_flows,
            "fit_score": fit_score,
            "objective": float(objective),
            "predicted_flow_error": float(first_step_flow_error),
            "predicted_level_error": 0.0,
            "normalized_flow_error": float(mean_flow_error),
            "normalized_adjust_count": float(normalized_adjust_count),
            "normalized_switch_penalty": float(normalized_switch_penalty),
            "predicted_back_level": float(transfer_bundle.reference_back_level[0]),
            "predicted_front_level": float(transfer_bundle.reference_front_level[0]),
            "predicted_head": float(transfer_bundle.reference_head[0]),
            "predicted_openings": step_avg_openings,
            "predicted_efficiencies": step_avg_efficiencies,
            "predicted_unit_openings": predicted_unit_openings,
            "predicted_unit_flows": predicted_unit_flows,
            "predicted_unit_status": predicted_unit_status,
            "predicted_unit_efficiencies": predicted_unit_efficiencies,
        }

    def _weighted_normalized_objective(
        self,
        flow_error: float,
        adjust_count: float,
        switch_penalty: float,
    ) -> float:
        weights = {
            "flow": max(float(self.runtime.lower_flow_weight), 0.0),
            "adjust": max(float(self.runtime.lower_adjust_count_weight), 0.0),
            "switch": max(float(self.runtime.lower_switch_weight), 0.0),
        }
        weight_sum = float(sum(weights.values()))
        if weight_sum <= 0.0:
            return 0.0
        normalized_weights = {key: value / weight_sum for key, value in weights.items()}
        return float(
            normalized_weights["flow"] * max(float(flow_error), 0.0)
            + normalized_weights["adjust"] * max(float(adjust_count), 0.0)
            + normalized_weights["switch"] * max(float(switch_penalty), 0.0)
        )

    def _optimize_single_step(
        self,
        active_unit_ids: List[int],
        unit_models,
        head: float,
        target_flow: float,
        initial_openings: Mapping[int, float],
        blade_angle_bounds: Optional[Mapping[int, Tuple[float, float]]] = None,
        max_opening_delta: float = float("inf"),
    ) -> Optional[Dict[str, object]]:
        if not active_unit_ids:
            return None

        bounds_min = []
        bounds_max = []
        r0 = []
        for unit_id in active_unit_ids:
            unit = unit_models[unit_id]
            if not np.isfinite(head) or not (float(unit.h_min) <= head <= float(unit.h_max)):
                return None
            actuator_min, actuator_max = (blade_angle_bounds or {}).get(
                unit_id,
                (float(unit.angle_min), float(unit.angle_max)),
            )
            if (
                not np.isfinite(actuator_min)
                or not np.isfinite(actuator_max)
                or float(actuator_min) > float(actuator_max)
            ):
                return None
            guess = float(initial_openings.get(unit_id, 0.5 * (unit.angle_min + unit.angle_max)))
            lower_bound = max(float(unit.angle_min), float(actuator_min), guess - max_opening_delta)
            upper_bound = min(float(unit.angle_max), float(actuator_max), guess + max_opening_delta)
            if lower_bound > upper_bound:
                return None
            bounds_min.append(lower_bound)
            bounds_max.append(upper_bound)
            r0.append(float(np.clip(guess, lower_bound, upper_bound)))

        def residual(r_array):
            total_flow = 0.0
            for unit_id, opening in zip(active_unit_ids, r_array):
                unit = unit_models[unit_id]
                predicted_flow = unit.predict_flow(
                    blade_angle=float(opening),
                    water_head=head,
                )
                if (
                    not np.isfinite(predicted_flow)
                    or not (float(unit.q_min) <= float(predicted_flow) <= float(unit.q_max))
                    or not unit.is_feasible(float(predicted_flow), head)
                ):
                    return np.asarray([1.0e6], dtype=float)
                total_flow += float(predicted_flow)
            return np.asarray([total_flow - target_flow], dtype=float)

        result = least_squares(
            residual,
            x0=np.asarray(r0, dtype=float),
            bounds=(np.asarray(bounds_min, dtype=float), np.asarray(bounds_max, dtype=float)),
            method="trf",
        )
        if not result.success or result.x is None or len(result.x) != len(active_unit_ids):
            return None

        openings: Dict[int, float] = {}
        unit_flows: Dict[int, float] = {}
        unit_efficiencies: Dict[int, float] = {}
        efficiencies: List[float] = []
        total_flow = 0.0
        for unit_id, opening in zip(active_unit_ids, result.x):
            opening_value = float(opening)
            unit = unit_models[unit_id]
            predicted_flow = unit.predict_flow(
                blade_angle=opening_value,
                water_head=head,
            )
            if (
                not np.isfinite(predicted_flow)
                or not (float(unit.q_min) <= float(predicted_flow) <= float(unit.q_max))
                or not unit.is_feasible(float(predicted_flow), head)
            ):
                return None
            flow_value = float(predicted_flow)
            openings[unit_id] = opening_value
            unit_flows[unit_id] = flow_value
            eff = float(unit.predict_efficiency(flow_value, head))
            if not np.isfinite(eff):
                return None
            efficiencies.append(eff)
            unit_efficiencies[unit_id] = eff
            total_flow += flow_value

        avg_efficiency = float(np.mean(efficiencies)) if efficiencies else 0.0
        return {
            "openings": openings,
            "unit_flows": unit_flows,
            "unit_efficiencies": unit_efficiencies,
            "total_flow": float(total_flow),
            "avg_efficiency": avg_efficiency,
        }

    def _average_opening(self, unit_status: Mapping[int, int], unit_openings: Mapping[int, float]) -> float:
        active_openings = [
            float(unit_openings.get(unit_id, 0.0))
            for unit_id, status in unit_status.items()
            if int(status) == 1
        ]
        if not active_openings:
            return 0.0
        return float(np.mean(active_openings))


def build_initial_station_memory(
    station_id: int,
    station_model: PumpStationModel,
    initial_flow: float,
    initial_head: float,
    available_unit_ids: List[int],
    runtime: RuntimeParameters,
) -> StationMemory:
    row = station_model.best_row_for_target(
        target_flow=initial_flow,
        head=initial_head,
        available_unit_ids=available_unit_ids,
        tolerance=runtime.head_search_tolerance,
    )
    if row is None:
        unit_status = {unit_id: 0 for unit_id in available_unit_ids}
        unit_openings = {unit_id: 0.0 for unit_id in available_unit_ids}
        active_unit_ids: List[int] = []
    else:
        unit_status = row.unit_status.copy()
        unit_openings = row.unit_openings.copy()
        active_unit_ids = [unit_id for unit_id, status in row.unit_status.items() if status == 1]

    return StationMemory(
        active_unit_ids=active_unit_ids,
        unit_openings=unit_openings,
        unit_status=unit_status,
        time_since_adjust={unit_id: runtime.station_memory_init_age for unit_id in available_unit_ids},
        time_since_switch={unit_id: runtime.station_memory_init_age for unit_id in available_unit_ids},
        last_selected_flow=float(initial_flow),
        mode="ODD1",
    )
