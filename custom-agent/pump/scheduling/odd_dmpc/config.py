from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path
from typing import Collection, Dict, List, Mapping, Optional, Sequence

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


DEFAULT_REMOTE_STATION_NAMES = {
    1: "泗洪站",
    2: "睢宁二站",
    3: "邳州站",
}

DEFAULT_STATION_NODES = {
    1: {"front": "0-洪泽湖", "back": "1-泗洪站下游"},
    2: {"front": "2-睢宁二站上游", "back": "3-睢宁二站下游"},
    3: {"front": "4-邳州站上游", "back": "5-骆马湖"},
}

DEFAULT_BOUNDARY_COLUMNS = {
    1: "洪泽湖",
    3: "骆马湖",
}


def _load_config(config_path: Path) -> Dict:
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid config payload in {config_path}")
    return payload


def _build_station_config(payload: Dict) -> StationConfig:
    units = [
        UnitConfig(
            id=unit["id"],
            name=unit["name"],
            remote_name=unit.get("remote_name"),
            q_min=unit.get("q_min"),
            q_max=unit.get("q_max"),
            table_e=_build_inline_table_config(unit.get("table_e")),
            table_r=_build_inline_table_config(unit.get("table_r")),
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


def _default_station_topology_fields(station_id: int, station_count: int) -> Dict[str, str]:
    remote_name = DEFAULT_REMOTE_STATION_NAMES.get(station_id, f"Station{station_id}")
    if station_id in DEFAULT_STATION_NODES:
        nodes = DEFAULT_STATION_NODES[station_id]
        return {
            "remote_name": remote_name,
            "front_level_key": f"b{station_id - 1}",
            "back_level_key": f"b{station_id}",
            "hydro_front_node": nodes["front"],
            "hydro_back_node": nodes["back"],
        }
    return {
        "remote_name": remote_name,
        "front_level_key": f"b{station_id - 1}",
        "back_level_key": f"b{station_id}",
        "hydro_front_node": f"NODE-{station_id - 1}-FRONT",
        "hydro_back_node": f"NODE-{station_id}-BACK",
    }


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
    for station in stations:
        if station.front_level_key is None or station.hydro_front_node is None:
            continue
        if station.id == stations[0].id:
            boundary_nodes.append(
                BoundaryNodeConfig(
                    id="upstream",
                    hydro_node=station.hydro_front_node,
                    series_column=DEFAULT_BOUNDARY_COLUMNS.get(station.id, station.hydro_front_node),
                    mpc_key=station.front_level_key,
                )
            )
        if station.id == stations[-1].id:
            boundary_nodes.append(
                BoundaryNodeConfig(
                    id="downstream",
                    hydro_node=station.hydro_back_node or "",
                    series_column=DEFAULT_BOUNDARY_COLUMNS.get(station.id, station.hydro_back_node or ""),
                    mpc_key=station.back_level_key,
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


def _system_config_from_payload(payload: Dict, config_path: Path) -> SystemConfig:
    stations = []
    raw_stations = payload["stations"]
    for idx, item in enumerate(raw_stations, start=1):
        station_payload = dict(item)
        defaults = _default_station_topology_fields(station_payload["id"], len(raw_stations))
        station_payload.setdefault("remote_name", defaults["remote_name"])
        station_payload.setdefault("front_level_key", defaults["front_level_key"])
        station_payload.setdefault("back_level_key", defaults["back_level_key"])
        station_payload.setdefault("hydro_front_node", defaults["hydro_front_node"])
        station_payload.setdefault("hydro_back_node", defaults["hydro_back_node"])
        stations.append(_build_station_config(station_payload))
    pools = [PoolConfig(**pool) for pool in payload["canal_pools"]]
    data_files = payload.get("data_files", {})
    raw_boundary_level = data_files.get("boundary_level", "data/boundary-level.xlsx")
    boundary_level_path = raw_boundary_level if isinstance(raw_boundary_level, str) else None
    hydro_model_path = data_files.get("hydro_model")
    topology = _build_topology_config(payload, stations)
    return SystemConfig(
        project=payload["project"],
        description=payload["description"],
        rho=payload["global_params"]["rho"],
        g=payload["global_params"]["g"],
        horizon_hours=payload["scheduling"]["horizon_hours"],
        dt_hours=payload["scheduling"]["dt_hours"],
        target_avg_flow_last_station=payload["scheduling"]["target_avg_flow_last_station"],
        stations=stations,
        canal_pools=pools,
        flow_depart_step_q=payload["flow_depart"]["step_q"],
        flow_depart_step_h=payload["flow_depart"]["step_h"],
        flow_depart_data_dir=payload["flow_depart"]["data_dir"],
        flow_depart_output_dir=payload["flow_depart"]["output_dir"],
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
    if list(df.columns) != ["洪泽湖", "骆马湖"]:
        raise ValueError(f"Unexpected boundary level columns: {list(df.columns)}")
    normalized = df.copy()
    normalized["洪泽湖"] = pd.to_numeric(normalized["洪泽湖"], errors="raise")
    normalized["骆马湖"] = pd.to_numeric(normalized["骆马湖"], errors="raise")
    return normalized.reset_index(drop=True)


def load_system_config(config_path: str = "data/config.yaml") -> SystemConfig:
    path = Path(config_path)
    payload = _load_config(path)
    return _system_config_from_payload(payload, path)


def load_runtime_parameters(config_path: str = "data/config.yaml") -> RuntimeParameters:
    path = Path(config_path)
    payload = _load_config(path)
    return _runtime_from_payload(payload)


def load_runtime_context(
    config_path: str = "data/config.yaml",
    demand_path: Optional[str] = None,
) -> Dict[str, object]:
    path = Path(config_path)
    payload = _load_config(path)
    return _runtime_context_from_payload(payload, path, demand_path)

def load_runtime_context_from_payload(payload: Dict[str, object]) -> Dict[str, object]:
    return _runtime_context_from_payload(payload, Path("agent_config_memory"), None)

def _runtime_context_from_payload(
    payload: Dict[str, object], 
    path: Path,
    demand_path: Optional[str] = None
) -> Dict[str, object]:
    del demand_path
    system_config = _system_config_from_payload(payload, path)
    runtime = _runtime_from_payload(payload)

    output_dir = Path(runtime.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "system_config": system_config,
        "runtime": runtime,
    }


def runtime_to_dict(runtime: RuntimeParameters) -> Dict[str, object]:
    return asdict(runtime)
