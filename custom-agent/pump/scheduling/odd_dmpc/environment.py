from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Union

import numpy as np
import pandas as pd

from .thread_client import RemoteThreadClient
from .thread_snapshot import parse_thread_snapshot
from .types import ControlAction, EnvironmentObservation, PoolProfileState, RuntimeParameters, SystemConfig, ThreadSnapshotState


TimeLike = Union[int, float]


def _profile_integral(values: List[float], spacings: List[float]) -> float:
    if len(values) < 2 or len(values) != len(spacings):
        raise ValueError("Profile arrays must have matching lengths >= 2")
    integral = 0.0
    for idx in range(1, len(values)):
        integral += 0.5 * (float(values[idx - 1]) + float(values[idx])) * float(spacings[idx])
    return float(integral)


def _profile_representative_level(profile: PoolProfileState) -> float:
    total_length = sum(float(length) for length in profile.spacings[1:])
    if total_length <= 0.0:
        raise ValueError(f"Profile {profile.name} has zero total length")
    return float(_profile_integral(profile.water_levels, profile.spacings) / total_length)


def _profile_representative_depth(profile: PoolProfileState) -> float:
    depths = [
        max(float(level) - float(bed), 1.0e-6)
        for level, bed in zip(profile.water_levels, profile.bed_elevations)
    ]
    total_length = sum(float(length) for length in profile.spacings[1:])
    if total_length <= 0.0:
        raise ValueError(f"Profile {profile.name} has zero total length")
    representative_depth = _profile_integral(depths, profile.spacings) / total_length
    return float(max(representative_depth, 1.0e-6))


def _raw_surface_area_from_profile(profile: PoolProfileState) -> float:
    widths: List[float] = []
    for level, bed, area in zip(profile.water_levels, profile.bed_elevations, profile.wet_areas):
        depth = max(float(level) - float(bed), 1.0e-3)
        widths.append(max(float(area), 0.0) / depth)
    storage_area = _profile_integral(widths, profile.spacings)
    return float(max(storage_area, 1.0))


def _dynamic_storage_area_from_profile(profile: PoolProfileState) -> float:
    return float(max(_raw_surface_area_from_profile(profile), 1.0))


def _profile_width_scale(profile: PoolProfileState) -> float:
    raw_surface_area = _raw_surface_area_from_profile(profile)
    if raw_surface_area <= 1.0e-9:
        return 1.0
    return float(_dynamic_storage_area_from_profile(profile) / raw_surface_area)


def _profile_total_volume(profile: PoolProfileState) -> float:
    return float(profile.volume_offset + _profile_integral(profile.wet_areas, profile.spacings))


def _refresh_profile_geometry(profile: PoolProfileState) -> PoolProfileState:
    profile.representative_level = _profile_representative_level(profile)
    profile.representative_depth = _profile_representative_depth(profile)
    profile.computed_volume = _profile_integral(profile.wet_areas, profile.spacings)
    profile.reported_volume = _profile_total_volume(profile)
    profile.raw_surface_area = _raw_surface_area_from_profile(profile)
    profile.storage_area = _dynamic_storage_area_from_profile(profile)
    return profile


def _shift_profile_uniform(profile: PoolProfileState, delta_level: float) -> PoolProfileState:
    if abs(delta_level) <= 1.0e-12:
        return _refresh_profile_geometry(profile)
    width_scale = _profile_width_scale(profile)
    widths: List[float] = []
    for level, bed, area in zip(profile.water_levels, profile.bed_elevations, profile.wet_areas):
        depth = max(float(level) - float(bed), 1.0e-3)
        widths.append(width_scale * max(float(area), 0.0) / depth)
    new_levels: List[float] = []
    new_areas: List[float] = []
    for level, bed, width in zip(profile.water_levels, profile.bed_elevations, widths):
        updated_level = float(level) + float(delta_level)
        updated_depth = max(updated_level - float(bed), 0.0)
        new_levels.append(updated_level)
        new_areas.append(float(width) * updated_depth)
    profile.water_levels = new_levels
    profile.wet_areas = new_areas
    return _refresh_profile_geometry(profile)


def _project_profile_to_volume(profile: PoolProfileState, target_volume: float) -> PoolProfileState:
    target_volume = float(target_volume)
    for _ in range(8):
        current_volume = _profile_total_volume(profile)
        residual = target_volume - current_volume
        if abs(residual) <= 1.0:
            break
        storage_area = _dynamic_storage_area_from_profile(profile)
        profile = _shift_profile_uniform(profile, residual / max(storage_area, 1.0))
    profile.reported_volume = float(target_volume)
    return _refresh_profile_geometry(profile)


def _copy_basin_profiles(profiles: Mapping[int, PoolProfileState]) -> Dict[int, PoolProfileState]:
    return {pool_id: copy.deepcopy(profile) for pool_id, profile in profiles.items()}


def _ordered_station_ids(system_config: SystemConfig) -> List[int]:
    return [station.id for station in system_config.stations]


def _ordered_pool_ids(system_config: SystemConfig) -> List[int]:
    pool_ids = system_config.pool_ids
    if pool_ids:
        return sorted(pool_ids)
    return list(range(1, max(len(system_config.stations), 1)))


def _level_keys(system_config: SystemConfig) -> List[str]:
    keys = list(system_config.level_key_sequence)
    if len(keys) == len(system_config.stations) + 1:
        return keys
    return [f"b{i}" for i in range(len(system_config.stations) + 1)]


def _chain_pairs(system_config: SystemConfig) -> List[Dict[str, object]]:
    station_ids = _ordered_station_ids(system_config)
    pool_ids = _ordered_pool_ids(system_config)
    level_keys = _level_keys(system_config)
    pairs: List[Dict[str, object]] = []
    for idx, (up_id, down_id) in enumerate(zip(station_ids[:-1], station_ids[1:]), start=1):
        pool_id = pool_ids[idx - 1] if idx - 1 < len(pool_ids) else idx
        pairs.append(
            {
                "pool_id": int(pool_id),
                "upstream_station_id": int(up_id),
                "downstream_station_id": int(down_id),
                "demand_column": f"station{up_id}-station{down_id}",
                "level_key": level_keys[idx] if idx < len(level_keys) else f"b{idx}",
                "front_level_key": level_keys[idx - 1] if idx - 1 < len(level_keys) else f"b{idx - 1}",
                "back_level_key": level_keys[idx] if idx < len(level_keys) else f"b{idx}",
            }
        )
    return pairs


def _pool_level_clip_bounds(
    system_config: SystemConfig,
    upstream_station_id: int,
    downstream_station_id: int,
    margin: float,
) -> tuple[float, float]:
    upstream_station = system_config.station_by_id[upstream_station_id]
    downstream_station = system_config.station_by_id[downstream_station_id]
    lower = max(
        float(upstream_station.level_back_min),
        float(downstream_station.level_front_min),
    ) - float(margin)
    upper = min(
        float(upstream_station.level_back_max),
        float(downstream_station.level_front_max),
    ) + float(margin)
    if lower <= upper:
        return float(lower), float(upper)

    # Fallback to the combined envelope if the configured station limits do not overlap.
    lower = min(
        float(upstream_station.level_back_min),
        float(downstream_station.level_front_min),
    ) - float(margin)
    upper = max(
        float(upstream_station.level_back_max),
        float(downstream_station.level_front_max),
    ) + float(margin)
    return float(lower), float(upper)


def _boundary_plan_from_snapshot(system_config: SystemConfig, boundary_levels: Mapping[str, float]) -> pd.DataFrame:
    topology = system_config.topology
    columns = topology.boundary_series_columns
    if not columns:
        return pd.DataFrame([dict(boundary_levels)])
    row = {}
    for node in topology.boundary_nodes:
        key = str(node.mpc_key or node.id or node.hydro_node)
        column = str(node.series_column or node.hydro_node)
        if key in boundary_levels:
            row[column] = float(boundary_levels[key])
        elif node.hydro_node in boundary_levels:
            row[column] = float(boundary_levels[node.hydro_node])
    if not row:
        raise ValueError(f"无法将任何边界节点映射到水位数据: boundary_levels={boundary_levels}, expected_columns={columns}")
    ordered_row = {}
    for column in columns:
        if column not in row:
            raise ValueError(f"边界水位数据缺失列 '{column}': boundary_levels={boundary_levels}")
        ordered_row[column] = float(row[column])
    return pd.DataFrame([ordered_row])


def basin_level_targets(anchor_basin_levels: Mapping[str, float]) -> Dict[str, float]:
    return {key: float(value) for key, value in anchor_basin_levels.items()}


def resolve_pool_areas(
    system_config: SystemConfig,
    snapshot: Optional[ThreadSnapshotState] = None,
    auto_identify: bool = False,
) -> Dict[int, float]:
    del auto_identify
    areas = {}
    for pool in system_config.canal_pools:
        area = None
        if snapshot is not None and snapshot.pool_areas:
            area = snapshot.pool_areas.get(pool.id)
        if area is None:
            area = pool.area
        if area is None:
            raise ValueError(f"缺少渠道 pool_id={pool.id} 的表面积配置，无法进行等效蓄量水位计算。")
        areas[pool.id] = float(area)
    return areas


def basin_to_station_levels(
    basin_levels: Mapping[str, float],
    system_config: Optional[SystemConfig] = None,
) -> Dict[str, Dict[int, float]]:
    if system_config is not None:
        station_ids = _ordered_station_ids(system_config)
        level_keys = _level_keys(system_config)
        if len(level_keys) >= len(station_ids) + 1:
            station_back_levels = {
                station_id: float(basin_levels[level_keys[idx]])
                for idx, station_id in enumerate(station_ids, start=1)
            }
            station_front_levels = {
                station_id: float(basin_levels[level_keys[idx - 1]])
                for idx, station_id in enumerate(station_ids, start=1)
            }
            station_heads = {
                station_id: station_back_levels[station_id] - station_front_levels[station_id]
                for station_id in station_ids
            }
            return {
                "station_back_levels": station_back_levels,
                "station_front_levels": station_front_levels,
                "station_heads": station_heads,
                "station_up_levels": station_back_levels,
                "station_down_levels": station_front_levels,
            }

    ordered_keys = sorted(key for key in basin_levels if re.match(r"^b\d+$", str(key)))
    station_back_levels = {}
    station_front_levels = {}
    for idx, key in enumerate(ordered_keys[1:], start=1):
        station_back_levels[idx] = float(basin_levels[key])
        station_front_levels[idx] = float(basin_levels[ordered_keys[idx - 1]])
    station_heads = {
        station_id: station_back_levels[station_id] - station_front_levels[station_id]
        for station_id in station_back_levels
    }
    return {
        "station_back_levels": station_back_levels,
        "station_front_levels": station_front_levels,
        "station_heads": station_heads,
        "station_up_levels": station_back_levels,
        "station_down_levels": station_front_levels,
    }


def basin_profiles_to_basin_levels(
    basin_profiles: Mapping[int, PoolProfileState],
    boundary_levels: Mapping[str, float],
    system_config: Optional[SystemConfig] = None,
) -> Dict[str, float]:
    if system_config is not None:
        level_keys = _level_keys(system_config)
        pool_ids = _ordered_pool_ids(system_config)
        basin_levels: Dict[str, float] = {}
        if level_keys:
            fallback_value = float(next(iter(boundary_levels.values()), 0.0))
            last_value = float(next(reversed(list(boundary_levels.values())), fallback_value)) if boundary_levels else 0.0
            basin_levels[level_keys[0]] = float(boundary_levels.get(level_keys[0], fallback_value))
            basin_levels[level_keys[-1]] = float(boundary_levels.get(level_keys[-1], last_value))
        for idx, pool_id in enumerate(pool_ids, start=1):
            key = level_keys[idx] if idx < len(level_keys) else f"b{idx}"
            profile = basin_profiles.get(pool_id)
            if profile is not None:
                basin_levels[key] = float(profile.representative_level)
        return basin_levels
    return {
        "b0": float(boundary_levels["b0"]),
        "b1": float(basin_profiles[1].representative_level),
        "b2": float(basin_profiles[2].representative_level),
        "b3": float(boundary_levels["b3"]),
    }


def _validate_hidden_disturbance_frame(path: str, df: pd.DataFrame) -> pd.DataFrame:
    expected = ["hour", "pool1", "pool2"]
    if list(df.columns) != expected:
        raise ValueError(f"Unexpected hidden disturbance columns in {path}: {list(df.columns)}")
    validated = df.copy()
    validated["hour"] = pd.to_numeric(validated["hour"], errors="raise").astype(int)
    validated["pool1"] = pd.to_numeric(validated["pool1"], errors="raise")
    validated["pool2"] = pd.to_numeric(validated["pool2"], errors="raise")
    validated = validated.sort_values("hour").drop_duplicates(subset=["hour"], keep="last")
    return validated.set_index("hour", drop=False)


def load_hidden_disturbance_scenarios(runtime: RuntimeParameters) -> Dict[str, pd.DataFrame]:
    scenario_paths = {
        "light": runtime.hidden_disturbance_rain_light_path,
        "moderate": runtime.hidden_disturbance_rain_moderate_path,
        "heavy": runtime.hidden_disturbance_rain_heavy_path,
    }
    scenarios = {}
    for scenario, path in scenario_paths.items():
        scenarios[scenario] = _validate_hidden_disturbance_frame(path, pd.read_excel(path))
    return scenarios


def _hour_index(step_time: TimeLike) -> int:
    return int(np.floor(float(step_time) + 1e-9))


def hidden_disturbance_at_step(
    step_index: TimeLike,
    disturbance_plan: Optional[pd.DataFrame],
    pool_ids: Optional[Iterable[int]] = None,
) -> Dict[int, float]:
    ordered_pool_ids = [int(pool_id) for pool_id in (pool_ids or [1, 2])]
    if disturbance_plan is None or disturbance_plan.empty:
        return {pool_id: 0.0 for pool_id in ordered_pool_ids}

    hour_index = _hour_index(step_index)
    if hour_index in disturbance_plan.index:
        row = disturbance_plan.loc[hour_index]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
    else:
        row = disturbance_plan.iloc[min(max(hour_index, 0), len(disturbance_plan) - 1)]

    disturbance: Dict[int, float] = {}
    for pool_id in ordered_pool_ids:
        column = f"pool{pool_id}"
        disturbance[pool_id] = float(row[column]) if column in row else 0.0
    return disturbance


def _resolve_path(system_config: SystemConfig, candidate_path: str) -> Path:
    candidate = Path(candidate_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    search_roots = [
        Path.cwd(),
        Path(system_config.source_config_path).resolve().parent,
        Path(system_config.source_config_path).resolve().parent.parent,
    ]
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (Path.cwd() / candidate).resolve()


def load_boundary_level_plan(system_config: SystemConfig) -> pd.DataFrame:
    if system_config.boundary_level_inline is not None:
        df = pd.DataFrame(
            system_config.boundary_level_inline.rows,
            columns=system_config.boundary_level_inline.columns,
        )
        normalized = df.copy()
        for column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="raise")
        return normalized.reset_index(drop=True)
    topology = system_config.topology
    if system_config.boundary_level_path is None:
        raise ValueError("Boundary level source is not configured")
    path = _resolve_path(system_config, system_config.boundary_level_path)
    df = pd.read_excel(path)
    expected_columns = topology.boundary_series_columns or list(df.columns)
    if list(df.columns) != expected_columns:
        raise ValueError(f"Unexpected boundary level columns in {path}: {list(df.columns)}")
    normalized = df.copy()
    for column in expected_columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise")
    return normalized.reset_index(drop=True)


def boundary_levels_at_hour(
    boundary_level_plan: pd.DataFrame,
    step_time: TimeLike,
    system_config: Optional[SystemConfig] = None,
) -> Dict[str, float]:
    if boundary_level_plan.empty:
        raise ValueError("Boundary level plan is empty")
    hour_index = min(max(_hour_index(step_time), 0), len(boundary_level_plan) - 1)
    row = boundary_level_plan.iloc[hour_index]
    if system_config is not None and system_config.topology.boundary_nodes:
        levels: Dict[str, float] = {}
        for node in system_config.topology.boundary_nodes:
            key = str(node.mpc_key or node.id or node.hydro_node)
            column = str(node.series_column or node.hydro_node)
            if column not in row:
                raise ValueError(f"Missing boundary level column {column}")
            levels[key] = float(row[column])
        return levels
    columns = list(boundary_level_plan.columns)
    if len(columns) == 2:
        return {
            "b0": float(row[columns[0]]),
            "b3": float(row[columns[1]]),
        }
    return {f"b{idx}": float(row[column]) for idx, column in enumerate(columns)}


def _boundary_level_plan_for_system(
    system_config: SystemConfig,
    snapshot: Optional[ThreadSnapshotState] = None,
) -> pd.DataFrame:
    if system_config.topology.boundary_series_source == "create":
        if snapshot is not None:
            return _boundary_plan_from_snapshot(system_config, snapshot.boundary_levels)
        columns = system_config.topology.boundary_series_columns
        return pd.DataFrame(columns=columns)
    return load_boundary_level_plan(system_config)


def _channel_disturbance_nodes(system_config: SystemConfig) -> List[str]:
    nodes = [
        str(segment.disturbance_node)
        for segment in system_config.topology.channel_segments
        if getattr(segment, "disturbance_node", None)
    ]
    if nodes:
        return nodes
    return ["沙集站分水", "沙集站来水"]


def disturbance_value_at_step(
    disturbance_forecast: Mapping[int, object],
    pool_id: int,
    step_index: int,
) -> float:
    raw_value = disturbance_forecast.get(pool_id, 0.0)
    if isinstance(raw_value, (list, tuple, np.ndarray, pd.Series)):
        if len(raw_value) == 0:
            return 0.0
        return float(raw_value[min(max(step_index, 0), len(raw_value) - 1)])
    return float(raw_value)


def simulate_basin_trajectory(
    system_config: SystemConfig,
    runtime: RuntimeParameters,
    initial_levels: Mapping[str, float],
    flow_plan: Mapping[int, List[float]],
    demand_plan: pd.DataFrame,
    boundary_level_plan: pd.DataFrame,
    disturbance_forecast: Mapping[int, object],
    start_hour: TimeLike,
    step_hours: Optional[float] = None,
    boundary_nominal_flows: Optional[Mapping[str, float]] = None,
    anchor_basin_levels: Optional[Mapping[str, float]] = None,
    pool_areas: Optional[Mapping[int, float]] = None,
    pool_profiles: Optional[Mapping[int, PoolProfileState]] = None,
) -> Dict[str, List[Dict[str, float]]]:
    station_ids = _ordered_station_ids(system_config)
    chain_pairs = _chain_pairs(system_config)
    level_keys = _level_keys(system_config)
    horizon = len(next(iter(flow_plan.values()))) if flow_plan else 0
    levels = {str(key): float(value) for key, value in initial_levels.items()}
    level_history = [levels.copy()]
    station_history = [basin_to_station_levels(levels, system_config)]
    dt_hours = float(step_hours if step_hours is not None else system_config.dt_hours)
    dt_seconds = dt_hours * 3600.0 / max(runtime.env_substeps, 1)

    resolved_pool_areas = {
        int(pool_id): float(area)
        for pool_id, area in (
            pool_areas.items() if pool_areas is not None else resolve_pool_areas(system_config, auto_identify=False).items()
        )
    }
    profile_states = _copy_basin_profiles(pool_profiles) if pool_profiles is not None else None
    del boundary_nominal_flows
    del station_ids

    for step in range(horizon):
        current_time = float(start_hour) + step * dt_hours
        demand_hour = min(max(_hour_index(current_time), 0), len(demand_plan) - 1)
        demand_row = demand_plan.iloc[demand_hour]
        boundary_levels = boundary_levels_at_hour(boundary_level_plan, current_time, system_config)
        for key, value in boundary_levels.items():
            levels[str(key)] = float(value)

        for _ in range(max(runtime.env_substeps, 1)):
            for pair in chain_pairs:
                pool_id = int(pair["pool_id"])
                upstream_station_id = int(pair["upstream_station_id"])
                downstream_station_id = int(pair["downstream_station_id"])
                demand_column = str(pair["demand_column"])
                level_key = str(pair["level_key"])
                upstream_flow = float(flow_plan[upstream_station_id][step])
                downstream_flow = float(flow_plan[downstream_station_id][step])
                disturbance = disturbance_value_at_step(disturbance_forecast, pool_id, step)
                demand = float(demand_row.get(demand_column, 0.0)) + float(disturbance)
                if profile_states is None:
                    if pool_id not in resolved_pool_areas:
                        raise ValueError(f"缺少 pool_id={pool_id} 的渠道表面积 (pool_area) 数据，无法推演水位。")
                    pool_area = float(resolved_pool_areas[pool_id])
                    levels[level_key] = float(
                        levels.get(level_key, 0.0) + (upstream_flow - downstream_flow + demand) * dt_seconds / pool_area
                    )
                else:
                    profile = profile_states[pool_id]
                    profile_states[pool_id] = _project_profile_to_volume(
                        profile,
                        _profile_total_volume(profile) + (upstream_flow - downstream_flow + demand) * dt_seconds,
                    )
                    margin = runtime.basin_clip_margin_b1 if pool_id == 1 else runtime.basin_clip_margin_b2
                    min_level, max_level = _pool_level_clip_bounds(
                        system_config=system_config,
                        upstream_station_id=upstream_station_id,
                        downstream_station_id=downstream_station_id,
                        margin=margin,
                    )
                    if profile_states[pool_id].representative_level < min_level or profile_states[pool_id].representative_level > max_level:
                        target_level = float(np.clip(profile_states[pool_id].representative_level, min_level, max_level))
                        profile_states[pool_id] = _shift_profile_uniform(
                            profile_states[pool_id],
                            target_level - float(profile_states[pool_id].representative_level),
                        )
                    levels.update(basin_profiles_to_basin_levels(profile_states, boundary_levels, system_config))
                if profile_states is None:
                    margin = runtime.basin_clip_margin_b1 if pool_id == 1 else runtime.basin_clip_margin_b2
                    min_level, max_level = _pool_level_clip_bounds(
                        system_config=system_config,
                        upstream_station_id=upstream_station_id,
                        downstream_station_id=downstream_station_id,
                        margin=margin,
                    )
                    levels[level_key] = float(
                        np.clip(
                            levels.get(level_key, 0.0),
                            min_level,
                            max_level,
                        )
                    )

        if profile_states is not None:
            levels.update(basin_profiles_to_basin_levels(profile_states, boundary_levels, system_config))
        else:
            levels.update(boundary_levels)

        level_history.append(levels.copy())
        station_history.append(basin_to_station_levels(levels, system_config))

    return {
        "basin_levels": level_history,
        "station_levels": station_history,
    }


class RemoteHydraulicEnvironment:
    def __init__(
        self,
        system_config: SystemConfig,
        demand_plan: pd.DataFrame,
        runtime: RuntimeParameters,
        client: Optional[RemoteThreadClient] = None,
    ) -> None:
        self.system_config = system_config
        self.demand_plan = demand_plan.reset_index(drop=True)
        self.runtime = runtime
        self.client = client or RemoteThreadClient(runtime.sim_api_base_url)
        self.boundary_level_plan = _boundary_level_plan_for_system(system_config)
        self.hidden_disturbance_scenarios = load_hidden_disturbance_scenarios(runtime)
        if runtime.hidden_disturbance_enabled:
            scenario = runtime.hidden_disturbance_active_scenario.lower()
            if scenario not in self.hidden_disturbance_scenarios:
                raise ValueError(f"Unsupported hidden disturbance scenario: {runtime.hidden_disturbance_active_scenario}")
            self.hidden_disturbance_scenario = scenario
            self.hidden_disturbance_plan = self.hidden_disturbance_scenarios[scenario]
        else:
            self.hidden_disturbance_scenario = "disabled"
            self.hidden_disturbance_plan = None

        sync_steps = float(system_config.dt_hours) * 3600.0 / float(runtime.sim_sync_dt_seconds)
        if abs(sync_steps - round(sync_steps)) > 1e-9:
            raise ValueError(
                "scheduling.dt_hours * 3600 must be divisible by runtime.environment.sim_sync_dt_seconds"
            )
        self.sync_steps = int(round(sync_steps))
        self.time_hours = 0.0
        self.time_index = 0
        self.current_snapshot: Optional[ThreadSnapshotState] = None
        self.anchor_snapshot: Optional[ThreadSnapshotState] = None
        self.boundary_nominal_flows: Dict[str, float] = {"source": 0.0, "sink": 0.0}
        self.pool_areas: Dict[int, float] = resolve_pool_areas(system_config, auto_identify=False)
        self.last_hidden_disturbance = {pool_id: 0.0 for pool_id in (self.system_config.pool_ids or [1, 2])}
        self.last_bleeder_updates = {node: 0.0 for node in _channel_disturbance_nodes(self.system_config)}
        self.last_node_updates = {
            str(node.mpc_key or node.id or node.hydro_node): 0.0
            for node in self.system_config.topology.boundary_nodes
        }
        self.last_create_response: Optional[Mapping[str, object]] = None
        self.last_start_sync_response: Optional[Mapping[str, object]] = None

    def _hydro_model_path(self) -> Path:
        if not self.system_config.hydro_model_path:
            raise ValueError(
                "hydro_model is no longer configured in config.yaml; "
                "use the new remote-driven integration path instead of create_thread."
            )
        return _resolve_path(self.system_config, self.system_config.hydro_model_path)

    def _known_channel_disturbance(self, current_hour: TimeLike) -> Dict[int, float]:
        demand_hour = min(max(_hour_index(current_hour), 0), len(self.demand_plan) - 1)
        demand_row = self.demand_plan.iloc[demand_hour]
        hidden = hidden_disturbance_at_step(current_hour, self.hidden_disturbance_plan, self.system_config.pool_ids)
        disturbance: Dict[int, float] = {}
        for pair in _chain_pairs(self.system_config):
            pool_id = int(pair["pool_id"])
            column = str(pair["demand_column"])
            disturbance[pool_id] = float(demand_row.get(column, 0.0)) + float(hidden.get(pool_id, 0.0))
        return disturbance

    def reset(self) -> EnvironmentObservation:
        payload = self.client.create_thread(
            hydro_model_path=str(self._hydro_model_path()),
            is_steady_state=bool(self.runtime.sim_create_is_steady_state),
        )
        self.last_create_response = payload
        snapshot = parse_thread_snapshot(payload, self.system_config)
        self.time_hours = 0.0
        self.time_index = 0
        self.anchor_snapshot = copy.deepcopy(snapshot)
        self.current_snapshot = copy.deepcopy(snapshot)
        self.pool_areas = snapshot.pool_areas.copy()
        self.boundary_nominal_flows = {
            "source": float(self.anchor_snapshot.station_total_flows[self.system_config.first_station_id]),
            "sink": float(self.anchor_snapshot.station_total_flows[self.system_config.last_station_id]),
        }
        self.last_hidden_disturbance = {pool_id: 0.0 for pool_id in (self.system_config.pool_ids or [1, 2])}
        self.last_bleeder_updates = {node: 0.0 for node in _channel_disturbance_nodes(self.system_config)}
        if self.system_config.topology.boundary_series_source == "create":
            initial_boundaries = {
                str(key): float(value)
                for key, value in snapshot.boundary_levels.items()
            }
            self.boundary_level_plan = _boundary_plan_from_snapshot(self.system_config, snapshot.boundary_levels)
        else:
            initial_boundaries = boundary_levels_at_hour(self.boundary_level_plan, 0.0, self.system_config)
        self.last_node_updates = {str(key): float(value) for key, value in initial_boundaries.items()}
        return self.observe()

    def _build_updates(
        self,
        control_actions: Mapping[int, ControlAction],
        current_hour: TimeLike,
    ) -> List[Dict[str, object]]:
        updates: List[Dict[str, object]] = []
        for station in self.system_config.stations:
            external_station_name = str(station.remote_name or station.name)
            action = control_actions[station.id]
            for unit in station.units:
                status = int(action.unit_status.get(unit.id, 0))
                opening = float(action.unit_openings.get(unit.id, 100.0))
                value = opening if status == 1 else 100.0
                remote_unit_name = str(unit.remote_name or f"{external_station_name}{unit.id}")
                updates.append(
                    {
                        "type": "pumps",
                        "id": remote_unit_name,
                        "value": float(value),
                    }
                )

        channel_disturbance = self._known_channel_disturbance(current_hour)
        if self.system_config.topology.boundary_series_source == "create":
            self.last_node_updates = {}
        else:
            boundary_levels = boundary_levels_at_hour(self.boundary_level_plan, current_hour, self.system_config)
            self.last_node_updates = {str(key): float(value) for key, value in boundary_levels.items()}
        self.last_hidden_disturbance = hidden_disturbance_at_step(
            current_hour,
            self.hidden_disturbance_plan,
            self.system_config.pool_ids,
        )
        bleeders = {}
        for idx, node_id in enumerate(_channel_disturbance_nodes(self.system_config), start=1):
            value = -float(channel_disturbance.get(idx, 0.0))
            bleeders[node_id] = value
            updates.append({"type": "bleeders", "id": node_id, "value": float(value)})
        self.last_bleeder_updates = bleeders
        for node_id, value in self.last_node_updates.items():
            updates.append({"type": "nodes", "id": node_id, "value": float(value)})
        return updates

    def step(
        self,
        control_actions: Mapping[int, ControlAction],
        current_hour: TimeLike,
    ) -> EnvironmentObservation:
        if self.current_snapshot is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")
        updates = self._build_updates(control_actions, current_hour)
        self.client.update_thread(self.current_snapshot.thread_uuid, updates)
        payload = self.client.start_sync(
            uuid_value=self.current_snapshot.thread_uuid,
            dt_seconds=int(self.runtime.sim_sync_dt_seconds),
            steps=int(self.sync_steps),
        )
        self.last_start_sync_response = payload
        self.current_snapshot = parse_thread_snapshot(payload, self.system_config)
        self.time_hours = float(current_hour) + float(self.system_config.dt_hours)
        self.time_index = _hour_index(self.time_hours)
        return self.observe()

    def observe(self) -> EnvironmentObservation:
        if self.current_snapshot is None or self.anchor_snapshot is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")
        snapshot = self.current_snapshot
        snapshot_basin_levels = snapshot.basin_levels.copy()
        snapshot_boundary_levels = snapshot.boundary_levels.copy()
        snapshot_station_front = snapshot.station_front_levels.copy()
        snapshot_station_back = snapshot.station_back_levels.copy()
        if float(self.time_hours) > 1.0e-9:
            boundary_levels = boundary_levels_at_hour(self.boundary_level_plan, self.time_hours, self.system_config)
            level_keys = _level_keys(self.system_config)
            if level_keys:
                snapshot_basin_levels[level_keys[0]] = float(boundary_levels[level_keys[0]])
                snapshot_basin_levels[level_keys[-1]] = float(boundary_levels[level_keys[-1]])
                snapshot_boundary_levels.update({key: float(value) for key, value in boundary_levels.items()})
                snapshot_station_front[self.system_config.first_station_id] = float(boundary_levels[level_keys[0]])
                snapshot_station_back[self.system_config.last_station_id] = float(boundary_levels[level_keys[-1]])
        return EnvironmentObservation(
            time_index=self.time_index,
            time_hours=float(self.time_hours),
            basin_levels=snapshot_basin_levels,
            basin_volumes=snapshot.basin_volumes.copy(),
            pool_areas=snapshot.pool_areas.copy(),
            basin_profiles=_copy_basin_profiles(snapshot.basin_profiles),
            anchor_basin_levels=self.anchor_snapshot.basin_levels.copy(),
            boundary_nominal_flows=self.boundary_nominal_flows.copy(),
            station_back_levels=snapshot_station_back,
            station_front_levels=snapshot_station_front,
            station_heads={
                station_id: float(snapshot_station_back[station_id] - snapshot_station_front[station_id])
                for station_id in snapshot_station_back
            },
            station_flows=snapshot.station_total_flows.copy(),
            pool_levels={
                pool_id: float(snapshot_basin_levels.get(_level_keys(self.system_config)[pool_id], 0.0))
                for pool_id in self.system_config.pool_ids
            } if self.system_config.pool_ids else {},
            thread_uuid=snapshot.thread_uuid,
        )

    def get_internal_state(self) -> Dict[str, object]:
        if self.current_snapshot is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")
        return {
            "uuid": self.current_snapshot.thread_uuid,
            "raw_result": self.current_snapshot.raw_result,
            "basin_levels": self.current_snapshot.basin_levels.copy(),
            "basin_volumes": self.current_snapshot.basin_volumes.copy(),
            "pool_areas": self.current_snapshot.pool_areas.copy(),
            "basin_profiles": _copy_basin_profiles(self.current_snapshot.basin_profiles),
            "last_bleeder_updates": self.last_bleeder_updates.copy(),
            "last_node_updates": self.last_node_updates.copy(),
            "last_hidden_disturbance": self.last_hidden_disturbance.copy(),
            "create_response": self.last_create_response,
            "start_sync_response": self.last_start_sync_response,
        }
