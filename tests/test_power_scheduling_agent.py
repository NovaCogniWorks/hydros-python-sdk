import importlib
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from hydros_agent_sdk.protocol.commands import TickCmdRequest, TimeSeriesDataUpdateRequest
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import ObjectTimeSeries, SimulationContext
from hydros_agent_sdk.scheduling_task_state import SchedulingTaskState


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


def _build_agent(module, scene_id: str):
    enqueued = []
    client = SimpleNamespace(
        mqtt_client=Mock(),
        state_manager=Mock(),
        topic="/hydros/commands/coordination/test-cluster",
        enqueue=enqueued.append,
    )
    context = SimulationContext(biz_scene_instance_id=scene_id)
    agent = module.PumpCentralSchedulingAgent(
        sim_coordination_client=client,
        agent_id=f"{scene_id}-agent",
        agent_code="CENTRAL_SCHEDULING_AGENT_POWER",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Power Scheduling Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
    )
    agent._hydrosim_initialized = True
    agent._hydrosim_power_plan_loaded = True
    agent._control_command_dispatcher.dispatch = Mock()
    agent._target_agent_resolver.resolve_target_agent_for_object = Mock(
        side_effect=lambda object_id, device_type=None: SimpleNamespace(
            agent_code=f"TARGET_AGENT_{object_id}"
        )
    )
    return agent, context, enqueued


def _build_session(step_count: int):
    station_series = [
        {
            "node_id": 20300,
            "station": "Station-20300",
            "time_series": [{"step": step, "value": 100.0 + step} for step in range(step_count)],
        }
    ]
    device_series = [
        {
            "object_id": 20304,
            "object_type": "Turbine",
            "object_name": "Turbine-20304",
            "metrics_code": "power",
            "node_id": 20300,
            "time_series": [{"step": step, "value": 80.0 + step} for step in range(step_count)],
        },
        {
            "object_id": 20101,
            "object_type": "Gate",
            "object_name": "Gate-20101",
            "metrics_code": "gate_opening",
            "node_id": 20100,
            "time_series": [{"step": step, "value": 1.0 + (step * 0.1)} for step in range(step_count)],
        },
    ]
    return SimpleNamespace(
        latest_station_power_series=station_series,
        latest_device_output_series=device_series,
    )


def _build_step_result(step: int):
    return {
        "current_step_index": step,
        "station_step_outputs": [
            {"node_id": 20300, "station": "Station-20300", "step": step, "power": 100.0 + step}
        ],
        "device_step_outputs": [
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": "power",
                "step": step,
                "value": 80.0 + step,
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": "gate_opening",
                "step": step,
                "value": 1.0 + (step * 0.1),
            },
        ],
    }


def test_power_scheduling_tick_returns_hydrosim_device_metrics():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-001")

    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(
            return_value=SchedulingTaskState(
                context=context,
                rolling_interval_steps=1,
                start_step=3,
                current_step=3,
                total_steps=12,
            )
        ),
        get_roll_steps=lambda: 1,
    )
    agent._hydrosim_api._session = _build_session(12)
    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(3))

    metrics_list = agent.on_tick_simulation(
        TickCmdRequest(
            command_id="tick-003",
            context=context,
            step=3,
            broadcast=False,
        )
    )

    metrics_map = {(item.object_id, item.metrics_code): item.value for item in metrics_list}
    assert metrics_map[(20304, "power")] == 83.0
    assert metrics_map[(20101, "gate_opening")] == 1.3
    assert len(enqueued) == 1
    report = enqueued[0]
    assert report.mpc_results[0].plan_type == "optimal"
    assert report.mpc_results[0].step == 3
    horizon_steps = {detail.horizon_step for detail in report.mpc_results[0].details}
    assert horizon_steps == {3}
    agent._control_command_dispatcher.dispatch.assert_called_once()
    dispatched_commands = agent._control_command_dispatcher.dispatch.call_args.args[0]
    assert dispatched_commands == [
        {
            "target_agent_code": "TARGET_AGENT_20300",
            "target_command_type": "output_power",
            "target_value": 103.0,
            "object_id": 20300,
            "object_type": "Station",
        }
    ]
    agent._hydrosim_api.execute_step.assert_called_once_with(step_index=3)


def test_power_scheduling_refreshes_window_only_at_roll_step_boundaries():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-002")

    task_state = SchedulingTaskState(
        context=context,
        rolling_interval_steps=10,
        start_step=1,
        current_step=1,
        total_steps=30,
    )
    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(return_value=task_state),
        get_roll_steps=lambda: 10,
    )
    agent._hydrosim_api._session = _build_session(30)
    agent._hydrosim_api.execute_step = Mock(side_effect=lambda step_index: _build_step_result(step_index))

    agent.on_tick_simulation(TickCmdRequest(command_id="tick-001", context=context, step=1, broadcast=False))
    assert len(enqueued) == 1
    first_report = enqueued[0]
    assert first_report.mpc_results[0].step == 1
    assert {detail.horizon_step for detail in first_report.mpc_results[0].details} == set(range(1, 11))
    assert agent._rolling_window_start_step == 1
    assert agent._rolling_window_end_step == 10

    agent.on_tick_simulation(TickCmdRequest(command_id="tick-005", context=context, step=5, broadcast=False))
    assert len(enqueued) == 1
    assert agent._rolling_window_start_step == 1
    assert agent._rolling_window_end_step == 10

    agent.on_tick_simulation(TickCmdRequest(command_id="tick-011", context=context, step=11, broadcast=False))
    assert len(enqueued) == 2
    second_report = enqueued[1]
    assert second_report.mpc_results[0].step == 11
    assert {detail.horizon_step for detail in second_report.mpc_results[0].details} == set(range(11, 21))
    assert agent._rolling_window_start_step == 11
    assert agent._rolling_window_end_step == 20
    assert agent._control_command_dispatcher.dispatch.call_count == 2


def test_power_scheduling_time_series_update_activates_window_anchor():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-003")

    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(side_effect=RuntimeError("not initialized")),
        get_roll_steps=lambda: 10,
        configured_mpc_config_url="mpc.yaml",
        configured_target_and_constrain_config_url="control.yaml",
    )
    agent._hydrosim_api._session = _build_session(30)

    response = agent.on_time_series_data_update(
        TimeSeriesDataUpdateRequest(
            command_id="ts-001",
            context=context,
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                hydro_event_source_type="WATER_USE",
                auto_schedule_at_step=1,
                object_time_series=[ObjectTimeSeries(object_id=1001, object_name="water-use")],
            ),
            broadcast=False,
        )
    )

    assert response.command_status == "SUCCEED"
    assert agent._local_mpc_task_state is not None
    assert agent._local_mpc_task_state.start_step == 1
    assert agent._local_mpc_task_state.current_step == 1
    assert agent._local_mpc_task_state.rolling_interval_steps == 10
    assert agent._local_mpc_task_state.hydro_events


def test_hydrosim_execute_step_returns_cached_device_outputs():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    stations = [
        SimpleNamespace(name="Station-20100", history={"current_power": []}),
        SimpleNamespace(name="Station-20300", history={"current_power": []}),
        SimpleNamespace(name="Station-20500", history={"current_power": []}),
        SimpleNamespace(name="Station-20700", history={"current_power": []}),
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
        device_names={20304: "Turbine-20304", 20101: "Gate-20101"},
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
                "station": "Station-20100",
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
