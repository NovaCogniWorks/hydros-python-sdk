from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from .environment import _chain_pairs, _level_keys, _ordered_station_ids
from .types import PoolProfileState, RuntimeParameters, SystemConfig


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
    ) -> Dict[int, float]:
        dt_hours = float(step_hours if step_hours is not None else self.system_config.dt_hours)
        if dt_hours <= 0.0:
            raise ValueError("step_hours must be positive")
        dt_seconds = dt_hours * 3600.0
        station_ids = _ordered_station_ids(self.system_config)
        chain_pairs = _chain_pairs(self.system_config)
        level_keys = _level_keys(self.system_config)
        areas = {}
        for pair in chain_pairs:
            pool_id = pair["pool_id"]
            if pool_areas is None or pool_id not in pool_areas:
                raise ValueError(f"缺少 pool_id={pool_id} 的表面积配置，无法进行等效蓄量观测。")
            areas[pool_id] = float(pool_areas[pool_id])

        updated = {}
        for index, pair in enumerate(chain_pairs):
            pool_id = int(pair["pool_id"])
            upstream_station_id = int(pair["upstream_station_id"])
            downstream_station_id = int(pair["downstream_station_id"])
            level_key = str(pair["level_key"])
            q_in = float(actual_flows[upstream_station_id])
            q_out = float(actual_flows[downstream_station_id])
            nominal_disturbance = float(demand_row.get(str(pair["demand_column"]), 0.0))
            if prev_basin_profiles is not None and next_basin_profiles is not None:
                storage_flow = (
                    float(next_basin_profiles[pool_id].reported_volume) - 
                    float(prev_basin_profiles[pool_id].reported_volume)
                ) / dt_seconds
            elif prev_basin_volumes is not None and next_basin_volumes is not None:
                storage_flow = (
                    float(next_basin_volumes[pool_id]) - float(prev_basin_volumes[pool_id])
                ) / dt_seconds
            else:
                actual_delta = float(next_basin_levels[level_key] - prev_basin_levels[level_key])
                storage_flow = areas[pool_id] * actual_delta / dt_seconds
            inferred = storage_flow - (q_in - q_out - nominal_disturbance)
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
