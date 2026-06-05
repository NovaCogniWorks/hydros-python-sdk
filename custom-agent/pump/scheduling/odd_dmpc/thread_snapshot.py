from __future__ import annotations

import copy
import math
import re
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .types import AvailableUnitsMap, PoolProfileState, SystemConfig, ThreadSnapshotState


UNIT_KEY_RE = re.compile(r"^(.*?)(\d+)$")
WATER_LEVEL_TOLERANCE = 1e-3
FLOW_TOLERANCE = 1e-3


def _single_numeric_value(payload: Mapping[str, object], field_name: str, node_name: str) -> float:
    values = payload.get(field_name)
    if not isinstance(values, list) or not values:
        raise ValueError(f"Missing {field_name} for node {node_name}")
    if values[0] is None:
        raise ValueError(
            f"Node {node_name} returned null {field_name}; create_thread must be called with is_steady_state=true"
        )
    return float(values[0])


def _profile_integral(values: List[float], spacings: List[float], label: str) -> float:
    if len(values) < 2 or len(spacings) != len(values):
        raise ValueError(f"Invalid profile lengths for {label}")
    segment_lengths = [float(length) for length in spacings[1:]]
    if any(length < 0.0 for length in segment_lengths):
        raise ValueError(f"Negative segment length in {label}")
    integral = 0.0
    for idx, segment_length in enumerate(segment_lengths, start=1):
        integral += 0.5 * (float(values[idx - 1]) + float(values[idx])) * segment_length
    return float(integral)


def _trapezoidal_weighted_average(levels: List[float], spacings: List[float], label: str) -> float:
    total_length = sum(float(length) for length in spacings[1:])
    if total_length <= 0.0:
        raise ValueError(f"Zero total profile length for {label}")
    return float(_profile_integral(levels, spacings, label) / total_length)


def _representative_depth(
    levels: List[float],
    bed_elevations: List[float],
    spacings: List[float],
    label: str,
) -> float:
    depths = [max(float(level) - float(bed), 1.0e-6) for level, bed in zip(levels, bed_elevations)]
    representative_depth = _trapezoidal_weighted_average(depths, spacings, label)
    if representative_depth <= 0.0:
        raise ValueError(f"Invalid representative depth for {label}: {representative_depth}")
    return float(representative_depth)


def _assert_close(actual: float, expected: float, tol: float, label: str) -> None:
    if not math.isfinite(actual) or not math.isfinite(expected):
        raise ValueError(f"Non-finite value in {label}: {actual} vs {expected}")
    if abs(actual - expected) > tol:
        raise ValueError(f"{label} mismatch: {actual} vs {expected}")


def _dynamic_storage_area_from_profile(
    levels: List[float],
    bed_elevations: List[float],
    wet_areas: List[float],
    spacings: List[float],
    label: str,
) -> float:
    if not (len(levels) == len(bed_elevations) == len(wet_areas) == len(spacings)):
        raise ValueError(f"Inconsistent profile arrays for {label}")
    widths: List[float] = []
    for level, bed, area in zip(levels, bed_elevations, wet_areas):
        depth = max(float(level) - float(bed), 1.0e-3)
        widths.append(max(float(area), 0.0) / depth)
    storage_area = _profile_integral(widths, spacings, label)
    if storage_area <= 0.0:
        raise ValueError(f"Invalid storage area for {label}: {storage_area}")
    return float(storage_area)


def _equivalent_surface_area(reported_volume: float, representative_depth: float, label: str) -> float:
    if representative_depth <= 0.0:
        raise ValueError(f"Invalid representative depth for {label}: {representative_depth}")
    surface_area = float(reported_volume) / float(representative_depth)
    if surface_area <= 0.0:
        raise ValueError(f"Invalid equivalent surface area for {label}: {surface_area}")
    return float(surface_area)


def _parse_pool_profile(node: Mapping[str, object], pool_id: int, label: str) -> PoolProfileState:
    required_fields = ["水体体积", "断面间距", "渠底高程", "水位", "流量", "过水面积"]
    for field_name in required_fields:
        if field_name not in node:
            raise ValueError(f"Missing {field_name} for {label}")
    spacings = [float(value) for value in node["断面间距"]]
    bed_elevations = [float(value) for value in node["渠底高程"]]
    water_levels = [float(value) for value in node["水位"]]
    section_flows = [float(value) for value in node["流量"]]
    wet_areas = [float(value) for value in node["过水面积"]]
    if not (len(spacings) == len(bed_elevations) == len(water_levels) == len(section_flows) == len(wet_areas)):
        raise ValueError(f"Inconsistent profile array lengths for {label}")
    reported_volume = _single_numeric_value(node, "水体体积", label)
    representative_level = _trapezoidal_weighted_average(water_levels, spacings, label)
    representative_depth = _representative_depth(water_levels, bed_elevations, spacings, label)
    computed_volume = _profile_integral(wet_areas, spacings, label)
    raw_surface_area = _dynamic_storage_area_from_profile(
        water_levels,
        bed_elevations,
        wet_areas,
        spacings,
        label,
    )
    storage_area = _equivalent_surface_area(reported_volume, representative_depth, label)
    return PoolProfileState(
        pool_id=pool_id,
        name=label,
        spacings=spacings,
        bed_elevations=bed_elevations,
        water_levels=water_levels,
        section_flows=section_flows,
        wet_areas=wet_areas,
        representative_level=float(representative_level),
        representative_depth=float(representative_depth),
        reported_volume=float(reported_volume),
        computed_volume=float(computed_volume),
        volume_offset=float(reported_volume - computed_volume),
        raw_surface_area=float(raw_surface_area),
        storage_area=float(storage_area),
    )


def _station_remote_name(station) -> str:
    return str(getattr(station, "remote_name", None) or station.name)


def _station_front_node(station) -> Optional[str]:
    return getattr(station, "hydro_front_node", None)


def _station_back_node(station) -> Optional[str]:
    return getattr(station, "hydro_back_node", None)


def _station_front_key(station, fallback: str) -> str:
    return str(getattr(station, "front_level_key", None) or fallback)


def _station_back_key(station, fallback: str) -> str:
    return str(getattr(station, "back_level_key", None) or fallback)


def _boundary_nodes(system_config: SystemConfig) -> List[object]:
    return list(getattr(system_config.topology, "boundary_nodes", []) or [])


def _channel_segments(system_config: SystemConfig) -> List[object]:
    return list(getattr(system_config.topology, "channel_segments", []) or [])


def _channel_groups(system_config: SystemConfig) -> List[object]:
    return list(getattr(system_config.topology, "channel_groups", []) or [])


def _profile_total_length(profile: PoolProfileState) -> float:
    return float(sum(float(length) for length in profile.spacings[1:]))


def _build_pool_profile_groups(system_config: SystemConfig) -> List[Tuple[int, str, List[object]]]:
    pool_ids = [int(pool_id) for pool_id in system_config.pool_ids]
    pool_name_by_id = {int(pool.id): str(pool.name) for pool in system_config.canal_pools}
    channel_groups = _channel_groups(system_config)
    segment_map = getattr(system_config.topology, "segment_map", {})

    if channel_groups:
        if pool_ids and len(pool_ids) != len(channel_groups):
            raise ValueError("Configured canal_pools count does not match topology.channel_groups count")
        grouped_profiles: List[Tuple[int, str, List[object]]] = []
        for idx, group in enumerate(channel_groups, start=1):
            pool_id = pool_ids[idx - 1] if idx - 1 < len(pool_ids) else idx
            segments: List[object] = []
            for segment_id in getattr(group, "segment_ids", []):
                segment = segment_map.get(str(segment_id))
                if segment is None:
                    raise ValueError(f"Unknown channel segment in group mapping: {segment_id}")
                segments.append(segment)
            if not segments:
                raise ValueError(
                    f"Channel group {group.upstream_station_id}->{group.downstream_station_id} has no segments"
                )
            pool_name = pool_name_by_id.get(
                int(pool_id),
                f"Pool {pool_id} ({group.upstream_station_id}->{group.downstream_station_id})",
            )
            grouped_profiles.append((int(pool_id), pool_name, segments))
        return grouped_profiles

    channel_segments = _channel_segments(system_config)
    if pool_ids and len(pool_ids) != len(channel_segments):
        raise ValueError("Configured canal_pools count does not match topology.channel_segments count")
    grouped_profiles = []
    for idx, segment in enumerate(channel_segments, start=1):
        pool_id = pool_ids[idx - 1] if idx - 1 < len(pool_ids) else idx
        pool_name = pool_name_by_id.get(
            int(pool_id),
            f"Pool {pool_id} ({segment.upstream_station_id}->{segment.downstream_station_id})",
        )
        grouped_profiles.append((int(pool_id), pool_name, [segment]))
    return grouped_profiles


def _aggregate_pool_profile(
    pool_id: int,
    label: str,
    segment_profiles: Sequence[PoolProfileState],
) -> PoolProfileState:
    if not segment_profiles:
        raise ValueError(f"Cannot aggregate empty profile group for {label}")
    if len(segment_profiles) == 1:
        profile = copy.deepcopy(segment_profiles[0])
        profile.pool_id = int(pool_id)
        profile.name = label
        return profile

    total_length = sum(_profile_total_length(profile) for profile in segment_profiles)
    if total_length <= 0.0:
        total_length = float(len(segment_profiles))

    total_volume = sum(float(profile.reported_volume) for profile in segment_profiles)
    total_storage_area = sum(float(profile.storage_area) for profile in segment_profiles)
    if total_storage_area <= 0.0:
        raise ValueError(f"Invalid aggregated storage area for {label}")

    weighted_lengths = [max(_profile_total_length(profile), 1.0) for profile in segment_profiles]
    weighted_level = sum(
        float(profile.representative_level) * weight
        for profile, weight in zip(segment_profiles, weighted_lengths)
    ) / sum(weighted_lengths)
    representative_depth = total_volume / total_storage_area
    if representative_depth <= 0.0:
        raise ValueError(f"Invalid aggregated representative depth for {label}")

    bed_level = float(weighted_level - representative_depth)
    section_area = float(total_volume / total_length)

    # 将串联河段折叠为一个合成河段，同时为上层 MPC 状态模型
    # 保留总库容和总蓄水面积。
    return PoolProfileState(
        pool_id=int(pool_id),
        name=label,
        spacings=[0.0, float(total_length)],
        bed_elevations=[bed_level, bed_level],
        water_levels=[float(weighted_level), float(weighted_level)],
        section_flows=[0.0, 0.0],
        wet_areas=[section_area, section_area],
        representative_level=float(weighted_level),
        representative_depth=float(representative_depth),
        reported_volume=float(total_volume),
        computed_volume=float(total_volume),
        volume_offset=0.0,
        raw_surface_area=float(total_storage_area),
        storage_area=float(total_storage_area),
    )


def _normalized_station_tokens(value: object) -> Set[str]:
    if value is None:
        return set()
    text = str(value).strip()
    if not text:
        return set()

    candidates: Set[str] = set()

    def _add(token: str) -> None:
        token = str(token).strip()
        if not token or token.isdigit():
            return
        candidates.add(token)
        compact = re.sub(r"[\s\-_]+", "", token)
        if compact and not compact.isdigit():
            candidates.add(compact)
        if token.endswith("站") and len(token) > 1:
            stationless = token[:-1].strip()
            if stationless:
                candidates.add(stationless)
                compact_stationless = re.sub(r"[\s\-_]+", "", stationless)
                if compact_stationless:
                    candidates.add(compact_stationless)

    _add(text)

    trimmed_prefix = re.sub(r"^[A-Za-z0-9]+-", "", text)
    trimmed_suffix = re.sub(r"-\d+$", "", trimmed_prefix).strip("-_ ")
    _add(trimmed_prefix)
    _add(trimmed_suffix)

    parts = [part.strip() for part in re.split(r"[-_]", text) if str(part).strip()]
    if parts:
        _add("".join(parts))
        if len(parts) >= 2:
            if not parts[-1].isdigit():
                _add(parts[-1])
        if len(parts) >= 3:
            middle = "".join(parts[1:-1]).strip()
            _add(middle)
            _add("-".join(parts[1:-1]).strip())

    return {token for token in candidates if token}


def _station_alias_map(system_config: SystemConfig) -> Dict[str, int]:
    aliases: Dict[str, int] = {}
    for station in system_config.stations:
        station_id = int(station.id)
        for raw_value in (
            getattr(station, "remote_name", None),
            getattr(station, "name", None),
            getattr(station, "hydro_front_node", None),
            getattr(station, "hydro_back_node", None),
        ):
            for alias in _normalized_station_tokens(raw_value):
                aliases.setdefault(alias, station_id)
    return aliases


def _unit_remote_name_map(system_config: SystemConfig) -> Dict[str, tuple[int, int]]:
    unit_names: Dict[str, tuple[int, int]] = {}
    for station in system_config.stations:
        station_name = _station_remote_name(station)
        for unit in station.units:
            remote_names = [str(unit.remote_name)] if unit.remote_name else []
            remote_names.append(f"{station_name}{unit.id}")
            for raw_name in remote_names:
                raw_name = str(raw_name).strip()
                if not raw_name:
                    continue
                unit_names.setdefault(raw_name, (int(station.id), int(unit.id)))
    return unit_names


def parse_thread_snapshot(payload: Mapping[str, object], system_config: SystemConfig) -> ThreadSnapshotState:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("Thread response missing 'result'")
    thread_uuid = str(payload.get("uuid", ""))
    if not thread_uuid:
        raise ValueError("Thread response missing 'uuid'")

    stations = system_config.stations
    if not stations:
        raise ValueError("System config contains no stations")
    level_keys = list(system_config.level_key_sequence)
    if len(level_keys) != len(stations) + 1:
        level_keys = [f"b{i}" for i in range(len(stations) + 1)]

    boundary_nodes = _boundary_nodes(system_config)
    upstream_station = stations[0]
    downstream_station = stations[-1]
    upstream_boundary_node = boundary_nodes[0].hydro_node if boundary_nodes else _station_front_node(upstream_station)
    downstream_boundary_node = boundary_nodes[-1].hydro_node if boundary_nodes else _station_back_node(downstream_station)
    if upstream_boundary_node is None or downstream_boundary_node is None:
        raise ValueError("Boundary node mapping is incomplete")

    upstream_boundary_key = str(boundary_nodes[0].mpc_key or _station_front_key(upstream_station, "b0")) if boundary_nodes else _station_front_key(upstream_station, "b0")
    downstream_boundary_key = str(boundary_nodes[-1].mpc_key or _station_back_key(downstream_station, f"b{len(stations)}")) if boundary_nodes else _station_back_key(downstream_station, f"b{len(stations)}")

    boundary_levels = {
        upstream_boundary_key: _single_numeric_value(result[upstream_boundary_node], "水位", upstream_boundary_node),
        downstream_boundary_key: _single_numeric_value(result[downstream_boundary_node], "水位", downstream_boundary_node),
    }

    station_front_levels: Dict[int, float] = {}
    station_back_levels: Dict[int, float] = {}
    for station in stations:
        front_node = _station_front_node(station)
        back_node = _station_back_node(station)
        if front_node is None or back_node is None:
            raise ValueError(f"Missing hydro node mapping for station {station.id}")
        station_front_levels[station.id] = _single_numeric_value(result[front_node], "水位", front_node)
        station_back_levels[station.id] = _single_numeric_value(result[back_node], "水位", back_node)

    pool_profiles: Dict[int, PoolProfileState] = {}
    for pool_id, pool_name, grouped_segments in _build_pool_profile_groups(system_config):
        segment_profiles: List[PoolProfileState] = []
        for segment in grouped_segments:
            profile_node = getattr(segment, "hydro_profile_node", None)
            if profile_node is None:
                raise ValueError(
                    f"Missing hydro_profile_node for pool group {pool_name}: "
                    f"{segment.upstream_station_id}->{segment.downstream_station_id}"
                )
            if profile_node not in result:
                raise ValueError(f"Missing channel profile node in snapshot: {profile_node}")
            segment_profiles.append(_parse_pool_profile(result[profile_node], pool_id, profile_node))
        pool_profiles[pool_id] = _aggregate_pool_profile(pool_id, pool_name, segment_profiles)

    for idx, segment in []:  # 旧版逐分段路径已故意禁用
        profile_node = getattr(segment, "hydro_profile_node", None)
        if profile_node is None:
            profile_node = f"{idx - 1}-{segment.upstream_station_id}-{segment.downstream_station_id}段"
        if profile_node not in result:
            raise ValueError(f"Missing channel profile node in snapshot: {profile_node}")
        pool_profiles[idx] = _parse_pool_profile(result[profile_node], idx, profile_node)

    basin_levels = {level_keys[0]: boundary_levels[upstream_boundary_key]}
    basin_volumes: Dict[int, float] = {}
    pool_areas: Dict[int, float] = {}
    for idx, profile in pool_profiles.items():
        if idx < len(level_keys):
            basin_levels[level_keys[idx]] = float(profile.representative_level)
        else:
            basin_levels[f"b{idx}"] = float(profile.representative_level)
        basin_volumes[idx] = float(profile.reported_volume)
        pool_areas[idx] = float(profile.storage_area)
    basin_levels[level_keys[-1]] = boundary_levels[downstream_boundary_key]

    unit_status: Dict[int, Dict[int, int]] = {
        station.id: {unit.id: 0 for unit in station.units}
        for station in stations
    }
    unit_openings: Dict[int, Dict[int, float]] = {
        station.id: {unit.id: 0.0 for unit in station.units}
        for station in stations
    }
    unit_flows: Dict[int, Dict[int, float]] = {
        station.id: {unit.id: 0.0 for unit in station.units}
        for station in stations
    }
    unit_front_levels: Dict[int, Dict[int, float]] = {
        station.id: {unit.id: 0.0 for unit in station.units}
        for station in stations
    }
    unit_back_levels: Dict[int, Dict[int, float]] = {
        station.id: {unit.id: 0.0 for unit in station.units}
        for station in stations
    }

    external_name_to_station_id = {
        _station_remote_name(station): station.id
        for station in stations
    }
    station_aliases = _station_alias_map(system_config)
    remote_unit_name_map = _unit_remote_name_map(system_config)
    for key, node in result.items():
        if not isinstance(node, Mapping):
            continue

        exact_unit_match = remote_unit_name_map.get(str(key).strip())
        if exact_unit_match is not None:
            station_id, unit_id = exact_unit_match
        else:
            match = UNIT_KEY_RE.match(str(key))
            if match is None:
                continue
            external_station_name, unit_suffix = match.groups()
            normalized_external_name = external_station_name.strip("-_ ")
            station_id = external_name_to_station_id.get(external_station_name)
            if station_id is None:
                station_id = external_name_to_station_id.get(normalized_external_name)
            if station_id is None:
                for alias in _normalized_station_tokens(external_station_name):
                    station_id = station_aliases.get(alias)
                    if station_id is not None:
                        break
            if station_id is None:
                continue
            unit_id = int(unit_suffix)

        pair_fields = [
            value
            for value in node.values()
            if isinstance(value, list) and len(value) == 2
        ]
        scalar_fields = [
            value
            for value in node.values()
            if isinstance(value, list) and len(value) == 1
        ]
        if len(pair_fields) < 2 or not scalar_fields:
            continue

        expected_front = float(station_front_levels[station_id])
        expected_back = float(station_back_levels[station_id])
        water_levels = None
        flows = None
        for values in pair_fields:
            candidate_front = min(float(values[0]), float(values[1]))
            candidate_back = max(float(values[0]), float(values[1]))
            if (
                abs(candidate_front - expected_front) <= 1.0
                and abs(candidate_back - expected_back) <= 1.0
            ):
                water_levels = values
            else:
                flows = values
        if water_levels is None:
            water_levels = pair_fields[0]
        if flows is None:
            for values in pair_fields:
                if values is not water_levels:
                    flows = values
                    break
        operating_point = scalar_fields[0]
        if flows is None:
            continue

        if unit_id not in system_config.station_by_id[station_id].unit_name_by_id:
            continue
        if not isinstance(water_levels, list) or len(water_levels) != 2:
            raise ValueError(f"Invalid water levels for {key}")
        if not isinstance(flows, list) or len(flows) != 2:
            raise ValueError(f"Invalid flows for {key}")
        if abs(float(flows[0]) - float(flows[1])) > FLOW_TOLERANCE:
            raise ValueError(f"Inconsistent duplicated flow values for {key}: {flows}")
        if not isinstance(operating_point, list) or len(operating_point) != 1:
            raise ValueError(f"Invalid operating point for {key}")

        front_level = min(float(water_levels[0]), float(water_levels[1]))
        back_level = max(float(water_levels[0]), float(water_levels[1]))
        unit_front_levels[station_id][unit_id] = front_level
        unit_back_levels[station_id][unit_id] = back_level

        opening = float(operating_point[0])
        raw_flow = float(flows[0])
        if abs(opening - 100.0) <= 1e-9:
            unit_status[station_id][unit_id] = 0
            unit_openings[station_id][unit_id] = 0.0
            unit_flows[station_id][unit_id] = 0.0
        else:
            unit_status[station_id][unit_id] = 1
            unit_openings[station_id][unit_id] = opening
            unit_flows[station_id][unit_id] = raw_flow

    station_total_flows = {
        station_id: float(sum(unit_flows[station_id].values()))
        for station_id in unit_flows
    }
    available_units_map: AvailableUnitsMap = {
        station.id: [unit.id for unit in station.units]
        for station in stations
    }

    for station in stations:
        front_node = _station_front_node(station)
        back_node = _station_back_node(station)
        if front_node is not None and front_node in result:
            _assert_close(
                station_front_levels[station.id],
                _single_numeric_value(result[front_node], "水位", front_node),
                WATER_LEVEL_TOLERANCE,
                f"Station{station.id} front level",
            )
        if back_node is not None and back_node in result:
            _assert_close(
                station_back_levels[station.id],
                _single_numeric_value(result[back_node], "水位", back_node),
                WATER_LEVEL_TOLERANCE,
                f"Station{station.id} back level",
            )

    return ThreadSnapshotState(
        thread_uuid=thread_uuid,
        boundary_levels=boundary_levels,
        basin_levels=basin_levels,
        basin_volumes=basin_volumes,
        pool_areas=pool_areas,
        basin_profiles=pool_profiles,
        station_front_levels=station_front_levels,
        station_back_levels=station_back_levels,
        station_total_flows=station_total_flows,
        unit_status=unit_status,
        unit_openings=unit_openings,
        unit_flows=unit_flows,
        unit_front_levels=unit_front_levels,
        unit_back_levels=unit_back_levels,
        available_units_map=available_units_map,
        raw_result=result,
    )
