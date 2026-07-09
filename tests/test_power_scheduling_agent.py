import json
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from hydros_agent_sdk.protocol.commands import (
    OutflowTimeSeriesDataUpdateRequest,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.agent_commands.models import DeviceValueTypeEnum
from hydros_agent_sdk.protocol.events import (
    OutflowTimeSeriesDataChangedEvent,
    TimeSeriesDataChangedEvent,
)
from hydros_agent_sdk.protocol.models import ObjectTimeSeries, SimulationContext, TimeSeriesValue
from hydros_agent_sdk.scheduling_task_state import SchedulingTaskState

POWER_STATION_TURBINE = "POWER_STATION_TURBINE"
POWER_STATION_GATE = "POWER_STATION_GATE"
MPC_STATION_FLOW_COMMAND_TYPE = DeviceValueTypeEnum.WATER_FLOW.code


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
            "metrics_code": "output_power",
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
                "metrics_code": "output_power",
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
    assert metrics_map[(20304, "output_power")] == 83.0
    assert metrics_map[(20101, "gate_opening")] == 1.3
    assert len(enqueued) == 1
    report = enqueued[0]
    assert report.mpc_results[0].plan_type == "optimal"
    assert report.mpc_results[0].step == 3
    horizon_steps = {detail.horizon_step for detail in report.mpc_results[0].details}
    assert horizon_steps == {1}
    report_details = {
        (detail.object_id, detail.object_type, detail.command_type): detail.target_value
        for detail in report.mpc_results[0].details
    }
    assert report_details[(20304, POWER_STATION_TURBINE, "output_power")] == 83.0
    assert report_details[(20101, POWER_STATION_GATE, "gate_opening")] == 1.3
    assert (20304, POWER_STATION_TURBINE, MPC_STATION_FLOW_COMMAND_TYPE) not in report_details
    assert (20101, POWER_STATION_GATE, MPC_STATION_FLOW_COMMAND_TYPE) not in report_details
    turbine_station_detail = next(
        detail
        for detail in report.mpc_results[0].details
        if detail.object_type == POWER_STATION_TURBINE and detail.command_type == MPC_STATION_FLOW_COMMAND_TYPE
    )
    assert turbine_station_detail.node_id == 20300
    assert turbine_station_detail.object_id == 20300
    assert turbine_station_detail.value is None
    assert turbine_station_detail.target_value is None
    agent._control_command_dispatcher.dispatch.assert_called_once()
    dispatched_commands = agent._control_command_dispatcher.dispatch.call_args.args[0]
    assert dispatched_commands == [
        {
            "target_agent_code": "TARGET_AGENT_20304",
            "target_command_type": "output_power",
            "target_value": 83.0,
            "object_id": 20304,
            "object_type": "Turbine",
        },
        {
            "target_agent_code": "TARGET_AGENT_20101",
            "target_command_type": "gate_opening",
            "target_value": 1.3,
            "object_id": 20101,
            "object_type": "Gate",
        }
    ]
    agent._hydrosim_api.execute_step.assert_called_once_with(step_index=3)


def test_power_scheduling_optimization_builds_device_control_commands():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-turbine-001")
    agent._hydrosim_api._session = _build_session(4)

    commands = agent.on_optimization(2)

    assert commands == [
        {
            "target_agent_code": "TARGET_AGENT_20304",
            "target_command_type": "output_power",
            "target_value": 82.0,
            "object_id": 20304,
            "object_type": "Turbine",
        },
        {
            "target_agent_code": "TARGET_AGENT_20101",
            "target_command_type": "gate_opening",
            "target_value": 1.2,
            "object_id": 20101,
            "object_type": "Gate",
        }
    ]


def test_power_scheduling_init_downloads_hydrosim_inputs_from_config_urls():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-url-001")

    download_payload = b"demo-content"

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return download_payload

    original_urlopen = module.urlopen
    try:
        module.urlopen = Mock(return_value=_FakeResponse())
        agent.properties["mpc_config_url"] = "https://example.test/mpc_config.yaml"
        agent.properties["init_state_config_url"] = "https://example.test/initial_states.yaml"
        agent.properties["target_and_constrain_config_url"] = "https://example.test/constrains_targets.yaml"
        agent.properties["objects_time_series_url"] = "https://example.test/time_series_power_planning.json"
        agent._hydrosim_api.initialize = Mock(
            return_value={"session": {"session_id": "session-download-001"}}
        )
        agent._initialize_hydrosim_session()

        init_kwargs = agent._hydrosim_api.initialize.call_args.kwargs
        assert init_kwargs["time_series_file"].endswith("time_series_power_planning.json")
        assert init_kwargs["mpc_config_file"].endswith("mpc_config.yaml")
        assert init_kwargs["initial_states_file"].endswith("initial_states.yaml")
        assert init_kwargs["constraints_file"].endswith("constrains_targets.yaml")
        assert os.path.exists(init_kwargs["mpc_config_file"])
        assert os.path.exists(init_kwargs["initial_states_file"])
        assert os.path.exists(init_kwargs["constraints_file"])
        assert os.path.exists(init_kwargs["time_series_file"])
        assert module.urlopen.call_count >= 3
    finally:
        module.urlopen = original_urlopen


def test_power_scheduling_uses_objects_time_series_url_for_power_planning_file():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-url-002")

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"object_time_series": []}'

    original_urlopen = module.urlopen
    try:
        module.urlopen = Mock(return_value=_FakeResponse())
        agent.properties["objects_time_series_url"] = "https://example.test/time_series_power_planning.json"
        agent._hydrosim_power_plan_loaded = False
        agent._hydrosim_api.get_station_power_planning_series = Mock(
            return_value={"station_power_series": []}
        )

        agent._ensure_hydrosim_power_plan_loaded()

        planning_file = agent._hydrosim_api.get_station_power_planning_series.call_args.args[0]
        assert Path(planning_file).parent != agent._hydrosim_runtime_dir
    finally:
        module.urlopen = original_urlopen


def test_power_scheduling_uses_outflowplan_runtime_default_planning_file():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-default-001")
    agent._hydrosim_api.initialize = Mock(return_value={"session": {"session_id": "session-default-runtime-002"}})

    original_resolve = agent._hydrosim_input_resolver.resolve
    try:
        agent._hydrosim_input_resolver.resolve = Mock(side_effect=lambda **kwargs: kwargs["default_path"])
        agent._initialize_hydrosim_session()

        init_kwargs = agent._hydrosim_api.initialize.call_args.kwargs
        expected_path = os.path.abspath(
            os.path.join(
                "custom-agent",
                "power",
                ".runtime",
                "outflowplan",
                "time_series_power_planning.json",
            )
        )
        assert os.path.abspath(init_kwargs["time_series_file"]) == expected_path
    finally:
        agent._hydrosim_input_resolver.resolve = original_resolve


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
    assert {detail.horizon_step for detail in second_report.mpc_results[0].details} == set(range(1, 11))
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
    agent._hydrosim_api.apply_time_series_event_update = Mock(
        return_value={
            "station_power_series": agent._hydrosim_api._session.latest_station_power_series,
            "device_output_series": agent._hydrosim_api._session.latest_device_output_series,
            "updated_time_series_count": 1,
        }
    )

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
    _, kwargs = agent._hydrosim_api.apply_time_series_event_update.call_args
    assert kwargs["current_step"] == 1
    assert kwargs["current_step_metrics"] == []


def test_power_scheduling_time_series_update_refreshes_hydrosim_plan_for_optimization():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-004")

    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(side_effect=RuntimeError("not initialized")),
        get_roll_steps=lambda: 10,
        configured_mpc_config_url="mpc.yaml",
        configured_target_and_constrain_config_url="control.yaml",
    )
    agent._hydrosim_api._session = _build_session(5)

    def _refresh_plan(event, current_step=None, current_step_metrics=None):
        session = agent._hydrosim_api._session
        session.latest_station_power_series = [
            {
                "node_id": 20300,
                "station": "Station-20300",
                "time_series": [{"step": 2, "value": 321.0}],
            }
        ]
        session.latest_device_output_series = []
        return {
            "station_power_series": session.latest_station_power_series,
            "device_output_series": session.latest_device_output_series,
            "updated_time_series_count": len(event.object_time_series),
        }

    agent._hydrosim_api.apply_time_series_event_update = Mock(side_effect=_refresh_plan)

    response = agent.on_time_series_data_update(
        TimeSeriesDataUpdateRequest(
            command_id="ts-apply-001",
            context=context,
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                hydro_event_source_type="WATER_USE",
                auto_schedule_at_step=2,
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=1001,
                        object_name="water-use",
                        metrics_code="flow",
                        time_series=[TimeSeriesValue(step=2, value=12.0)],
                    )
                ],
            ),
            broadcast=False,
        )
    )

    commands = agent.on_optimization(2)

    assert response.command_status == "SUCCEED"
    agent._hydrosim_api.apply_time_series_event_update.assert_called_once()
    _, kwargs = agent._hydrosim_api.apply_time_series_event_update.call_args
    assert kwargs["current_step"] == 2
    assert commands == [
        {
            "target_agent_code": "TARGET_AGENT_20300",
            "target_command_type": "output_power",
            "target_value": 321.0,
            "object_id": 20300,
            "object_type": "Station",
        }
    ]


def test_power_scheduling_report_only_contains_control_metrics():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-report-001")
    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(
            return_value=SchedulingTaskState(
                context=context,
                rolling_interval_steps=1,
                start_step=2,
                current_step=2,
                total_steps=4,
            )
        ),
        get_roll_steps=lambda: 1,
    )
    agent._hydrosim_api._session = SimpleNamespace(
        latest_station_power_series=[],
        latest_device_output_series=[
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": "output_power",
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 82.0}],
            },
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 42.0}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": "gate_opening",
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 1.25}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 16.0}],
            },
        ],
        step_runtime=SimpleNamespace(
            merged_event={
                "object_time_series": [
                    {
                        "object_ids": [20300],
                        "object_type": "Station",
                        "object_name": "Station-20300",
                        "metrics_code": "water_level",
                        "time_series": [{"step": 2, "value": 658.0}],
                    }
                ]
            },
            target_stage_by_node={
                20300: [658.0, 658.0, 658.0],
                20100: [819.0, 819.0, 819.0],
            },
        ),
    )
    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(2))

    agent.on_tick_simulation(
        TickCmdRequest(
            command_id="tick-report-002",
            context=context,
            step=2,
            broadcast=False,
        )
    )

    report = enqueued[0]
    control_detail_keys = {
        (detail.object_id, detail.object_type, detail.command_type)
        for detail in report.mpc_results[0].details
        if detail.object_type in {POWER_STATION_TURBINE, POWER_STATION_GATE} and detail.command_type != MPC_STATION_FLOW_COMMAND_TYPE
    }
    assert control_detail_keys == {
        (20304, POWER_STATION_TURBINE, "output_power"),
        (20101, POWER_STATION_GATE, "gate_opening"),
    }
    turbine_station_detail = next(
        detail
        for detail in report.mpc_results[0].details
        if detail.object_type == POWER_STATION_TURBINE and detail.command_type == MPC_STATION_FLOW_COMMAND_TYPE
    )
    turbine_attributes = json.loads(turbine_station_detail.attributes)
    assert turbine_station_detail.node_id == 20300
    assert turbine_station_detail.object_id == 20300
    assert turbine_station_detail.value == 42.0
    assert turbine_station_detail.target_value == 42.0
    assert turbine_attributes["object_name"] == "Station-20300"
    assert turbine_attributes["front_water_level"] == 658.0
    assert turbine_attributes["back_water_level"] is None
    assert turbine_attributes["final_target_water_level"] == 658.0
    assert turbine_attributes["out_flow"] == 42.0
    assert turbine_attributes["diversion_flow"] is None
    assert turbine_attributes["efficiency"] == 82.0

    gate_station_detail = next(
        detail
        for detail in report.mpc_results[0].details
        if detail.object_type == POWER_STATION_GATE and detail.command_type == MPC_STATION_FLOW_COMMAND_TYPE
    )
    gate_attributes = json.loads(gate_station_detail.attributes)
    assert gate_station_detail.node_id == 20100
    assert gate_station_detail.object_id == 20100
    assert gate_station_detail.value == 16.0
    assert gate_station_detail.target_value == 16.0
    assert gate_attributes["object_name"] == "Station-20100"
    assert gate_attributes["front_water_level"] == 819.0
    assert gate_attributes["back_water_level"] == 658.0
    assert gate_attributes["final_target_water_level"] == 819.0
    assert gate_attributes["out_flow"] is None
    assert gate_attributes["diversion_flow"] == 16.0
    assert gate_attributes["efficiency"] is None


def test_power_scheduling_report_includes_station_predicted_aggregates():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-station-predict-001")
    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(
            return_value=SchedulingTaskState(
                context=context,
                rolling_interval_steps=1,
                start_step=2,
                current_step=2,
                total_steps=4,
            )
        ),
        get_roll_steps=lambda: 1,
    )
    agent._hydrosim_api._session = SimpleNamespace(
        latest_station_power_series=[
            {
                "node_id": 20300,
                "station": "Station-20300",
                "time_series": [
                    {"step": 0, "value": 200.0},
                    {"step": 1, "value": 220.0},
                    {"step": 2, "value": 262.0},
                    {"step": 3, "value": 240.0},
                ],
            }
        ],
        latest_device_output_series=[
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": "output_power",
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 82.0}],
            },
            {
                "object_id": 20305,
                "object_type": "Turbine",
                "object_name": "Turbine-20305",
                "metrics_code": "output_power",
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 180.0}],
            },
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 42.0}],
            },
            {
                "object_id": 20305,
                "object_type": "Turbine",
                "object_name": "Turbine-20305",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 58.0}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": "gate_opening",
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 1.25}],
            },
            {
                "object_id": 20102,
                "object_type": "Gate",
                "object_name": "Gate-20102",
                "metrics_code": "gate_opening",
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 1.75}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 16.0}],
            },
            {
                "object_id": 20102,
                "object_type": "Gate",
                "object_name": "Gate-20102",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 14.0}],
            },
        ],
        step_runtime=SimpleNamespace(
            merged_event={
                "object_time_series": [
                    {
                        "object_ids": [20300],
                        "object_type": "Station",
                        "object_name": "Station-20300",
                        "metrics_code": "water_level",
                        "time_series": [{"step": 2, "value": 658.0}],
                    },
                    {
                        "object_ids": [20500],
                        "object_type": "Station",
                        "object_name": "Station-20500",
                        "metrics_code": "water_level",
                        "time_series": [{"step": 2, "value": 620.0}],
                    },
                ]
            },
            target_stage_by_node={
                20300: [658.0, 658.0, 658.0],
                20500: [619.0, 619.0, 619.0],
            },
        ),
    )
    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(2))

    agent.on_tick_simulation(
        TickCmdRequest(
            command_id="tick-station-predict-002",
            context=context,
            step=2,
            broadcast=False,
        )
    )

    report = enqueued[0]
    turbine_station_detail = next(
        detail
        for detail in report.mpc_results[0].details
        if detail.object_type == POWER_STATION_TURBINE and detail.command_type == MPC_STATION_FLOW_COMMAND_TYPE
    )
    turbine_attributes = json.loads(turbine_station_detail.attributes)
    assert turbine_station_detail.node_id == 20300
    assert turbine_station_detail.object_id == 20300
    assert turbine_station_detail.value == 100.0
    assert turbine_station_detail.target_value == 100.0
    assert turbine_attributes["object_name"] == "Station-20300"
    assert turbine_attributes["front_water_level"] == 658.0
    assert turbine_attributes["back_water_level"] == 620.0
    assert turbine_attributes["final_target_water_level"] == 658.0
    assert turbine_attributes["out_flow"] == 100.0
    assert turbine_attributes["diversion_flow"] is None
    assert turbine_attributes["efficiency"] == 262.0

    gate_station_detail = next(
        detail
        for detail in report.mpc_results[0].details
        if detail.object_type == POWER_STATION_GATE and detail.command_type == MPC_STATION_FLOW_COMMAND_TYPE
    )
    gate_attributes = json.loads(gate_station_detail.attributes)
    assert gate_station_detail.node_id == 20300
    assert gate_station_detail.object_id == 20300
    assert gate_station_detail.value == 30.0
    assert gate_station_detail.target_value == 30.0
    assert gate_attributes["object_name"] == "Station-20300"
    assert gate_attributes["front_water_level"] == 658.0
    assert gate_attributes["back_water_level"] == 620.0
    assert gate_attributes["final_target_water_level"] == 658.0
    assert gate_attributes["out_flow"] is None
    assert gate_attributes["diversion_flow"] == 30.0
    assert gate_attributes["efficiency"] is None


def test_power_scheduling_optimization_falls_back_to_station_series_when_turbine_series_missing():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-station-fallback-001")
    agent._hydrosim_api._session = SimpleNamespace(
        latest_station_power_series=[
            {
                "node_id": 20300,
                "station": "Station-20300",
                "time_series": [{"step": 2, "value": 321.0}],
            }
        ],
        latest_device_output_series=[],
    )

    commands = agent.on_optimization(2)

    assert commands == [
        {
            "target_agent_code": "TARGET_AGENT_20300",
            "target_command_type": "output_power",
            "target_value": 321.0,
            "object_id": 20300,
            "object_type": "Station",
        }
    ]


def test_power_scheduling_optimization_still_ignores_water_flow_metrics():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-command-filter-001")
    agent._hydrosim_api._session = SimpleNamespace(
        latest_station_power_series=[],
        latest_device_output_series=[
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": "output_power",
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 82.0}],
            },
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20300,
                "time_series": [{"step": 2, "value": 42.0}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": "gate_opening",
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 1.25}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 16.0}],
            },
        ],
    )

    commands = agent.on_optimization(2)

    assert commands == [
        {
            "target_agent_code": "TARGET_AGENT_20304",
            "target_command_type": "output_power",
            "target_value": 82.0,
            "object_id": 20304,
            "object_type": "Turbine",
        },
        {
            "target_agent_code": "TARGET_AGENT_20101",
            "target_command_type": "gate_opening",
            "target_value": 1.25,
            "object_id": 20101,
            "object_type": "Gate",
        },
    ]


def test_power_scheduling_outflow_update_refreshes_hydrosim_session():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-005")

    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(side_effect=RuntimeError("not initialized")),
        get_roll_steps=lambda: 10,
        configured_mpc_config_url="mpc.yaml",
        configured_target_and_constrain_config_url="control.yaml",
    )
    agent._hydrosim_api._session = _build_session(5)
    agent._hydrosim_api.apply_time_series_event_update = Mock(
        return_value={
            "station_power_series": agent._hydrosim_api._session.latest_station_power_series,
            "device_output_series": agent._hydrosim_api._session.latest_device_output_series,
            "updated_time_series_count": 1,
        }
    )

    response = agent.on_outflow_time_series_data_update(
        OutflowTimeSeriesDataUpdateRequest(
            command_id="outflow-apply-001",
            context=context,
            outflow_time_series_data_changed_event=OutflowTimeSeriesDataChangedEvent(
                hydro_event_source_type="OUTFLOW_TIME_SERIES",
                object_type="Gate",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20101,
                        object_name="Gate-20101",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=2, value=16.0)],
                    )
                ],
            ),
            broadcast=False,
        )
    )

    assert response.command_status == "SUCCEED"
    agent._hydrosim_api.apply_time_series_event_update.assert_called_once()


def test_power_scheduling_time_series_update_passes_current_step_cache_to_hydrosim():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-006")

    agent._mpc_rolling_runtime = SimpleNamespace(
        require_mpc_task_state=Mock(side_effect=RuntimeError("not initialized")),
        get_roll_steps=lambda: 10,
        configured_mpc_config_url="mpc.yaml",
        configured_target_and_constrain_config_url="control.yaml",
    )
    agent._hydrosim_api._session = _build_session(5)
    agent._metrics_data_cache.update(
        {
            "object_id": 20100,
            "object_type": "Station",
            "metrics_code": "water_flow",
            "value": 456.0,
            "step_index": 3,
            "position_code": "none",
            "attributes": None,
        }
    )
    agent._hydrosim_api.apply_time_series_event_update = Mock(
        return_value={
            "station_power_series": agent._hydrosim_api._session.latest_station_power_series,
            "device_output_series": agent._hydrosim_api._session.latest_device_output_series,
            "updated_time_series_count": 1,
        }
    )

    agent.on_time_series_data_update(
        TimeSeriesDataUpdateRequest(
            command_id="ts-cache-001",
            context=context,
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                hydro_event_source_type="WATER_USE",
                auto_schedule_at_step=3,
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20100,
                        object_type="Station",
                        object_name="Station-20100",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=3, value=334.0)],
                    )
                ],
            ),
            broadcast=False,
        )
    )

    _, kwargs = agent._hydrosim_api.apply_time_series_event_update.call_args
    assert kwargs["current_step"] == 3
    assert kwargs["current_step_metrics"] == [
        {
            "object_id": 20100,
            "object_type": "Station",
            "metrics_code": "water_flow",
            "value": 456.0,
        }
    ]


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
            "Turbine": ("output_power", "water_flow"),
            "Gate": ("water_flow", "gate_opening"),
        }.get(control_type, ())
    )
    api.service.core.result_factory._control_domain_device_series = Mock(
        side_effect=lambda **kwargs: {
            (20304, "output_power"): [87.6],
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
    assert device_metrics[(20304, "output_power")] == 87.6
    assert device_metrics[(20304, "water_flow")] == 42.5
    assert device_metrics[(20101, "water_flow")] == 16.2
    assert device_metrics[(20101, "gate_opening")] == 1.75


def test_hydrosim_execute_step_rounds_outputs_to_six_decimals():
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
            20100: [1160.123456789],
            20300: [180.987654321],
            20500: [210.222222222],
            20700: [90.333333333],
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
        session_id="session-precision-001",
        time_series_file="base.json",
        mpc_config_file="mpc.yaml",
        initial_states_file="initial.yaml",
        constraints_file="constraints.yaml",
        latest_station_power_series=[
            {
                "node_id": 20100,
                "station": "Station-20100",
                "time_series": [{"step": 0, "value": 1160.123456789}],
            }
        ],
        step_runtime=step_runtime,
    )
    api.service.core.result_factory._device_metrics_for_control_type = Mock(
        side_effect=lambda control_type: {
            "Turbine": ("output_power", "water_flow"),
            "Gate": ("gate_opening",),
        }.get(control_type, ())
    )
    api.service.core.result_factory._control_domain_device_series = Mock(
        side_effect=lambda **kwargs: {
            (20304, "output_power"): [87.123456789],
            (20304, "water_flow"): [42.123456789],
            (20101, "gate_opening"): [1.987654321],
        }[(kwargs["device_id"], kwargs["metric"])]
    )

    def _fake_execute_runtime_step(step_runtime_obj, step_index, planning_values_by_node):
        stations[0].history["current_power"].append(1160.123456789)
        stations[1].history["current_power"].append(180.987654321)
        stations[2].history["current_power"].append(210.222222222)
        stations[3].history["current_power"].append(90.333333333)

    api._execute_runtime_step = Mock(side_effect=_fake_execute_runtime_step)

    result = api.execute_step(step_index=0)

    device_metrics = {
        (item["object_id"], item["metrics_code"]): item["value"]
        for item in result["device_step_outputs"]
    }
    station_metrics = {
        item["node_id"]: item["power"]
        for item in result["station_step_outputs"]
    }
    planning_values = {
        item["object_id"]: item["value"]
        for item in result["current_step_power_planning_values"]
    }
    assert station_metrics[20100] == 1160.123457
    assert station_metrics[20300] == 180.987654
    assert planning_values[20100] == 1160.123457
    assert planning_values[20300] == 180.987654
    assert device_metrics[(20304, "output_power")] == 87.123457
    assert device_metrics[(20304, "water_flow")] == 42.123457
    assert device_metrics[(20101, "gate_opening")] == 1.987654


def test_hydrosim_build_device_step_outputs_from_series_rounds_outputs_to_six_decimals():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()

    outputs = api._build_device_step_outputs_from_series(
        device_output_series=[
            {
                "object_id": 20304,
                "object_type": "Turbine",
                "object_name": "Turbine-20304",
                "metrics_code": "output_power",
                "node_id": 20300,
                "time_series": [{"step": 3, "value": 80.123456789}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": "gate_opening",
                "node_id": 20100,
                "time_series": [{"step": 3, "value": 1.987654321}],
            },
        ],
        target_step=0,
    )

    output_map = {
        (item["object_id"], item["metrics_code"]): item["value"]
        for item in outputs
    }
    assert output_map[(20304, "output_power")] == 80.123457
    assert output_map[(20101, "gate_opening")] == 1.987654


def test_hydrosim_apply_time_series_event_update_merges_series_into_active_session():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-merge-001",
        time_series_file="base.json",
        mpc_config_file="mpc.yaml",
        initial_states_file="initial.yaml",
        constraints_file="constraints.yaml",
        latest_station_power_series=[],
        latest_device_output_series=[],
        step_runtime=SimpleNamespace(
            merged_event={
                "object_time_series": [
                    {
                        "object_id": 1001,
                        "object_type": "Channel",
                        "object_name": "channel-1001",
                        "metrics_code": "flow",
                        "time_series": [{"step": 0, "value": 10.0}],
                    },
                    {
                        "object_id": 20300,
                        "object_type": "Station",
                        "object_name": "Station-20300",
                        "metrics_code": "output_power",
                        "time_series": [{"step": 0, "value": 100.0}],
                    },
                ]
            }
        ),
    )
    api._run_configured_with_event = Mock(return_value=({"ok": True}, [{"node_id": 20300, "station": "Station-20300", "time_series": []}], []))
    api._build_step_runtime = Mock(return_value=SimpleNamespace(merged_event={}))

    result = api.apply_time_series_event_update(
        TimeSeriesDataChangedEvent(
            hydro_event_source_type="WATER_USE",
            object_time_series=[
                ObjectTimeSeries(
                    object_id=1001,
                    object_type="Channel",
                    object_name="channel-1001",
                    metrics_code="flow",
                    time_series=[TimeSeriesValue(step=0, value=25.0)],
                ),
                ObjectTimeSeries(
                    object_id=1002,
                    object_type="Channel",
                    object_name="channel-1002",
                    metrics_code="flow",
                    time_series=[TimeSeriesValue(step=0, value=30.0)],
                ),
            ],
        )
    )

    merged_event = api._run_configured_with_event.call_args.args[1]
    merged_series = {
        (item.get("object_id"), item.get("metrics_code")): item["time_series"][0]["value"]
        for item in merged_event["object_time_series"]
    }

    assert merged_series[(1001, "flow")] == 25.0
    assert merged_series[(1002, "flow")] == 30.0
    assert merged_series[(20300, "power")] == 100.0
    assert result["updated_time_series_count"] == 2


def test_hydrosim_apply_time_series_event_update_replaces_matching_outflow_series():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-merge-steps-001",
        time_series_file="base.json",
        mpc_config_file="mpc.yaml",
        initial_states_file="initial.yaml",
        constraints_file="constraints.yaml",
        latest_station_power_series=[],
        latest_device_output_series=[],
        step_runtime=SimpleNamespace(
            merged_event={
                "object_time_series": [
                    {
                        "object_ids": [20100, 20300, 20500],
                        "object_type": "Station",
                        "object_name": "三站出力",
                        "metrics_code": "output_power",
                        "time_series_name": "power-plan",
                        "time_series": [
                            {"step": 0, "value": 100.0},
                            {"step": 15, "value": 120.0},
                            {"step": 30, "value": 140.0},
                        ],
                    }
                ]
            }
        ),
    )
    api._run_configured_with_event = Mock(return_value=({"ok": True}, [], []))
    api._build_step_runtime = Mock(return_value=SimpleNamespace(merged_event={}))

    api.apply_time_series_event_update(
        OutflowTimeSeriesDataChangedEvent(
            hydro_event_source_type="OUTFLOW_TIME_SERIES",
            object_type="Station",
            object_time_series=[
                ObjectTimeSeries(
                    object_ids=[20100, 20300, 20500],
                    object_type="Station",
                    object_name="三站出力-更新名称",
                    metrics_code="output_power",
                    time_series_name="power-plan-updated",
                    time_series=[TimeSeriesValue(step=15, value=222.0)],
                )
            ],
        )
    )

    merged_event = api._run_configured_with_event.call_args.args[1]
    merged_item = merged_event["object_time_series"][0]

    assert merged_item["object_name"] == "三站出力-更新名称"
    assert merged_item["time_series_name"] == "power-plan-updated"
    assert merged_item["time_series"] == [{"step": 15, "value": 222.0}]


def test_hydrosim_apply_time_series_event_update_removes_overlapping_station_power_items():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-overlap-replace-001",
        time_series_file="base.json",
        mpc_config_file="mpc.yaml",
        initial_states_file="initial.yaml",
        constraints_file="constraints.yaml",
        latest_station_power_series=[],
        latest_device_output_series=[],
        step_runtime=SimpleNamespace(
            merged_event={
                "object_time_series": [
                    {
                        "object_id": 20100,
                        "object_type": "Station",
                        "object_name": "瀑布沟",
                        "metrics_code": "output_power",
                        "time_series": [{"step": 1, "value": 1000.0}],
                    },
                    {
                        "object_id": 20300,
                        "object_type": "Station",
                        "object_name": "深溪沟",
                        "metrics_code": "output_power",
                        "time_series": [{"step": 1, "value": 200.0}],
                    },
                    {
                        "object_id": 20500,
                        "object_type": "Station",
                        "object_name": "枕头坝二期",
                        "metrics_code": "output_power",
                        "time_series": [{"step": 1, "value": 185.0}],
                    },
                    {
                        "object_id": 20700,
                        "object_type": "Station",
                        "object_name": "沙坪二期",
                        "metrics_code": "output_power",
                        "time_series": [{"step": 1, "value": 120.0}],
                    },
                ]
            }
        ),
    )
    api._run_configured_with_event = Mock(return_value=({"ok": True}, [], []))
    api._build_step_runtime = Mock(return_value=SimpleNamespace(merged_event={}))

    api.apply_time_series_event_update(
        OutflowTimeSeriesDataChangedEvent(
            hydro_event_source_type="OUTFLOW_TIME_SERIES",
            object_type="Station",
            object_time_series=[
                ObjectTimeSeries(
                    object_ids=[20100, 20300, 20500],
                    object_type="Station",
                    object_name="三站出力",
                    metrics_code="output_power",
                    time_series=[TimeSeriesValue(step=1, value=1385.0)],
                )
            ],
        )
    )

    merged_event = api._run_configured_with_event.call_args.args[1]
    merged_items = [
        item
        for item in merged_event["object_time_series"]
        if item.get("object_type") == "Station" and item.get("metrics_code") == "output_power"
    ]

    merged_summary = {
        tuple(item.get("object_ids") or [item.get("object_id")]): item["time_series"]
        for item in merged_items
    }
    assert merged_summary == {
        (20100, 20300, 20500): [{"step": 1, "value": 1385.0}],
        (20700,): [{"step": 1, "value": 120.0}],
    }


def test_hydrosim_apply_time_series_event_update_keeps_step_merge_for_non_outflow_events():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-water-use-merge-001",
        time_series_file="base.json",
        mpc_config_file="mpc.yaml",
        initial_states_file="initial.yaml",
        constraints_file="constraints.yaml",
        latest_station_power_series=[],
        latest_device_output_series=[],
        step_runtime=SimpleNamespace(
            merged_event={
                "object_time_series": [
                    {
                        "object_id": 20100,
                        "object_type": "Station",
                        "object_name": "Station-20100",
                        "metrics_code": "water_flow",
                        "time_series": [
                            {"step": 0, "value": 100.0},
                            {"step": 15, "value": 120.0},
                            {"step": 30, "value": 140.0},
                        ],
                    }
                ]
            }
        ),
    )
    api._run_configured_with_event = Mock(return_value=({"ok": True}, [], []))
    api._build_step_runtime = Mock(return_value=SimpleNamespace(merged_event={}))

    api.apply_time_series_event_update(
        TimeSeriesDataChangedEvent(
            hydro_event_source_type="WATER_USE",
            object_time_series=[
                ObjectTimeSeries(
                    object_id=20100,
                    object_type="Station",
                    object_name="Station-20100",
                    metrics_code="water_flow",
                    time_series=[TimeSeriesValue(step=15, value=222.0)],
                )
            ],
        )
    )

    merged_event = api._run_configured_with_event.call_args.args[1]
    merged_item = merged_event["object_time_series"][0]

    assert merged_item["time_series"] == [
        {"step": 0, "value": 100.0},
        {"step": 15, "value": 222.0},
        {"step": 30, "value": 140.0},
    ]


def test_hydrosim_apply_time_series_event_update_uses_cache_for_current_step_only():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-cache-001",
        time_series_file="base.json",
        mpc_config_file="mpc.yaml",
        initial_states_file="initial.yaml",
        constraints_file="constraints.yaml",
        latest_station_power_series=[],
        latest_device_output_series=[],
        step_runtime=SimpleNamespace(
            merged_event={
                "object_time_series": [
                    {
                        "object_id": 20100,
                        "object_type": "Station",
                        "object_name": "Station-20100",
                        "metrics_code": "water_flow",
                        "time_series": [
                            {"step": 3, "value": 334.0},
                            {"step": 4, "value": 340.0},
                            {"step": 5, "value": 350.0},
                        ],
                    }
                ]
            }
        ),
    )
    api._run_configured_with_event = Mock(return_value=({"ok": True}, [], []))
    api._build_step_runtime = Mock(return_value=SimpleNamespace(merged_event={}))

    api.apply_time_series_event_update(
        TimeSeriesDataChangedEvent(
            hydro_event_source_type="WATER_USE",
            auto_schedule_at_step=3,
            object_time_series=[
                ObjectTimeSeries(
                    object_id=20100,
                    object_type="Station",
                    object_name="Station-20100",
                    metrics_code="water_flow",
                    time_series=[
                        TimeSeriesValue(step=3, value=334.0),
                        TimeSeriesValue(step=4, value=340.0),
                        TimeSeriesValue(step=5, value=350.0),
                    ],
                )
            ],
        ),
        current_step=3,
        current_step_metrics=[
            {
                "object_id": 20100,
                "object_type": "Station",
                "metrics_code": "water_flow",
                "value": 456.0,
            }
        ],
    )

    merged_event = api._run_configured_with_event.call_args.args[1]
    assert merged_event["object_time_series"][0]["time_series"] == [
        {"step": 3, "value": 456.0},
        {"step": 4, "value": 340.0},
        {"step": 5, "value": 350.0},
    ]
