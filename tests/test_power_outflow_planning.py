import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hydros_agent_sdk.protocol.commands import (
    HydroEventCommand,
    OutflowTimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.events import (
    OutflowPlanningEvent,
    OutflowTimeSeriesDataChangedEvent,
)
from hydros_agent_sdk.protocol.models import (
    CommandStatus,
    ObjectTimeSeries,
    SimulationContext,
    TimeSeriesValue,
)


class _HydroSimulationApiStub:
    def __init__(self):
        self._session = None


def _load_power_scheduling_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom-agent"
        / "power"
        / "scheduling"
        / "power_scheduling_agent.py"
    )
    hydrosim_module = types.ModuleType("hydrosim_api")
    hydrosim_module.HydroSimulationApi = _HydroSimulationApiStub
    spec = importlib.util.spec_from_file_location(
        "power_scheduling_agent_outflow_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"hydrosim_api": hydrosim_module}):
        spec.loader.exec_module(module)
    return module


class PowerOutflowPlanningTest(unittest.TestCase):
    def setUp(self):
        module = _load_power_scheduling_module()
        self._runtime_dir = tempfile.TemporaryDirectory(
            prefix="power-outflow-planning-test-"
        )
        self.addCleanup(self._runtime_dir.cleanup)
        module.RUNTIME_DIR = Path(self._runtime_dir.name) / "scheduling"
        self.context = SimulationContext(biz_scene_instance_id="power-outflow-test")
        client = SimpleNamespace(
            mqtt_client=Mock(),
            transport=Mock(),
            state_manager=Mock(),
            topic="/hydros/commands/coordination/test-cluster",
            enqueue=Mock(),
        )
        self.agent = module.PowerCentralSchedulingAgent(
            sim_coordination_client=client,
            agent_id="power-central-agent",
            agent_code="CENTRAL_SCHEDULING_AGENT_POWER",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Power Central Scheduling Agent",
            context=self.context,
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )
        self.agent._hydrosim_initialized = True
        self.agent._activate_mpc_task_state_from_event = Mock(
            return_value=SimpleNamespace(current_step=3)
        )
        self.agent._refresh_rolling_window_for_boundary_change = Mock()

    def test_embedded_power_series_uses_power_planning_api(self):
        self.agent._hydrosim_api.get_station_power_planning_series = Mock(
            return_value={
                "station_power_series": [
                    {
                        "node_id": 20100,
                        "station": "Station-20100",
                        "time_series": [{"step": 3, "value": 500.0}],
                    }
                ]
            }
        )
        event = OutflowPlanningEvent(
            hydro_event_id="power-plan-event",
            auto_schedule_at_step=3,
            object_time_series=[
                ObjectTimeSeries(
                    object_id=20100,
                    object_type="Station",
                    metrics_code="output_power",
                    time_series=[TimeSeriesValue(step=3, value=500.0)],
                )
            ],
        )

        response = self.agent.on_outflow_planning(self._request(event))

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        self.assertEqual(response.hydro_event, event)
        planned = response.outflow_time_series_map["Station"][0]
        self.assertEqual(planned.metrics_code, "output_power")
        self.assertEqual(planned.time_series[0].value, 500.0)
        self.assertTrue(self.agent._hydrosim_power_plan_loaded)
        self.agent._hydrosim_api.get_station_power_planning_series.assert_called_once()
        changed_event = self.agent._activate_mpc_task_state_from_event.call_args.args[0]
        self.assertEqual(changed_event.hydro_event_source_type, "OUTFLOW_PLANNING")
        self.assertEqual(changed_event.object_time_series, [planned])

    def test_inflow_series_uses_inflow_planning_api_without_fallback(self):
        self.agent._hydrosim_api.get_station_power_planning_series_from_inflow = Mock(
            return_value={
                "station_power_series": [
                    {
                        "node_id": 20100,
                        "station": "Station-20100",
                        "time_series": [{"step": 3, "value": 480.0}],
                    }
                ]
            }
        )
        event = OutflowPlanningEvent(
            auto_schedule_at_step=3,
            object_time_series=[
                ObjectTimeSeries(
                    object_id=20100,
                    object_type="Station",
                    metrics_code="water_flow",
                    time_series=[TimeSeriesValue(step=3, value=334.0)],
                )
            ],
        )

        response = self.agent.on_outflow_planning(self._request(event))

        self.assertEqual(
            response.outflow_time_series_map["Station"][0].time_series[0].value,
            480.0,
        )
        self.agent._hydrosim_api.get_station_power_planning_series_from_inflow.assert_called_once()

    def test_follow_up_event_is_ack_only(self):
        self.agent._hydrosim_api.apply_time_series_event_update = Mock()
        request = OutflowTimeSeriesDataUpdateRequest(
            command_id="power-follow-up",
            context=self.context,
            outflow_time_series_data_changed_event=OutflowTimeSeriesDataChangedEvent(
                hydro_event_source_type="OUTFLOW_PLANNING",
                object_type="Station",
                object_time_series=[],
            ),
        )

        response = self.agent.on_outflow_time_series_data_update(request)

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        self.agent._hydrosim_api.apply_time_series_event_update.assert_not_called()

    def test_unsupported_series_fails_without_sample_fallback(self):
        event = OutflowPlanningEvent(
            object_time_series=[
                ObjectTimeSeries(
                    object_id=20100,
                    object_type="Station",
                    metrics_code="water_level",
                    time_series=[TimeSeriesValue(step=3, value=850.0)],
                )
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "requires Station/output_power or Station/water_flow",
        ):
            self.agent.on_outflow_planning(self._request(event))

    def _request(self, event: OutflowPlanningEvent) -> HydroEventCommand:
        return HydroEventCommand(
            command_id="power-planning-command",
            context=self.context,
            target_agent_instance=self.agent,
            payload=event,
        )


if __name__ == "__main__":
    unittest.main()
