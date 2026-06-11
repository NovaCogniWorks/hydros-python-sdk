from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from .environment import (
    basin_level_targets,
    disturbance_value_at_step,
    simulate_basin_trajectory,
    _chain_pairs,
    _level_keys,
    _ordered_station_ids,
)
from .flow_service import FlowDepartService
from .station_model import PumpStationModel
from .types import AvailableUnitsMap, LowerFeedback, RuntimeParameters, SystemConfig, UpperPlan


@dataclass
class UpperScheduler:
    system_config: SystemConfig
    demand_plan: pd.DataFrame
    runtime: RuntimeParameters
    flow_service: FlowDepartService
    boundary_level_plan: pd.DataFrame

    def _build_station_models(self, available_units_map: AvailableUnitsMap) -> Dict[int, PumpStationModel]:
        models = {}
        for station in self.system_config.stations:
            available_ids = available_units_map.get(station.id, [unit.id for unit in station.units])
            models[station.id] = self.flow_service.get_station_model(station.id, available_ids)
        return models

    def _target_remaining_flow(self, demand_state: Mapping[str, float], horizon: int) -> float:
        delivered = float(demand_state.get("delivered_last_station_total", 0.0))
        total_target_volume = self.system_config.target_avg_flow_last_station * self.system_config.horizon_hours
        if horizon <= 0:
            return self.system_config.target_avg_flow_last_station
        remaining_average = max((total_target_volume - delivered) / horizon, 0.0)
        return float(remaining_average)

    def _level_correction(self, target_level: float, current_level: float, area: float) -> float:
        gain = self.runtime.upper_level_correction_gain
        return gain * (target_level - current_level) * area / 3600.0

    def _apply_flow_bias_correction(
        self,
        station_id: int,
        commanded_flow: float,
        lower_feedback: LowerFeedback,
    ) -> float:
        gain = float(self.runtime.upper_flow_bias_correction_gain)
        bias = float(lower_feedback.plan_execution_errors.get(station_id, 0.0))
        return float(commanded_flow + gain * bias)

    def _startup_effective_flow(
        self,
        step: int,
        station_id: int,
        fallback_flow: float,
        env_snapshot,
    ) -> float:
        if step == 0:
            return float(env_snapshot.station_flows.get(station_id, fallback_flow))
        return float(fallback_flow)

    def _apply_state_feedback_correction(
        self,
        measured_levels: Mapping[str, float],
        lower_feedback: LowerFeedback,
    ) -> Dict[str, float]:
        del lower_feedback
        return {key: float(value) for key, value in measured_levels.items()}

    def _pick_row(self, model: PumpStationModel, target_flow: float, head: float) -> Tuple[float, float]:
        row = model.best_row_for_target(
            target_flow=target_flow,
            head=head,
            tolerance=self.runtime.head_search_tolerance,
        )
        if row is not None:
            return float(row.flow), float(row.efficiency)

        projected_flow = model.project_flow_to_feasible(
            head=head,
            target_flow=target_flow,
            tolerance=self.runtime.head_search_tolerance,
        )
        if projected_flow is not None:
            projected_efficiency = model.interpolate_efficiency(
                head=head,
                flow=projected_flow,
                tolerance=self.runtime.head_search_tolerance,
            )
            return float(projected_flow), float(projected_efficiency or 0.0)

        fallback_row = model.best_row_for_target(
            target_flow=target_flow,
            head=head,
            tolerance=1.0e9,
        )
        if fallback_row is not None:
            return float(fallback_row.flow), float(fallback_row.efficiency)

        flow_min, flow_max = model.global_feasible_flow_range()
        return float(np.clip(target_flow, flow_min, flow_max)), 0.0

    def _solve_global_nlp(
        self,
        now: int,
        horizon: int,
        station_ids: List[int],
        station_models: Dict[int, PumpStationModel],
        chain_pairs: List[Dict[str, object]],
        targets: Dict[str, float],
        current_levels: Dict[str, float],
        level_keys: List[str],
        env_snapshot,
        demand_state: Mapping[str, float],
        disturbance_forecast: Mapping[int, object],
        target_avg: float,
        feasible_flow_overrides: Optional[Dict[int, List[float]]] = None,
    ) -> np.ndarray:
        from scipy.optimize import minimize
        N = len(station_ids)
        T = horizon

        areas = np.zeros(len(chain_pairs))
        for idx, pair in enumerate(chain_pairs):
            pool_id = int(pair["pool_id"])
            areas[idx] = float(env_snapshot.pool_areas.get(pool_id, 1.0))
        c_p = 3600.0 / areas
        
        L0 = np.array([float(current_levels[k]) for k in level_keys])
        
        # 预先根据初始扬程计算每个站的缓存表可行流量范围
        # 扬程 = 站后水位 - 站前水位（level_keys 中 index+1 是站后，index 是站前）
        head_tol = float(self.runtime.head_search_tolerance)
        head_based_bounds: Dict[int, Tuple[float, float]] = {}
        for idx, s_id in enumerate(station_ids):
            if idx < N - 1:
                head_key_index = idx + 1
            else:
                head_key_index = min(idx, len(level_keys) - 1)
            h_est = float(L0[head_key_index] - L0[head_key_index - 1])
            q_lo, q_hi = station_models[s_id].feasible_flow_range(
                head=h_est, tolerance=head_tol
            )
            if q_lo >= q_hi:  # 该扬程下无缓存行，退化为全局范围
                q_lo, q_hi = station_models[s_id].global_feasible_flow_range()
            head_based_bounds[s_id] = (q_lo, q_hi)

        bounds = []
        for t in range(T):
            for s_id in station_ids:
                if feasible_flow_overrides and s_id in feasible_flow_overrides:
                    override = feasible_flow_overrides[s_id]
                    q_min, q_max = float(override[0]), float(override[1])
                else:
                    q_min, q_max = head_based_bounds.get(s_id, (0.0, 0.0))
                # 避免出现 q_min > q_max 的异常
                if q_min > q_max:
                    q_min, q_max = q_max, q_min
                bounds.append((q_min, q_max))
                
        last_station_idx = N - 1

        # 预先提取各个水池在 T 个时段的需求和扰动
        demands_mat = np.zeros((T, N-1))
        dists_mat = np.zeros((T, N-1))
        target_levels = np.zeros(N-1)
        
        for t in range(T):
            demand_row = self.demand_plan.iloc[min(now + t, len(self.demand_plan) - 1)]
            for idx, pair in enumerate(chain_pairs):
                pool_id = int(pair["pool_id"])
                demands_mat[t, idx] = float(demand_row.get(str(pair["demand_column"]), 0.0))
                dists_mat[t, idx] = float(disturbance_value_at_step(disturbance_forecast, pool_id, t))
                if t == 0:
                    target_levels[idx] = float(targets.get(str(pair["back_level_key"]), L0[idx+1]))

        def get_states_vectorized(x):
            Q = x.reshape((T, N))
            delta_Q = Q[:, :-1] - Q[:, 1:] # (T, N-1)
            net_flow = delta_Q + demands_mat + dists_mat
            delta_L = net_flow * c_p # 广播机制
            L_inner = np.cumsum(delta_L, axis=0) + L0[1:-1]
            
            L = np.zeros((T + 1, N + 1))
            L[0] = L0
            L[1:, 1:-1] = L_inner
            L[:, 0] = L0[0]
            L[:, -1] = L0[-1]
            return Q, L

        def objective(x):
            Q, L = get_states_vectorized(x)
            total_eff = 0.0
            penalty = 0.0
            heads = L[:-1, 1:] - L[:-1, :-1] # (T, N)
            
            for idx, s_id in enumerate(station_ids):
                h_array = heads[:, idx]
                q_array = Q[:, idx]
                q_lo_hb, q_hi_hb = head_based_bounds.get(s_id, (0.0, float("inf")))
                
                if station_models[s_id].eff_interp is not None:
                    pts = np.column_stack((h_array, q_array))
                    vals = station_models[s_id].eff_interp(pts)
                    valid = vals >= 0
                    total_eff += np.sum(vals[valid])
                    
                    invalid = ~valid
                    if np.any(invalid):
                        h_vals = station_models[s_id].h_vals
                        if h_vals is not None and len(h_vals) > 0:
                            h_min_v, h_max_v = float(h_vals[0]), float(h_vals[-1])
                            h_inv = h_array[invalid]
                            # 扬程越界惩罚
                            penalty += np.sum(np.maximum(h_min_v - h_inv, 0)) * 100.0
                            penalty += np.sum(np.maximum(h_inv - h_max_v, 0)) * 100.0
                        # 流量越界惩罚（对不在缓存表扬程切片内的点施加额外惩罚）
                        q_inv = q_array[invalid]
                        penalty += np.sum(np.maximum(q_lo_hb - q_inv, 0)) * 80.0
                        penalty += np.sum(np.maximum(q_inv - q_hi_hb, 0)) * 80.0

            # 水位惩罚项，整体计算平方差
            level_diff = L[1:, 1:-1] - target_levels
            penalty += np.sum(5.0 * level_diff**2)
            
            return -total_eff + penalty

        def constraint_eq(x):
            Q = x.reshape((T, N))
            return np.mean(Q[:, last_station_idx]) - target_avg

        cons = [{'type': 'eq', 'fun': constraint_eq}]
        x0 = np.ones(N * T) * target_avg
        
        for i, (b_min, b_max) in enumerate(bounds):
            x0[i] = np.clip(x0[i], b_min, b_max)
            
        res = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 100, 'disp': False})
        return res.x.reshape((T, N))

    def _solve_greedy(
        self,
        now: int,
        horizon: int,
        station_ids: List[int],
        station_models: Dict[int, PumpStationModel],
        chain_pairs: List[Dict[str, object]],
        targets: Dict[str, float],
        current_levels: Dict[str, float],
        level_keys: List[str],
        env_snapshot,
        demand_state: Mapping[str, float],
        disturbance_forecast: Mapping[int, object],
        target_avg: float,
        feasible_flow_overrides: Optional[Dict[int, List[float]]] = None,
    ) -> np.ndarray:
        N = len(station_ids)
        T = horizon
        Q_opt = np.zeros((T, N))
        
        simulated_levels = {key: float(value) for key, value in current_levels.items()}
        for step in range(T):
            step_command_flows = {}
            for index, station_id in reversed(list(enumerate(station_ids))):
                if index == N - 1:
                    target_flow = target_avg
                else:
                    pair = next(p for p in chain_pairs if p["upstream_station_id"] == station_ids[index])
                    downstream_flow = step_command_flows[station_ids[index + 1]]
                    pool_id = int(pair["pool_id"])
                    
                    demand_row = self.demand_plan.iloc[min(now + step, len(self.demand_plan) - 1)]
                    demand_value = float(demand_row.get(str(pair["demand_column"]), 0.0))
                    disturbance = float(disturbance_value_at_step(disturbance_forecast, pool_id, step))
                    
                    area = float(env_snapshot.pool_areas.get(pool_id, 1.0))
                    current_pool_level = float(simulated_levels[pair["back_level_key"]])
                    target_pool_level = float(targets.get(str(pair["back_level_key"]), current_pool_level))
                    
                    correction = self._level_correction(target_pool_level, current_pool_level, area)
                    target_flow = max(downstream_flow - demand_value - disturbance + correction, 0.0)
                
                if index == N - 1:
                    head_key_index = min(index, len(level_keys) - 1)
                else:
                    head_key_index = index + 1
                head = float(simulated_levels[level_keys[head_key_index]] - simulated_levels[level_keys[head_key_index - 1]])
                
                flow, _ = self._pick_row(station_models[station_id], target_flow, head)
                # 根据当前扬程从缓存表中获取真实可行流量范围，并将规划流量硬裁剪
                if feasible_flow_overrides and station_id in feasible_flow_overrides:
                    override = feasible_flow_overrides[station_id]
                    flow = float(np.clip(flow, float(override[0]), float(override[1])))
                else:
                    hbq_lo, hbq_hi = station_models[station_id].feasible_flow_range(
                        head=head, tolerance=float(self.runtime.head_search_tolerance)
                    )
                    if hbq_lo < hbq_hi:  # 有效可行域：裁剪
                        flow = float(np.clip(flow, hbq_lo, hbq_hi))
                    # 若该扬程下无可行域（hbq_lo>=hbq_hi），保持 _pick_row 的回退结果
                step_command_flows[station_id] = flow
                Q_opt[step, index] = flow
                
            step_flow_plan = {sid: [step_command_flows[sid]] for sid in station_ids}
            predicted = simulate_basin_trajectory(
                system_config=self.system_config,
                runtime=self.runtime,
                initial_levels=simulated_levels,
                flow_plan=step_flow_plan,
                demand_plan=self.demand_plan,
                boundary_level_plan=self.boundary_level_plan,
                disturbance_forecast=disturbance_forecast,
                start_hour=now + step,
                boundary_nominal_flows=env_snapshot.boundary_nominal_flows,
                anchor_basin_levels=env_snapshot.anchor_basin_levels,
                pool_areas=env_snapshot.pool_areas,
                pool_profiles=getattr(env_snapshot, "basin_profiles", None),
            )
            for k in level_keys:
                simulated_levels[k] = predicted["basin_levels"][-1][k]
                
        return Q_opt

    def solve(
        self,
        now: int,
        env_snapshot,
        demand_state: Mapping[str, float],
        available_units_map: AvailableUnitsMap,
        disturbance_forecast: Mapping[int, object],
        lower_feedback: LowerFeedback,
    ) -> UpperPlan:
        horizon = max(self.system_config.horizon_hours - now, 1)
        effective_units_map = lower_feedback.available_units_map or available_units_map
        station_models = self._build_station_models(effective_units_map)
        targets = basin_level_targets(env_snapshot.anchor_basin_levels)
        current_levels = self._apply_state_feedback_correction(env_snapshot.basin_levels, lower_feedback)
        station_ids = _ordered_station_ids(self.system_config)
        level_keys = _level_keys(self.system_config)
        chain_pairs = _chain_pairs(self.system_config)
        last_station_id = self.system_config.last_station_id
        last_station_index = len(station_ids) - 1

        flow_refs: Dict[int, List[float]] = {station_id: [] for station_id in station_ids}
        effective_flow_refs: Dict[int, List[float]] = {station_id: [] for station_id in station_ids}
        command_flow_refs: Dict[int, List[float]] = {station_id: [] for station_id in station_ids}
        efficiency_refs: Dict[int, List[float]] = {station_id: [] for station_id in station_ids}
        station_back_levels: Dict[int, List[float]] = {station_id: [] for station_id in station_ids}
        station_front_levels: Dict[int, List[float]] = {station_id: [] for station_id in station_ids}
        station_heads: Dict[int, List[float]] = {station_id: [] for station_id in station_ids}
        planned_last_station_volume = 0.0

        target_avg = self._target_remaining_flow(
            {"delivered_last_station_total": float(demand_state.get("delivered_last_station_total", 0.0))},
            horizon
        )

        # 从下层反馈中提取实际可行流量范围（ODD3降级时机组组合会变化导致范围收窄）
        feasible_flow_overrides: Dict[int, List[float]] = {}
        for s_id, flow_range in lower_feedback.feasible_flow_ranges.items():
            if flow_range and len(flow_range) == 2:
                q_lo, q_hi = float(flow_range[0]), float(flow_range[1])
                if q_lo < q_hi:  # 仅当范围有效时才覆盖
                    feasible_flow_overrides[s_id] = [q_lo, q_hi]

        if self.runtime.upper_mpc_optimization_method == "nlp":
            Q_opt = self._solve_global_nlp(
                now=now,
                horizon=horizon,
                station_ids=station_ids,
                station_models=station_models,
                chain_pairs=chain_pairs,
                targets=targets,
                current_levels=current_levels,
                level_keys=level_keys,
                env_snapshot=env_snapshot,
                demand_state=demand_state,
                disturbance_forecast=disturbance_forecast,
                target_avg=target_avg,
                feasible_flow_overrides=feasible_flow_overrides if feasible_flow_overrides else None,
            )
        else:
            Q_opt = self._solve_greedy(
                now=now,
                horizon=horizon,
                station_ids=station_ids,
                station_models=station_models,
                chain_pairs=chain_pairs,
                targets=targets,
                current_levels=current_levels,
                level_keys=level_keys,
                env_snapshot=env_snapshot,
                demand_state=demand_state,
                disturbance_forecast=disturbance_forecast,
                target_avg=target_avg,
                feasible_flow_overrides=feasible_flow_overrides if feasible_flow_overrides else None,
            )

        for step in range(horizon):
            step_command_flows: Dict[int, float] = {}
            step_effective_flows: Dict[int, float] = {}
            step_efficiencies: Dict[int, float] = {}
            
            for index, station_id in enumerate(station_ids):
                q_command = float(Q_opt[step, index])
                
                # 取精确推演前一刻的水位计算扬程
                if index == last_station_index:
                    head_key_index = min(index, len(level_keys) - 1)
                else:
                    head_key_index = index + 1
                head = float(current_levels[level_keys[head_key_index]] - current_levels[level_keys[head_key_index - 1]])
                eff = station_models[station_id].get_efficiency(head, q_command) or 0.0
                
                q_effective = self._startup_effective_flow(
                    step=step,
                    station_id=station_id,
                    fallback_flow=self._apply_flow_bias_correction(station_id, q_command, lower_feedback),
                    env_snapshot=env_snapshot,
                )
                step_command_flows[station_id] = q_command
                step_effective_flows[station_id] = q_effective
                step_efficiencies[station_id] = eff

            step_flow_plan = {station_id: [step_effective_flows[station_id]] for station_id in station_ids}
            predicted = simulate_basin_trajectory(
                system_config=self.system_config,
                runtime=self.runtime,
                initial_levels=current_levels,
                flow_plan=step_flow_plan,
                demand_plan=self.demand_plan,
                boundary_level_plan=self.boundary_level_plan,
                disturbance_forecast=disturbance_forecast,
                start_hour=now + step,
                boundary_nominal_flows=env_snapshot.boundary_nominal_flows,
                anchor_basin_levels=env_snapshot.anchor_basin_levels,
                pool_areas=env_snapshot.pool_areas,
                pool_profiles=getattr(env_snapshot, "basin_profiles", None),
            )
            current_levels = predicted["basin_levels"][-1]
            planned_last_station_volume += float(step_effective_flows[last_station_id])
            station_levels = predicted["station_levels"][-1]
            for station_id in station_ids:
                flow_refs[station_id].append(float(step_command_flows[station_id]))
                effective_flow_refs[station_id].append(float(step_effective_flows[station_id]))
                command_flow_refs[station_id].append(float(step_command_flows[station_id]))
                efficiency_refs[station_id].append(float(step_efficiencies[station_id]))
                station_back_levels[station_id].append(float(station_levels["station_back_levels"][station_id]))
                station_front_levels[station_id].append(float(station_levels["station_front_levels"][station_id]))
                station_heads[station_id].append(float(station_levels["station_heads"][station_id]))

        return UpperPlan(
            hour_index=now,
            horizon=horizon,
            flow_refs=flow_refs,
            station_back_levels=station_back_levels,
            station_front_levels=station_front_levels,
            station_heads=station_heads,
            efficiency_refs=efficiency_refs,
            target_last_station_flow=float(flow_refs[last_station_id][0]),
            effective_flow_refs=effective_flow_refs,
            command_flow_refs=command_flow_refs,
            metadata={
                "remaining_target_avg_flow": float(target_avg),
                "remaining_target_avg_flow_effective": float(effective_flow_refs[last_station_id][0]),
                "remaining_target_avg_flow_command": float(command_flow_refs[last_station_id][0]),
                "flow_bias_gain": float(self.runtime.upper_flow_bias_correction_gain),
                "reconfigured_station_count": float(sum(1 for changed in lower_feedback.reconfigured_stations.values() if changed)),
                **{
                    f"observer_pool_{pair['pool_id']}": disturbance_value_at_step(disturbance_forecast, int(pair["pool_id"]), 0)
                    for pair in chain_pairs
                },
                **{
                    f"flow_bias_station_{station_id}": float(lower_feedback.plan_execution_errors.get(station_id, 0.0))
                    for station_id in station_ids
                },
                **{
                    f"effective_flow_station_{station_id}": float(effective_flow_refs[station_id][0])
                    for station_id in station_ids
                },
                **{
                    f"command_flow_station_{station_id}": float(command_flow_refs[station_id][0])
                    for station_id in station_ids
                },
                **{
                    f"startup_flow_station_{station_id}": float(env_snapshot.station_flows.get(station_id, 0.0))
                    for station_id in station_ids
                },
                **{
                    f"startup_level_{level_key}": float(env_snapshot.basin_levels.get(level_key, 0.0))
                    for level_key in level_keys
                },
            },
        )
