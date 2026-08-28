from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from .environment import _chain_pairs, _level_keys, _ordered_station_ids
from .types import PoolProfileState, RuntimeParameters, SystemConfig
import logging

logger = logging.getLogger(__name__)


@dataclass
class DisturbanceObserverBank:
    system_config: SystemConfig
    runtime: RuntimeParameters
    estimates: Dict[int, float] = field(default_factory=lambda: {1: 0.0, 2: 0.0})
    pending_updates: Dict[int, Optional[float]] = field(default_factory=lambda: {1: None, 2: None})
    history: Dict[int, List[float]] = field(default_factory=lambda: {1: [], 2: []})

    def __post_init__(self) -> None:
        pool_ids = self.system_config.pool_ids or list(range(1, max(len(self.system_config.stations), 1)))
        self.estimates = {pool_id: float(self.estimates.get(pool_id, 0.0)) for pool_id in pool_ids}
        self.pending_updates = {pool_id: self.pending_updates.get(pool_id) for pool_id in pool_ids}
        self.history = {pool_id: list(self.history.get(pool_id, [])) for pool_id in pool_ids}

    def _append_history(self, values: Mapping[int, float]) -> None:
        for pool_id in self.estimates:
            self.history[pool_id].append(float(values[pool_id]))

    def flush_pending(self) -> None:
        applied = False
        for pool_id, value in list(self.pending_updates.items()):
            if value is None:
                continue
            self.estimates[pool_id] = float(value)
            self.pending_updates[pool_id] = None
            applied = True
        if applied:
            self._append_history(self.estimates)

    def get_estimate(self) -> Dict[int, float]:
        return {pool_id: float(value) for pool_id, value in self.estimates.items()}

    def get_forecast(
        self,
        horizon: int,
        step_hours: Optional[float] = None,
    ) -> Dict[int, List[float]]:
        dt_hours = float(step_hours if step_hours is not None else self.system_config.dt_hours)
        if dt_hours <= 0.0:
            raise ValueError("step_hours must be positive")
        window_steps = max(
            1,
            int(round(float(self.runtime.disturbance_forecast_window_hours) / dt_hours)),
        )
        method = str(self.runtime.disturbance_forecast_method).strip().lower()
        forecasts: Dict[int, List[float]] = {}
        for pool_id in self.estimates:
            history = self.history[pool_id][-window_steps:]
            current = float(self.estimates[pool_id])
            if not history:
                history = [current]
            forecasts[pool_id] = self._forecast_series(history, current, horizon, method)
        return forecasts

    def _forecast_series(
        self,
        history: List[float],
        current: float,
        horizon: int,
        method: str,
    ) -> List[float]:
        if horizon <= 0:
            return []
        if method == "hold":
            return [float(current)] * horizon
        if method == "mean":
            mean_value = float(np.mean(history))
            return [mean_value] * horizon
        if method == "linear":
            if len(history) < 2:
                return [float(current)] * horizon
            x = np.arange(len(history), dtype=float)
            y = np.asarray(history, dtype=float)
            slope, intercept = np.polyfit(x, y, deg=1)
            start_x = float(len(history) - 1)
            return [float(slope * (start_x + step + 1.0) + intercept) for step in range(horizon)]
        raise ValueError(f"Unsupported disturbance forecast method: {self.runtime.disturbance_forecast_method}")

    def update(
        self,
        prev_basin_levels: Mapping[str, float],
        next_basin_levels: Mapping[str, float],
        actual_flows: Mapping[int, float],
        demand_row: pd.Series,
        prev_basin_volumes: Optional[Mapping[int, float]] = None,
        next_basin_volumes: Optional[Mapping[int, float]] = None,
        prev_basin_profiles: Optional[Mapping[int, PoolProfileState]] = None,
        next_basin_profiles: Optional[Mapping[int, PoolProfileState]] = None,
        defer_visibility: bool = False,
        step_hours: Optional[float] = None,
        pool_areas: Optional[Mapping[int, float]] = None,
        prev_station_front_levels: Optional[Mapping[int, float]] = None,
        prev_station_back_levels: Optional[Mapping[int, float]] = None,
        next_station_front_levels: Optional[Mapping[int, float]] = None,
        next_station_back_levels: Optional[Mapping[int, float]] = None,
    ) -> Dict[int, float]:
        dt_hours = float(step_hours if step_hours is not None else self.system_config.dt_hours)
        if dt_hours <= 0.0:
            raise ValueError("step_hours must be positive")
        dt_seconds = dt_hours * 3600.0
        chain_pairs = _chain_pairs(self.system_config)
        areas = {}
        for pair in chain_pairs:
            pool_id = pair["pool_id"]
            if pool_areas is None or pool_id not in pool_areas:
                raise ValueError(f"缺少 pool_id={pool_id} 的表面积配置，无法进行等效蓄量观测。")
            areas[pool_id] = float(pool_areas[pool_id])

        updated = {}
        for pair in chain_pairs:
            pool_id = int(pair["pool_id"])
            upstream_station_id = int(pair["upstream_station_id"])
            downstream_station_id = int(pair["downstream_station_id"])
            level_key = str(pair["level_key"])
            q_in = float(actual_flows[upstream_station_id])
            q_out = float(actual_flows[downstream_station_id])
            nominal_disturbance = float(demand_row.get(str(pair["demand_column"]), 0.0))

            storage_source = "basin_level"
            upstream_back_prev = None
            upstream_back_next = None
            upstream_back_delta = None
            downstream_front_prev = None
            downstream_front_next = None
            downstream_front_delta = None

            if (
                prev_station_back_levels is not None
                and next_station_back_levels is not None
                and prev_station_front_levels is not None
                and next_station_front_levels is not None
                and upstream_station_id in prev_station_back_levels
                and upstream_station_id in next_station_back_levels
                and downstream_station_id in prev_station_front_levels
                and downstream_station_id in next_station_front_levels
            ):
                # 误差观察器基于“中间节点”计算未知扰动：
                # 池段两端分别是上游站后池和下游站前池，不涉及两端边界水位节点
                # （首站前池、末站后池）。
                upstream_back_prev = float(prev_station_back_levels[upstream_station_id])
                upstream_back_next = float(next_station_back_levels[upstream_station_id])
                downstream_front_prev = float(prev_station_front_levels[downstream_station_id])
                downstream_front_next = float(next_station_front_levels[downstream_station_id])
                upstream_back_delta = upstream_back_next - upstream_back_prev
                downstream_front_delta = downstream_front_next - downstream_front_prev
                representative_delta = (upstream_back_delta + downstream_front_delta) / 2.0
                storage_flow = areas[pool_id] * representative_delta / dt_seconds
                storage_source = "station_endpoints"
            elif (
                prev_basin_profiles is not None
                and next_basin_profiles is not None
                and pool_id in prev_basin_profiles
                and pool_id in next_basin_profiles
            ):
                storage_flow = (
                    float(next_basin_profiles[pool_id].reported_volume) -
                    float(prev_basin_profiles[pool_id].reported_volume)
                ) / dt_seconds
                storage_source = "basin_profiles"
            elif (
                prev_basin_volumes is not None
                and next_basin_volumes is not None
                and pool_id in prev_basin_volumes
                and pool_id in next_basin_volumes
            ):
                storage_flow = (
                    float(next_basin_volumes[pool_id]) - float(prev_basin_volumes[pool_id])
                ) / dt_seconds
                storage_source = "basin_volumes"
            else:
                actual_delta = float(next_basin_levels[level_key] - prev_basin_levels[level_key])
                storage_flow = areas[pool_id] * actual_delta / dt_seconds
                storage_source = "basin_level"
            # 由于采用了 正=来水(inflow)，负=出水(outflow) 的符号约定：
            # storage_flow = q_in - q_out + nominal_disturbance + hidden_disturbance
            # 其中 planned inflow 会以正 demand 表示，因此反推 hidden disturbance 时
            # 采用的逻辑是：hidden_disturbance = 实际蓄量变化 - 理论已知净流量
            inferred = storage_flow - (q_in - q_out + nominal_disturbance)

            if storage_source == "station_endpoints":
                logger.info(
                    f"误差观察器计算 Pool {pool_id} 扰动 (中间节点水位差):\n"
                    f"  上游站 S{upstream_station_id} 后池: {upstream_back_prev:.3f} -> {upstream_back_next:.3f} (Δ={upstream_back_delta:+.3f})\n"
                    f"  下游站 S{downstream_station_id} 前池: {downstream_front_prev:.3f} -> {downstream_front_next:.3f} (Δ={downstream_front_delta:+.3f})\n"
                    f"  实际流入(q_in)={q_in:.3f}, 实际流出(q_out)={q_out:.3f}, 计划需水(nominal)={nominal_disturbance:.3f}\n"
                    f"  理论已知流量差(q_in - q_out + nominal)={(q_in - q_out + nominal_disturbance):.3f}\n"
                    f"  实际蓄水量变化率(storage_flow)={storage_flow:.3f}\n"
                    f"  反推瞬时未知扰动(inferred)={inferred:.3f}"
                )
            else:
                logger.info(
                    f"误差观察器计算 Pool {pool_id} 扰动 ({storage_source}):\n"
                    f"  实际流入(q_in)={q_in:.3f}, 实际流出(q_out)={q_out:.3f}, 计划需水(nominal)={nominal_disturbance:.3f}\n"
                    f"  理论已知流量差(q_in - q_out + nominal)={(q_in - q_out + nominal_disturbance):.3f}\n"
                    f"  实际蓄水量变化率(storage_flow)={storage_flow:.3f}\n"
                    f"  反推瞬时未知扰动(inferred)={inferred:.3f}"
                )

            old = float(self.estimates[pool_id])
            corrected = old + self.runtime.observer_gain * (inferred - old)
            smoothed = self.runtime.observer_smoothing * old + (1.0 - self.runtime.observer_smoothing) * corrected
            updated[pool_id] = float(smoothed)

        if defer_visibility:
            self.pending_updates.update(updated)
        else:
            self.estimates.update(updated)
            self._append_history(updated)
        return self.get_estimate()
