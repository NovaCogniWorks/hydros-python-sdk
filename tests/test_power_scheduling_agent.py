import importlib
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from hydros_agent_sdk.protocol.commands import TickCmdRequest
from hydros_agent_sdk.protocol.models import SimulationContext


def _load_power_scheduling_module():
    scheduling_dir = os.path.abspath("custom-agent/power/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)
    return importlib.import_module("power_scheduling_agent")


def _load_hydrosim_api_module():
    hydrosim_dir = os.path.abspath("custom-agent/power/mpc")
    if hydrosim_dir not in sys.path:
        sys.path.insert(0, hydrosim_dir)
    return importlib.import_module("hydrosim_api")


def test_power_scheduling_tick_returns_hydrosim_device_metrics():
    module = _load_power_scheduling_module()

    client = SimpleNamespace(
        mqtt_client=Mock(),
        state_manager=Mock(),
        topic="/hydros/commands/coordination/test-cluster",
    )
    context = SimulationContext(biz_scene_instance_id="power-scene-001")
    agent = module.PumpCentralSchedulingAgent(
        sim_coordination_client=client,
        agent_id="power-agent-001",
        agent_code="CENTRAL_SCHEDULING_AGENT_POWER",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Power Scheduling Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
    )

    agent._mpc_rolling_runtime = Mock()
    agent._hydrosim_initialized = True
    agent._hydrosim_power_plan_loaded = True
    agent._hydrosim_api.execute_step = Mock(
        return_value={
            "current_step_index": 3,
            "device_step_outputs": [
                {
                    "object_id": 20304,
                    "object_type": "Turbine",
                    "object_name": "深溪沟水轮机1",
                    "metrics_code": "power",
                    "step": 3,
                    "value": 87.6,
                },
                {
                    "object_id": 20304,
                    "object_type": "Turbine",
                    "object_name": "深溪沟水轮机1",
                    "metrics_code": "water_flow",
                    "step": 3,
                    "value": 42.5,
                },
                {
                    "object_id": 20101,
                    "object_type": "Gate",
                    "object_name": "瀑布闸1",
                    "metrics_code": "water_flow",
                    "step": 3,
                    "value": 16.2,
                },
                {
                    "object_id": 20101,
                    "object_type": "Gate",
                    "object_name": "瀑布闸1",
                    "metrics_code": "gate_opening",
                    "step": 3,
                    "value": 1.75,
                },
            ],
        }
    )

    metrics_list = agent.on_tick_simulation(
        TickCmdRequest(
            command_id="tick-003",
            context=context,
            step=3,
            broadcast=False,
        )
    )

    metrics_map = {(item.object_id, item.metrics_code): item.value for item in metrics_list}
    assert metrics_map[(20304, "power")] == 87.6
    assert metrics_map[(20304, "water_flow")] == 42.5
    assert metrics_map[(20101, "water_flow")] == 16.2
    assert metrics_map[(20101, "gate_opening")] == 1.75
    assert len(metrics_list) == 4
    agent._mpc_rolling_runtime.on_tick.assert_called_once_with(3)
    agent._hydrosim_api.execute_step.assert_called_once_with(step_index=3)


def test_hydrosim_execute_step_returns_cached_device_outputs():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    stations = [
        SimpleNamespace(name="瀑布沟", history={"current_power": []}),
        SimpleNamespace(name="深溪沟", history={"current_power": []}),
        SimpleNamespace(name="枕头坝", history={"current_power": []}),
        SimpleNamespace(name="沙坪", history={"current_power": []}),
    ]
    step_runtime = hydrosim_api.HydroSimulationStepRuntime(
        merged_event={"object_time_series": []},
        initial_states={},
        constraints={},
        flow_configs=[],
        steps=[0],
        flows_in=[334.0],
        station_power_plan={
            20100: [1160.0],
            20300: [180.0],
            20500: [210.0],
            20700: [90.0],
        },
        target_stage_by_node={20100: [819.0], 20300: [658.0], 20500: [619.0], 20700: [552.0]},
        control_domains=[
            {"device_id": 20304, "node_id": 20300, "type": "Turbine"},
            {"device_id": 20101, "node_id": 20100, "type": "Gate"},
        ],
        device_names={20304: "深溪沟水轮机1", 20101: "瀑布闸1"},
        multi_river=SimpleNamespace(),
        multi_reservoir=SimpleNamespace(),
        multi_stair=SimpleNamespace(multi_stair=stations),
    )
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-001",
        time_series_file="base.json",
        mpc_config_file="mpc.yaml",
        initial_states_file="initial.yaml",
        constraints_file="constraints.yaml",
        latest_station_power_series=[
            {
                "node_id": 20100,
                "station": "瀑布沟",
                "time_series": [{"step": 0, "value": 1160.0}],
            }
        ],
        step_runtime=step_runtime,
    )
    api.service.core.result_factory._device_metrics_for_control_type = Mock(
        side_effect=lambda control_type: {
            "Turbine": ("power", "water_flow"),
            "Gate": ("water_flow", "gate_opening"),
        }.get(control_type, ())
    )
    api.service.core.result_factory._control_domain_device_series = Mock(
        side_effect=lambda **kwargs: {
            (20304, "power"): [87.6],
            (20304, "water_flow"): [42.5],
            (20101, "water_flow"): [16.2],
            (20101, "gate_opening"): [1.75],
        }[(kwargs["device_id"], kwargs["metric"])]
    )

    def _fake_execute_runtime_step(step_runtime_obj, step_index, planning_values_by_node):
        stations[0].history["current_power"].append(1160.0)
        stations[1].history["current_power"].append(180.0)
        stations[2].history["current_power"].append(210.0)
        stations[3].history["current_power"].append(90.0)

    api._execute_runtime_step = Mock(side_effect=_fake_execute_runtime_step)

    result = api.execute_step(step_index=0)

    assert result["station_step_outputs"][0]["power"] == 1160.0
    device_metrics = {
        (item["object_id"], item["metrics_code"]): item["value"]
        for item in result["device_step_outputs"]
    }
    assert device_metrics[(20304, "power")] == 87.6
    assert device_metrics[(20304, "water_flow")] == 42.5
    assert device_metrics[(20101, "water_flow")] == 16.2
    assert device_metrics[(20101, "gate_opening")] == 1.75
