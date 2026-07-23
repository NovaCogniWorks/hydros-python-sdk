import os
import sys
import unittest
from unittest.mock import Mock

import pandas as pd
import yaml

sys.path.insert(0, os.path.abspath("custom-agent/pump/scheduling"))

from hydros_agent_sdk.protocol.commands import CommandStatus, TimeSeriesDataUpdateRequest
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import ObjectTimeSeries, SimulationContext, TimeSeriesValue
from odd_dmpc.config import build_zero_demand_plan, load_runtime_context_from_payload
from odd_dmpc.observers import DisturbanceObserverBank
from odd_dmpc.types import StationMemory
from pump_scheduling_agent import PumpCentralSchedulingAgent


class MockClient:
    def __init__(self):
        self.state_manager = self
        self.topic = "test/topic"

    def send_command(self, req):
        del req

    def subscribe(self, topic):
        del topic

class TestPumpDynamicDemandPlan(unittest.TestCase):
    def setUp(self):
        self.context = SimulationContext(biz_scene_instance_id="test_scene")
        self.agent = PumpCentralSchedulingAgent(
            sim_coordination_client=MockClient(),
            agent_id="agent1",
            agent_code="code",
            agent_type="type",
            agent_name="name",
            context=self.context,
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )
        self.agent.properties["mpc_config_url"] = "custom-agent/pump/data/config_xhh.yaml"
        mock_agent = Mock()
        mock_agent.agent_code = "mock_station_code"
        self.agent._target_agent_resolver.resolve_target_agent_for_object = Mock(return_value=mock_agent)
        self.agent._lazy_init_odd_mpc()

    def test_weather_forecast_update_maps_sensor_object_and_normalizes_inflow_sign(self):
        self.agent.last_opt_step = 5
        request = TimeSeriesDataUpdateRequest(
            context=self.context,
            command_id="cmd-weather-1",
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20400,
                        object_name="沙集站入水",
                        time_series=[TimeSeriesValue(step=7, value=20.0)],
                    )
                ],
            ),
            broadcast=False,
        )

        response = self.agent.on_time_series_data_update(request)

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        self.assertEqual(self.agent.odd_demand_plan.loc[7, "station2-station3"], -20.0)
        self.assertEqual(self.agent.odd_demand_plan.loc[5, "station2-station3"], 0.0)

    def test_observer_excludes_planned_inflow_from_disturbance_estimate(self):
        with open("custom-agent/pump/data/config_xhh.yaml", "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        runtime_context = load_runtime_context_from_payload(payload)
        system_config = runtime_context["system_config"]
        runtime = runtime_context["runtime"]
        runtime.observer_gain = 1.0
        runtime.observer_smoothing = 0.0

        observer = DisturbanceObserverBank(system_config, runtime)
        estimate = observer.update(
            prev_basin_levels={"b1": 0.0, "b2": 0.0},
            next_basin_levels={"b1": 0.0, "b2": 0.0},
            actual_flows={1: 30.0, 2: 30.0, 3: 50.0},
            demand_row=pd.Series({"station1-station2": 0.0, "station2-station3": -20.0}),
            pool_areas={1: 1.0, 2: 1.0},
            step_hours=1.0,
        )

        self.assertAlmostEqual(estimate[1], 0.0)
        self.assertAlmostEqual(estimate[2], 0.0)

    def test_runtime_context_uses_zero_demand_plan_instead_of_configured_file(self):
        with open("custom-agent/pump/data/config_xhh.yaml", "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        runtime_context = load_runtime_context_from_payload(payload)
        system_config = runtime_context["system_config"]
        demand_plan = runtime_context["demand_plan"]

        expected = build_zero_demand_plan(system_config)
        self.assertListEqual(list(demand_plan.columns), list(expected.columns))
        self.assertTrue(demand_plan.equals(expected))

    def test_live_station_state_sync_updates_memory_flow_and_active_units(self):
        station_id = self.agent.system_config.station_ids[0]
        available_units = self.agent.available_units_map[station_id]
        self.agent.station_memories[station_id] = StationMemory(
            active_unit_ids=[],
            unit_openings={unit_id: 0.0 for unit_id in available_units},
            unit_status={unit_id: 0 for unit_id in available_units},
            time_since_adjust={unit_id: 999 for unit_id in available_units},
            time_since_switch={unit_id: 999 for unit_id in available_units},
            last_selected_flow=0.0,
            mode="ODD1",
        )
        live_memory = self.agent.station_memories[station_id]
        live_memory.unit_status[available_units[0]] = 1
        if len(available_units) > 1:
            live_memory.unit_status[available_units[1]] = 1

        self.agent._sync_station_memory_from_live_state(station_id, total_flow=42.5)

        self.assertListEqual(live_memory.active_unit_ids, available_units[:2])
        self.assertAlmostEqual(live_memory.last_selected_flow, 42.5)


if __name__ == "__main__":
    unittest.main()
