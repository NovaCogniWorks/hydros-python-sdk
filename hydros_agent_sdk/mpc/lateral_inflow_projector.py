"""Project rainstorm channel inflows onto MPC-supported disturbance nodes."""

from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, List, Mapping, Optional, Set

from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.utils import WaterwayTopology


class MpcLateralInflowProjectionError(RuntimeError):
    """Raised when a rainstorm channel cannot be mapped to one MPC injection node."""


class MpcLateralInflowProjector:
    """Project channel-level rainstorm inflows before the planning HTTP boundary."""

    UNIFIED_CANAL = "UnifiedCanal"
    GATE_STATION = "GateStation"
    DISTURBANCE_NODE = "DisturbanceNode"

    @classmethod
    def project_for_task(
        cls,
        task_state,
        source_boundaries: Mapping[str, List[float]],
        rainstorm_source_object_ids: Iterable[str],
        prediction_horizon: int,
    ) -> Dict[str, List[float]]:
        rainstorm_ids = set(rainstorm_source_object_ids or [])
        if not source_boundaries or not rainstorm_ids:
            return dict(source_boundaries)

        model_context = ContextManager.get_context(task_state.context)
        topology = getattr(model_context, "topology", None) if model_context is not None else None
        if topology is None:
            raise MpcLateralInflowProjectionError(
                "暴雨渠道旁侧入流缺少 Python central 完整水网拓扑上下文, "
                f"bizSceneInstanceId={task_state.context.biz_scene_instance_id}"
            )
        return cls.project(
            source_boundaries,
            rainstorm_ids,
            topology,
            prediction_horizon,
        )

    @classmethod
    def project(
        cls,
        source_boundaries: Mapping[str, List[float]],
        rainstorm_source_object_ids: Iterable[str],
        topology: WaterwayTopology,
        prediction_horizon: int,
    ) -> Dict[str, List[float]]:
        projected: Dict[str, List[float]] = {}
        rainstorm_ids = set(rainstorm_source_object_ids or [])
        for source_object_id, values in source_boundaries.items():
            target_object_id = source_object_id
            if source_object_id in rainstorm_ids:
                parsed_source_id = cls._parse_object_id(source_object_id)
                source_object = topology.get_object(parsed_source_id)
                if source_object is None:
                    raise MpcLateralInflowProjectionError(
                        f"暴雨旁侧入流渠道不在完整水网拓扑中, objectId={parsed_source_id}"
                    )
                if getattr(source_object, "object_type", None) != cls.UNIFIED_CANAL:
                    raise MpcLateralInflowProjectionError(
                        "暴雨旁侧入流对象不是 UnifiedCanal, "
                        f"objectId={parsed_source_id}, "
                        f"objectType={getattr(source_object, 'object_type', None)}"
                    )
                target_object_id = str(
                    cls.find_rainstorm_injection_node(topology, parsed_source_id)
                )
            cls._merge_boundary_series(
                projected,
                target_object_id,
                values,
                prediction_horizon,
            )
        return projected

    @classmethod
    def find_rainstorm_injection_node(
        cls,
        topology: WaterwayTopology,
        source_channel_id: int,
    ) -> int:
        downstream_target = cls._find_nearest_disturbance_within_adjacent_gate_interval(
            topology,
            source_channel_id,
            downstream=True,
        )
        if downstream_target is not None:
            return downstream_target

        upstream_target = cls._find_nearest_disturbance_within_adjacent_gate_interval(
            topology,
            source_channel_id,
            downstream=False,
        )
        if upstream_target is not None:
            return upstream_target

        raise MpcLateralInflowProjectionError(
            "当前渠段相邻上下游 GateStation 区间均找不到 DisturbanceNode, "
            f"channelId={source_channel_id}"
        )

    @classmethod
    def _find_nearest_disturbance_within_adjacent_gate_interval(
        cls,
        topology: WaterwayTopology,
        source_channel_id: int,
        downstream: bool,
    ) -> Optional[int]:
        distance_from_source = {source_channel_id: 0}
        shortest_predecessors: Dict[int, Set[int]] = {}
        queue = deque([source_channel_id])
        nearest_gate_distance: Optional[int] = None
        nearest_gate_stations: Set[int] = set()

        while queue:
            current_id = queue.popleft()
            current_distance = distance_from_source[current_id]
            if nearest_gate_distance is not None and current_distance >= nearest_gate_distance:
                continue

            neighbors = topology.find_neighbors(current_id)
            direction = "downstream" if downstream else "upstream"
            for adjacent_object_id in neighbors.get(direction, []):
                adjacent_distance = current_distance + 1
                known_distance = distance_from_source.get(adjacent_object_id)
                if known_distance is None or adjacent_distance < known_distance:
                    distance_from_source[adjacent_object_id] = adjacent_distance
                    shortest_predecessors[adjacent_object_id] = {current_id}
                    queue.append(adjacent_object_id)
                elif adjacent_distance == known_distance:
                    shortest_predecessors.setdefault(adjacent_object_id, set()).add(current_id)
                else:
                    continue

                if cls._is_object_type(topology, adjacent_object_id, cls.GATE_STATION):
                    if nearest_gate_distance is None or adjacent_distance < nearest_gate_distance:
                        nearest_gate_distance = adjacent_distance
                        nearest_gate_stations.clear()
                    if adjacent_distance == nearest_gate_distance:
                        nearest_gate_stations.add(adjacent_object_id)

        if not nearest_gate_stations:
            return None
        if len(nearest_gate_stations) > 1:
            direction_name = "下游" if downstream else "上游"
            raise MpcLateralInflowProjectionError(
                f"渠道{direction_name}存在多个等距的相邻 GateStation, "
                f"channelId={source_channel_id}, candidates={sorted(nearest_gate_stations)}"
            )

        adjacent_gate_station_id = next(iter(nearest_gate_stations))
        shortest_path_nodes = cls._collect_shortest_path_nodes(
            adjacent_gate_station_id,
            shortest_predecessors,
        )
        nearest_disturbance_distance: Optional[int] = None
        nearest_disturbance_nodes: Set[int] = set()
        for path_node_id in shortest_path_nodes:
            if not cls._is_object_type(topology, path_node_id, cls.DISTURBANCE_NODE):
                continue
            distance = distance_from_source[path_node_id]
            if nearest_disturbance_distance is None or distance < nearest_disturbance_distance:
                nearest_disturbance_distance = distance
                nearest_disturbance_nodes.clear()
            if distance == nearest_disturbance_distance:
                nearest_disturbance_nodes.add(path_node_id)

        if not nearest_disturbance_nodes:
            return None
        if len(nearest_disturbance_nodes) > 1:
            direction_name = "下游" if downstream else "上游"
            raise MpcLateralInflowProjectionError(
                f"当前渠段{direction_name}存在多个等距的最近 DisturbanceNode, "
                f"channelId={source_channel_id}, "
                f"adjacentGateStationId={adjacent_gate_station_id}, "
                f"candidates={sorted(nearest_disturbance_nodes)}"
            )
        return next(iter(nearest_disturbance_nodes))

    @staticmethod
    def _collect_shortest_path_nodes(
        target_id: int,
        shortest_predecessors: Mapping[int, Set[int]],
    ) -> Set[int]:
        path_nodes: Set[int] = set()
        queue = deque([target_id])
        while queue:
            current_id = queue.popleft()
            if current_id in path_nodes:
                continue
            path_nodes.add(current_id)
            queue.extend(shortest_predecessors.get(current_id, set()))
        return path_nodes

    @staticmethod
    def _is_object_type(
        topology: WaterwayTopology,
        object_id: int,
        expected_type: str,
    ) -> bool:
        hydro_object = topology.get_object(object_id)
        return hydro_object is not None and getattr(hydro_object, "object_type", None) == expected_type

    @staticmethod
    def _parse_object_id(raw_object_id: str) -> int:
        try:
            return int(raw_object_id)
        except (TypeError, ValueError) as exc:
            raise MpcLateralInflowProjectionError(
                f"旁侧入流对象ID必须为整数, objectId={raw_object_id}"
            ) from exc

    @classmethod
    def _merge_boundary_series(
        cls,
        projected: Dict[str, List[float]],
        target_object_id: str,
        incoming: List[float],
        prediction_horizon: int,
    ) -> None:
        existing = projected.get(target_object_id)
        if existing is None:
            projected[target_object_id] = incoming
            return

        normalized_existing = cls._normalize_series(existing, prediction_horizon)
        normalized_incoming = cls._normalize_series(incoming, prediction_horizon)
        projected[target_object_id] = [
            normalized_existing[index] + normalized_incoming[index]
            for index in range(prediction_horizon)
        ]

    @staticmethod
    def _normalize_series(source: List[float], prediction_horizon: int) -> List[float]:
        if not source:
            return [0.0] * prediction_horizon

        last_value = float(source[0]) if source[0] is not None else 0.0
        normalized: List[float] = []
        for index in range(prediction_horizon):
            if index < len(source) and source[index] is not None:
                last_value = float(source[index])
            normalized.append(last_value)
        return normalized
