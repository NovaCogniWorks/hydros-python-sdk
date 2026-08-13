import unittest

from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.mpc.client import MpcPlanningClient
from hydros_agent_sdk.mpc.lateral_inflow_projector import (
    MpcLateralInflowProjectionError,
    MpcLateralInflowProjector,
)
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import (
    ObjectTimeSeries,
    SimulationContext,
    TimeSeriesValue,
)
from hydros_agent_sdk.utils import TopHydroObject, WaterwayTopology


def build_topology(objects, *edges):
    upstream_map = {}
    downstream_map = {}
    for from_id, to_id in edges:
        downstream_map.setdefault(from_id, []).append(to_id)
        upstream_map.setdefault(to_id, []).append(from_id)
    return WaterwayTopology(
        topObjects=[
            TopHydroObject(
                objectId=object_id,
                objectType=object_type,
                objectName=f"{object_type}-{object_id}",
            )
            for object_id, object_type in objects
        ],
        upstreamMap=upstream_map,
        downstreamMap=downstream_map,
    )


class MpcLateralInflowProjectorTest(unittest.TestCase):
    def tearDown(self):
        ContextManager.clear()

    def test_selects_disturbance_closest_to_channel_before_next_gate(self):
        topology = build_topology(
            [
                (10, "UnifiedCanal"),
                (20, "DisturbanceNode"),
                (30, "UnifiedCanal"),
                (40, "DisturbanceNode"),
                (50, "GateStation"),
                (60, "DisturbanceNode"),
                (70, "GateStation"),
            ],
            (10, 20),
            (20, 30),
            (30, 40),
            (40, 50),
            (50, 60),
            (60, 70),
        )

        target = MpcLateralInflowProjector.find_rainstorm_injection_node(topology, 10)

        self.assertEqual(target, 20)

    def test_aggregates_channels_mapped_to_same_disturbance_by_horizon_step(self):
        topology = build_topology(
            [
                (10, "UnifiedCanal"),
                (11, "UnifiedCanal"),
                (20, "DisturbanceNode"),
                (30, "GateStation"),
            ],
            (10, 20),
            (11, 20),
            (20, 30),
        )

        projected = MpcLateralInflowProjector.project(
            {"10": [1.0, 2.0], "11": [10.0, 20.0, 30.0]},
            {"10", "11"},
            topology,
            prediction_horizon=3,
        )

        self.assertEqual(projected, {"20": [11.0, 22.0, 32.0]})

    def test_keeps_existing_point_boundary_and_merges_projected_channel(self):
        topology = build_topology(
            [
                (10, "UnifiedCanal"),
                (20, "DisturbanceNode"),
                (30, "GateStation"),
            ],
            (10, 20),
            (20, 30),
        )

        projected = MpcLateralInflowProjector.project(
            {"20": [5.0, 6.0], "10": [1.0, 2.0]},
            {"10"},
            topology,
            prediction_horizon=2,
        )

        self.assertEqual(projected, {"20": [6.0, 8.0]})

    def test_falls_back_to_previous_gate_interval(self):
        topology = build_topology(
            [
                (1, "GateStation"),
                (5, "DisturbanceNode"),
                (10, "UnifiedCanal"),
                (20, "UnifiedCanal"),
                (30, "GateStation"),
            ],
            (1, 5),
            (5, 10),
            (10, 20),
            (20, 30),
        )

        target = MpcLateralInflowProjector.find_rainstorm_injection_node(topology, 10)

        self.assertEqual(target, 5)

    def test_rejects_equal_distance_adjacent_gate_stations(self):
        topology = build_topology(
            [
                (10, "UnifiedCanal"),
                (20, "DisturbanceNode"),
                (30, "GateStation"),
                (40, "DisturbanceNode"),
                (50, "GateStation"),
            ],
            (10, 20),
            (20, 30),
            (10, 40),
            (40, 50),
        )

        with self.assertRaisesRegex(
            MpcLateralInflowProjectionError,
            "多个等距的相邻 GateStation",
        ):
            MpcLateralInflowProjector.find_rainstorm_injection_node(topology, 10)

    def test_rejects_equal_distance_disturbance_nodes_before_unique_gate(self):
        topology = build_topology(
            [
                (10, "UnifiedCanal"),
                (20, "DisturbanceNode"),
                (21, "DisturbanceNode"),
                (30, "UnifiedCanal"),
                (40, "GateStation"),
            ],
            (10, 20),
            (10, 21),
            (20, 30),
            (21, 30),
            (30, 40),
        )

        with self.assertRaisesRegex(
            MpcLateralInflowProjectionError,
            "多个等距的最近 DisturbanceNode",
        ):
            MpcLateralInflowProjector.find_rainstorm_injection_node(topology, 10)

    def test_rejects_when_adjacent_gate_intervals_have_no_disturbance(self):
        topology = build_topology(
            [
                (1, "GateStation"),
                (10, "UnifiedCanal"),
                (20, "UnifiedCanal"),
                (30, "GateStation"),
            ],
            (1, 10),
            (10, 20),
            (20, 30),
        )

        with self.assertRaisesRegex(
            MpcLateralInflowProjectionError,
            "相邻上下游 GateStation 区间均找不到",
        ):
            MpcLateralInflowProjector.find_rainstorm_injection_node(topology, 10)

    def test_planning_request_projects_exact_rainstorm_channel_without_protocol_change(self):
        context = SimulationContext(biz_scene_instance_id="rainstorm-projection")
        topology = build_topology(
            [
                (10, "UnifiedCanal"),
                (20, "DisturbanceNode"),
                (30, "GateStation"),
            ],
            (10, 20),
            (20, 30),
        )
        ContextManager.create(context=context, topology=topology)
        task_state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=1,
            prediction_horizon=3,
        )
        task_state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=10,
                        object_type="UnifiedCanal",
                        metrics_code="water_flow",
                        time_series=[
                            TimeSeriesValue(step=1, value=1.0),
                            TimeSeriesValue(step=2, value=2.0),
                            TimeSeriesValue(step=3, value=3.0),
                        ],
                    )
                ],
            )
        )

        request = MpcPlanningClient(
            base_url="http://mpc.local/planning/start",
            require_sensor_data=False,
        ).build_optimize_request(task_state, [])
        payload = request.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(payload["upstream_boundaries"], {"20": [1.0, 2.0, 3.0]})
        self.assertNotIn("10", payload["upstream_boundaries"])
        self.assertNotIn("lateral_inflow_mappings", payload)
        self.assertNotIn("rainstorm_source_object_ids", payload)

    def test_non_rainstorm_channel_remains_unchanged_without_topology(self):
        task_state = MpcTaskState(
            context=SimulationContext(biz_scene_instance_id="ordinary-channel"),
            rolling_interval_steps=3,
            start_step=1,
            current_step=1,
        )
        task_state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="OTHER",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=10,
                        object_type="UnifiedCanal",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=1, value=4.0)],
                    )
                ],
            )
        )

        request = MpcPlanningClient(
            base_url="http://mpc.local/planning/start",
            require_sensor_data=False,
        ).build_optimize_request(task_state, [])

        self.assertEqual(request.upstream_boundaries, {"10": [4.0]})

    def test_rainstorm_channel_requires_loaded_topology_before_request(self):
        task_state = MpcTaskState(
            context=SimulationContext(biz_scene_instance_id="missing-topology"),
            rolling_interval_steps=3,
            start_step=1,
            current_step=1,
        )
        task_state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=10,
                        object_type="UnifiedCanal",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=1, value=4.0)],
                    )
                ],
            )
        )

        with self.assertRaisesRegex(
            MpcLateralInflowProjectionError,
            "缺少 Python central 完整水网拓扑上下文",
        ):
            MpcPlanningClient(
                base_url="http://mpc.local/planning/start",
                require_sensor_data=False,
            ).build_optimize_request(task_state, [])

    def test_non_flow_time_series_is_not_sent_as_lateral_inflow(self):
        task_state = MpcTaskState(
            context=SimulationContext(biz_scene_instance_id="non-flow-series"),
            rolling_interval_steps=3,
            start_step=1,
            current_step=1,
        )
        task_state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=10,
                        object_type="UnifiedCanal",
                        metrics_code="water_level",
                        time_series=[TimeSeriesValue(step=1, value=4.0)],
                    )
                ],
            )
        )

        request = MpcPlanningClient(
            base_url="http://mpc.local/planning/start",
            require_sensor_data=False,
        ).build_optimize_request(task_state, [])

        self.assertEqual(request.upstream_boundaries, {})


if __name__ == "__main__":
    unittest.main()
