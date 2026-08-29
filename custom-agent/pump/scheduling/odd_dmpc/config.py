from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path
from typing import Collection, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import yaml

from .types import (
    BoundaryNodeConfig,
    ChannelGroupConfig,
    ChannelSegmentConfig,
    InlineTableConfig,
    PoolConfig,
    RuntimeParameters,
    StationConfig,
    SystemConfig,
    TopologyConfig,
    UnitConfig,
)

STATIC_CONFIG_FILENAME = "mpc_static_config.yaml"
CURVES_CONFIG_FILENAME = "mpc_curves.yaml"



def _load_config(config_path: Path) -> Dict:
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid config payload in {config_path}")
    return payload


def _default_static_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / STATIC_CONFIG_FILENAME


def _resolve_static_config_path(
    payload: Mapping[str, object],
    runtime_config_path: Path,
    static_config_path: Optional[str] = None,
) -> Path:
    configured_path = static_config_path or payload.get("static_config_path")
    if isinstance(configured_path, str) and configured_path.strip():
        candidate = Path(configured_path)
        if candidate.is_absolute():
            return candidate
        if runtime_config_path.name != "agent_config_memory":
            return (runtime_config_path.resolve().parent / candidate).resolve()
        return (_default_static_config_path().parent / candidate).resolve()
    return _default_static_config_path()


def _resolve_curves_config_path(
    payload: Mapping[str, object],
    static_path: Path,
) -> Path:
    configured_path = payload.get("curves_config_path")
    if isinstance(configured_path, str) and configured_path.strip():
        candidate = Path(configured_path)
        if candidate.is_absolute():
            return candidate
        return (static_path.resolve().parent / candidate).resolve()
    return (static_path.resolve().parent / CURVES_CONFIG_FILENAME).resolve()


def _load_curves_by_id(curves_path: Path) -> Dict[int, InlineTableConfig]:
    payload = _load_config(curves_path)
    raw_curves = payload.get("curves")
    if not isinstance(raw_curves, list):
        raise ValueError(f"curves config must contain a 'curves' list: {curves_path}")
    curves_by_id: Dict[int, InlineTableConfig] = {}
    for item in raw_curves:
        if not isinstance(item, Mapping):
            raise ValueError(f"curve entry must be a mapping in {curves_path}")
        curve_id = int(item["id"])
        if curve_id in curves_by_id:
            raise ValueError(f"duplicate curve id {curve_id} in {curves_path}")
        table = _build_inline_table_config(item)
        if table is None or not table.columns or not table.rows:
            raise ValueError(f"curve id {curve_id} has empty columns/rows in {curves_path}")
        curves_by_id[curve_id] = table
    return curves_by_id


def _merge_mapping(base: Mapping[str, object], overrides: Mapping[str, object]) -> Dict[str, object]:
    merged = dict(base)
    for key, value in overrides.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = _merge_mapping(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_with_static_config(
    payload: Dict[str, object],
    runtime_config_path: Path,
    static_config_path: Optional[str] = None,
) -> Tuple[Dict[str, object], Path]:
    static_path = _resolve_static_config_path(payload, runtime_config_path, static_config_path)
    static_payload = _load_config(static_path)
    merged = _merge_mapping(static_payload, payload)
    merged.pop("static_config_path", None)
    return merged, static_path


def _build_station_config(
    payload: Dict,
    curves_by_id: Mapping[int, InlineTableConfig],
) -> StationConfig:
    units = [
        UnitConfig(
            id=unit["id"],
            name=unit["name"],
            remote_name=unit.get("remote_name"),
            q_min=unit.get("q_min"),
            q_max=unit.get("q_max"),
            table_e=_resolve_unit_table(unit, "table_e", "table_e_curve_id", curves_by_id),
            table_r=_resolve_unit_table(unit, "table_r", "table_r_curve_id", curves_by_id),
        )
        for unit in payload["units"]
    ]
    return StationConfig(
        id=payload["id"],
        name=payload["name"],
        level_back_min=payload["level_back_min"],
        level_back_max=payload["level_back_max"],
        level_front_min=payload["level_front_min"],
        level_front_max=payload["level_front_max"],
        num_units=payload["num_units"],
        units=units,
        units_file=payload.get("units_file", {}),
        remote_name=payload.get("remote_name"),
        front_level_key=payload.get("front_level_key"),
        back_level_key=payload.get("back_level_key"),
        hydro_front_node=payload.get("hydro_front_node"),
        hydro_back_node=payload.get("hydro_back_node"),
    )


def _build_inline_table_config(payload: object) -> Optional[InlineTableConfig]:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError(f"Inline table config must be a mapping, got {type(payload)!r}")
    columns = [str(column) for column in payload.get("columns", [])]
    rows_payload = payload.get("rows", [])
    if not isinstance(rows_payload, list):
        raise ValueError("Inline table rows must be a list")
    rows: List[List[float]] = []
    for row in rows_payload:
        if not isinstance(row, list):
            raise ValueError("Inline table row must be a list")
        rows.append([float(value) for value in row])
    return InlineTableConfig(columns=columns, rows=rows)


def _resolve_unit_table(
    unit: Mapping[str, object],
    inline_key: str,
    curve_id_key: str,
    curves_by_id: Mapping[int, InlineTableConfig],
) -> Optional[InlineTableConfig]:
    curve_id_value = unit.get(curve_id_key)
    if curve_id_value is not None:
        curve_id = int(curve_id_value)
        if curve_id not in curves_by_id:
            raise ValueError(
                f"unknown {curve_id_key}={curve_id} for unit {unit.get('id')}"
            )
        return curves_by_id[curve_id]
    return _build_inline_table_config(unit.get(inline_key))


def _inline_table_to_frame(table: InlineTableConfig, label: str) -> pd.DataFrame:
    if not table.columns:
        raise ValueError(f"{label} columns are empty")
    df = pd.DataFrame(table.rows, columns=table.columns)
    if df.empty:
        raise ValueError(f"{label} rows are empty")
    normalized = df.copy()
    for column in normalized.columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise")
    return normalized.reset_index(drop=True)


def build_demand_plan_columns(system_config: SystemConfig) -> List[str]:
    columns: List[str] = []
    station_ids = system_config.station_ids
    for upstream_station_id, downstream_station_id in zip(station_ids[:-1], station_ids[1:]):
        columns.append(f"station{upstream_station_id}-station{downstream_station_id}")
    return columns


def build_zero_demand_plan(
    system_config: SystemConfig,
    length: Optional[int] = None,
) -> pd.DataFrame:
    resolved_length = int(length if length is not None else system_config.horizon_hours)
    resolved_length = max(resolved_length, 1)
    columns = build_demand_plan_columns(system_config)
    return pd.DataFrame(0.0, index=range(resolved_length), columns=columns)


def _extract_runtime_overrides(
    payload: Mapping[str, object],
    valid_fields: Collection[str],
) -> Dict[str, object]:
    overrides: Dict[str, object] = {}
    for key, value in payload.items():
        if key in valid_fields:
            overrides[key] = value
        elif isinstance(value, Mapping):
            overrides.update(_extract_runtime_overrides(value, valid_fields))
    return overrides


def _runtime_from_payload(payload: Mapping[str, object]) -> RuntimeParameters:
    raw_runtime = payload.get("runtime", {})
    valid_fields = {field.name for field in fields(RuntimeParameters)}
    overrides = _extract_runtime_overrides(raw_runtime, valid_fields) if isinstance(raw_runtime, Mapping) else {}
    return RuntimeParameters(**overrides)



def _build_topology_config(payload: Mapping[str, object], stations: Sequence[StationConfig]) -> TopologyConfig:
    raw_topology = payload.get("topology", {})
    if not isinstance(raw_topology, Mapping):
        raw_topology = {}

    if raw_topology:
        boundary_nodes = [
            BoundaryNodeConfig(
                id=str(node["id"]),
                hydro_node=str(node["hydro_node"]),
                series_column=node.get("series_column"),
                mpc_key=node.get("mpc_key"),
            )
            for node in raw_topology.get("boundary_nodes", [])
        ]
        channel_segments = [
            ChannelSegmentConfig(
                id=str(segment["id"]),
                upstream_station_id=int(segment["upstream_station_id"]),
                downstream_station_id=int(segment["downstream_station_id"]),
                hydro_channel=str(segment["hydro_channel"]),
                hydro_profile_node=segment.get("hydro_profile_node"),
                disturbance_node=segment.get("disturbance_node"),
            )
            for segment in raw_topology.get("channel_segments", [])
        ]
        channel_groups = [
            ChannelGroupConfig(
                upstream_station_id=int(group["upstream_station_id"]),
                downstream_station_id=int(group["downstream_station_id"]),
                segment_ids=[str(segment_id) for segment_id in group.get("segment_ids", [])],
            )
            for group in raw_topology.get("channel_groups", [])
        ]
        return TopologyConfig(
            boundary_series_source=str(raw_topology.get("boundary_series_source", "file")).strip().lower(),
            boundary_nodes=boundary_nodes,
            channel_segments=channel_segments,
            channel_groups=channel_groups,
        )

    boundary_nodes: List[BoundaryNodeConfig] = []
    if stations:
        first = stations[0]
        last = stations[-1]
        if first.hydro_front_node:
            boundary_nodes.append(
                BoundaryNodeConfig(
                    id="upstream",
                    hydro_node=first.hydro_front_node,
                    series_column=first.hydro_front_node,
                    mpc_key="b0",
                )
            )
        if last.hydro_back_node:
            boundary_nodes.append(
                BoundaryNodeConfig(
                    id="downstream",
                    hydro_node=last.hydro_back_node,
                    series_column=last.hydro_back_node,
                    mpc_key=f"b{len(stations)}",
                )
            )

    channel_segments = []
    for idx in range(1, len(stations)):
        upstream = stations[idx - 1]
        downstream = stations[idx]
        channel_segments.append(
            ChannelSegmentConfig(
                id=f"pool_{idx}",
                upstream_station_id=upstream.id,
                downstream_station_id=downstream.id,
                hydro_channel=f"{upstream.name}->{downstream.name}",
                hydro_profile_node=f"{idx - 1}-{upstream.name}-{downstream.name}段",
                disturbance_node=f"disturbance_{idx}",
            )
        )

    channel_groups = [
        ChannelGroupConfig(
            upstream_station_id=stations[idx - 1].id,
            downstream_station_id=stations[idx].id,
            segment_ids=[f"pool_{idx}"],
        )
        for idx in range(1, len(stations))
    ]

    return TopologyConfig(
        boundary_series_source="file",
        boundary_nodes=boundary_nodes,
        channel_segments=channel_segments,
        channel_groups=channel_groups,
    )


def _system_config_from_payload(
    payload: Dict,
    config_path: Path,
    static_path: Optional[Path] = None,
    task_max_steps: Optional[int] = None,
    task_output_step_seconds: Optional[int] = None,
) -> SystemConfig:
    curves_path = _resolve_curves_config_path(payload, static_path or _default_static_config_path())
    curves_by_id = _load_curves_by_id(curves_path)
    stations = []
    raw_stations = payload["stations"]
    for item in raw_stations:
        station_payload = dict(item)
        station_id = station_payload.get("id")
        if not station_payload.get("hydro_front_node"):
            raise ValueError(
                f"station id={station_id} missing hydro_front_node (远程前池水位节点名)"
            )
        if not station_payload.get("hydro_back_node"):
            raise ValueError(
                f"station id={station_id} missing hydro_back_node (远程后池水位节点名)"
            )
        station_payload.setdefault(
            "remote_name",
            station_payload.get("name") or f"Station{station_id}",
        )
        # 水位节点 b0..bn 由 level_key_sequence 按站顺序自动推导，无需在配置中显式声明
        stations.append(_build_station_config(station_payload, curves_by_id))
    pools = [PoolConfig(**pool) for pool in payload["canal_pools"]]
    data_files = payload.get("data_files", {})
    raw_boundary_level = data_files.get("boundary_level", "data/boundary-level.xlsx")
    boundary_level_path = raw_boundary_level if isinstance(raw_boundary_level, str) else None
    hydro_model_path = data_files.get("hydro_model")
    flow_depart = payload.get("flow_depart", {})
    topology = _build_topology_config(payload, stations)
    scheduling = payload["scheduling"]
    raw_horizon_hours = task_max_steps
    if raw_horizon_hours is None:
        raw_horizon_hours = scheduling.get("horizon_hours")
    if raw_horizon_hours is None:
        raise ValueError("task max_steps is required for pump scheduling")

    horizon_hours = int(raw_horizon_hours)
    if horizon_hours <= 0:
        raise ValueError("task max_steps must be positive")

    raw_dt_hours = scheduling.get("dt_hours")
    if task_output_step_seconds is not None:
        raw_dt_hours = float(task_output_step_seconds) / 3600.0
    if raw_dt_hours is None:
        raise ValueError(
            "task output_step_seconds is required for pump scheduling"
        )

    dt_hours = float(raw_dt_hours)
    if dt_hours <= 0:
        raise ValueError("task output_step_seconds must be positive")

    return SystemConfig(
        project=payload["project"],
        description=payload["description"],
        rho=payload["global_params"]["rho"],
        g=payload["global_params"]["g"],
        horizon_hours=horizon_hours,
        dt_hours=dt_hours,
        target_avg_flow_last_station=scheduling["target_avg_flow_last_station"],
        stations=stations,
        canal_pools=pools,
        flow_depart_step_q=flow_depart["step_q"],
        flow_depart_step_h=flow_depart["step_h"],
        flow_depart_data_dir=flow_depart.get("data_dir", "data"),
        flow_depart_output_dir=flow_depart.get("output_dir", "output"),
        source_config_path=str(config_path),
        hydro_model_path=hydro_model_path,
        boundary_level_path=boundary_level_path,
        boundary_level_inline=_build_inline_table_config(raw_boundary_level) if not isinstance(raw_boundary_level, str) else None,
        topology=topology,
    )



def load_boundary_level_plan(
    data_path: Optional[str] = "data/boundary-level.xlsx",
    inline_table: Optional[InlineTableConfig] = None,
) -> pd.DataFrame:
    if inline_table is not None:
        return _inline_table_to_frame(inline_table, "boundary_level")
    if data_path is None:
        raise ValueError("Boundary level source is not configured")
    df = pd.read_excel(data_path)
    normalized = df.copy()
    for column in normalized.columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise")
    return normalized.reset_index(drop=True)


def load_system_config(config_path: str = "data/config.yaml") -> SystemConfig:
    path = Path(config_path)
    payload = _load_config(path)
    merged_payload, static_path = _merge_with_static_config(payload, path)
    return _system_config_from_payload(merged_payload, path, static_path=static_path)


def load_runtime_parameters(config_path: str = "data/config.yaml") -> RuntimeParameters:
    path = Path(config_path)
    payload = _load_config(path)
    merged_payload, _ = _merge_with_static_config(payload, path)
    return _runtime_from_payload(merged_payload)


def load_runtime_context(
    config_path: str = "data/config.yaml",
    demand_path: Optional[str] = None,
) -> Dict[str, object]:
    path = Path(config_path)
    payload = _load_config(path)
    return _runtime_context_from_payload(payload, path, demand_path)

def load_runtime_context_from_payload(
    payload: Dict[str, object],
    static_config_path: Optional[str] = None,
    task_max_steps: Optional[int] = None,
    task_output_step_seconds: Optional[int] = None,
) -> Dict[str, object]:
    return _runtime_context_from_payload(
        payload,
        Path("agent_config_memory"),
        None,
        static_config_path,
        task_max_steps,
        task_output_step_seconds,
    )

def _runtime_context_from_payload(
    payload: Dict[str, object], 
    path: Path,
    demand_path: Optional[str] = None,
    static_config_path: Optional[str] = None,
    task_max_steps: Optional[int] = None,
    task_output_step_seconds: Optional[int] = None,
) -> Dict[str, object]:
    del demand_path
    merged_payload, static_path = _merge_with_static_config(payload, path, static_config_path)
    system_config = _system_config_from_payload(
        merged_payload,
        path,
        static_path=static_path,
        task_max_steps=task_max_steps,
        task_output_step_seconds=task_output_step_seconds,
    )
    runtime = _runtime_from_payload(merged_payload)
    demand_plan = build_zero_demand_plan(system_config)

    return {
        "demand_plan": demand_plan,
        "system_config": system_config,
        "runtime": runtime,
        "config_payload": merged_payload,
    }


def runtime_to_dict(runtime: RuntimeParameters) -> Dict[str, object]:
    return asdict(runtime)
