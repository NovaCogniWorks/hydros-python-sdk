import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from hydros_agent_sdk.protocol.commands import OutflowTimeSeriesRequest, SimTaskTerminateRequest
from hydros_agent_sdk.protocol.events import OutflowTimeSeriesEvent
from hydros_agent_sdk.protocol.models import SimulationContext, TopHydroObject


POWER_OUTFLOWPLAN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../custom-agent/power/outflowplan")
)
if POWER_OUTFLOWPLAN_DIR not in sys.path:
    sys.path.insert(0, POWER_OUTFLOWPLAN_DIR)

from power_outflow_plan_agent import PowerOutflowPlanAgent


class TestPowerOutflowPlanAgent(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.topic = "test/topic"

        self.context = SimulationContext(
            biz_scene_instance_id="power-scene",
            valid=True,
        )

        self.agent = PowerOutflowPlanAgent(
            sim_coordination_client=self.mock_client,
            agent_id="power-agent-001",
            agent_code="OUTFLOW_PLAN_AGENT_POWER",
            agent_type="OUTFLOW_PLAN_AGENT",
            agent_name="Power Outflow Plan Agent",
            context=self.context,
            hydros_cluster_id="cluster-1",
            hydros_node_id="node-1",
        )

        self.agent.state_manager = MagicMock()
        mock_topology = MagicMock()
        mock_topology.top_objects = [
            TopHydroObject(object_id=101, object_name="StationA", object_type="Station")
        ]
        self.agent._topology = mock_topology
        self.agent.properties.update({"planning_horizon": 4})
        self.agent._resolve_incoming_outflow_plans = MagicMock(return_value=[])

    def test_on_outflow_time_series_returns_station_power_series(self):
        request = OutflowTimeSeriesRequest(
            command_id="outflow-001",
            context=self.context,
            target_agent_instance=self.agent,
            hydro_event=OutflowTimeSeriesEvent(
                hydro_event_type="OUTFLOW_TIME_SERIES",
                event_content_url="http://test.url",
            ),
        )

        self.agent.on_outflow_time_series(request)

        self.mock_client.enqueue.assert_called_once()
        sent_response = self.mock_client.enqueue.call_args[0][0]
        self.assertIn("Station", sent_response.outflow_time_series_map)
        plans = sent_response.outflow_time_series_map["Station"]
        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual(plan.object_type, "Station")
        self.assertEqual(plan.metrics_code, "power")
        self.assertEqual(plan.time_series_name, "StationA_power_plan")
        self.assertEqual([value.step for value in plan.time_series], [0, 1, 2, 3])
        self.assertEqual([value.value for value in plan.time_series], [100.0, 105.0, 110.0, 115.0])

    def test_on_outflow_time_series_calls_hydrosim_power_planning_for_direct_load_event(self):
        self.agent._hydrosim_initialized = True
        self.agent._hydrosim_api.get_station_power_planning_series = MagicMock(
            return_value={
                "station_power_series": [
                    {
                        "node_id": 101,
                        "station": "StationA",
                        "time_series": [{"step": 0, "value": 88.0}],
                    }
                ]
            }
        )

        request = OutflowTimeSeriesRequest(
            command_id="outflow-002",
            context=self.context,
            target_agent_instance=self.agent,
            hydro_event=OutflowTimeSeriesEvent(
                hydro_event_type="OUTFLOW_TIME_SERIES",
                event_content_url="http://test.url/planning.json",
                direct_load_time_series=True,
            ),
        )

        with patch.object(
            self.agent,
            "_load_event_payload_from_url",
            return_value={
                "object_time_series": [
                    {
                        "object_id": 101,
                        "object_type": "Station",
                        "object_name": "StationA",
                        "metrics_code": "power",
                        "time_series": [{"step": 0, "value": 88.0}],
                    }
                ]
            },
        ):
            self.agent.on_outflow_time_series(request)

        self.agent._hydrosim_api.get_station_power_planning_series.assert_called_once()
        sent_response = self.mock_client.enqueue.call_args[0][0]
        plans = sent_response.outflow_time_series_map["Station"]
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].metrics_code, "power")
        self.assertEqual(plans[0].time_series[0].value, 88.0)

    def test_on_outflow_time_series_calls_hydrosim_power_planning_from_event_url_without_direct_flag(self):
        self.agent._hydrosim_initialized = True
        self.agent._hydrosim_api.get_station_power_planning_series = MagicMock(
            return_value={
                "station_power_series": [
                    {
                        "node_id": 101,
                        "station": "StationA",
                        "time_series": [{"step": 0, "value": 66.0}],
                    }
                ]
            }
        )

        request = OutflowTimeSeriesRequest(
            command_id="outflow-003",
            context=self.context,
            target_agent_instance=self.agent,
            hydro_event=OutflowTimeSeriesEvent(
                hydro_event_type="OUTFLOW_TIME_SERIES",
                event_content_url="http://test.url/planning.json",
            ),
        )

        with patch.object(
            self.agent,
            "_load_object_time_series_from_url",
            return_value=[],
        ), patch.object(
            self.agent,
            "_load_event_payload_from_url",
            return_value={
                "object_time_series": [
                    {
                        "object_id": 101,
                        "object_type": "Station",
                        "object_name": "StationA",
                        "metrics_code": "power",
                        "time_series": [{"step": 0, "value": 66.0}],
                    }
                ]
            },
        ):
            self.agent.on_outflow_time_series(request)

        self.agent._hydrosim_api.get_station_power_planning_series.assert_called_once()
        sent_response = self.mock_client.enqueue.call_args[0][0]
        plans = sent_response.outflow_time_series_map["Station"]
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].time_series[0].value, 66.0)

    def test_on_outflow_time_series_uses_objects_time_series_url_property_for_power_planning(self):
        self.agent._hydrosim_initialized = True
        self.agent.properties["objects_time_series_url"] = "https://example.test/time_series_power_planning.json"
        self.agent._hydrosim_api.get_station_power_planning_series = MagicMock(
            return_value={
                "station_power_series": [
                    {
                        "node_id": 101,
                        "station": "StationA",
                        "time_series": [{"step": 0, "value": 77.0}],
                    }
                ]
            }
        )

        request = OutflowTimeSeriesRequest(
            command_id="outflow-004",
            context=self.context,
            target_agent_instance=self.agent,
            hydro_event=OutflowTimeSeriesEvent(
                hydro_event_type="OUTFLOW_TIME_SERIES",
                event_content_url="http://unused-event.url",
            ),
        )

        with patch.object(
            self.agent,
            "_load_event_payload_from_url",
            return_value={
                "object_time_series": [
                    {
                        "object_id": 101,
                        "object_type": "Station",
                        "object_name": "StationA",
                        "metrics_code": "power",
                        "time_series": [{"step": 0, "value": 77.0}],
                    }
                ]
            },
        ):
            self.agent.on_outflow_time_series(request)

        self.agent._hydrosim_api.get_station_power_planning_series.assert_called_once()
        sent_response = self.mock_client.enqueue.call_args[0][0]
        plans = sent_response.outflow_time_series_map["Station"]
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].time_series[0].value, 77.0)

    def test_on_terminate_returns_protocol_command_status_enum(self):
        request = SimTaskTerminateRequest(
            command_id="term-001",
            context=self.context,
        )
        self.agent._hydrosim_api.cancel = MagicMock()
        self.agent._hydrosim_initialized = True

        response = self.agent.on_terminate(request)

        self.assertEqual(response.command_status, "SUCCEED")
        self.agent._hydrosim_api.cancel.assert_called_once()
        self.agent.state_manager.terminate_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
