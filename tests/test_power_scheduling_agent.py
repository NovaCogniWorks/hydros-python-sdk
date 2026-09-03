import json
import importlib
import os
import sys
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import yaml

from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    HydroEventCommand,
    OutflowTimeSeriesDataUpdateRequest,
    SimTaskInitRequest,
    SimTaskTerminateRequest,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.protocol.events import (
    OutflowPlanningEvent,
    OutflowTimeSeriesDataChangedEvent,
    TimeSeriesDataChangedEvent,
)
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    CommandStatus,
    HydroAgent,
    ObjectTimeSeries,
    SimulationContext,
    TimeSeriesValue,
)
from hydros_agent_sdk.mpc.task_state import MpcTaskState as SchedulingTaskState

POWER_STATION_TURBINE = "POWER_STATION_TURBINE"
POWER_STATION_GATE = "POWER_STATION_GATE"
MPC_STATION_FLOW_COMMAND_TYPE = DeviceValueTypeEnum.WATER_FLOW.code
MPC_STATION_POWER_COMMAND_TYPE = DeviceValueTypeEnum.OUTPUT_POWER.code


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
        transport=Mock(),
        state_manager=Mock(),
        topic="/hydros/commands/coordination/test-cluster",
        enqueue=enqueued.append,
    )
    context = SimulationContext(biz_scene_instance_id=scene_id)
    agent = module.PowerCentralSchedulingAgent(
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
    agent.dispatch_control_commands_and_await_execution = Mock()
    agent._target_agent_resolver.resolve_target_agent_for_object = Mock(
        side_effect=lambda object_id, device_type=None: SimpleNamespace(
            agent_code=f"TARGET_AGENT_{object_id}"
        )
    )
    return agent, context, enqueued


def _configure_mpc_task_state(
    agent,
    *,
    roll_steps: int,
    task_state=None,
    algorithm_config_url: str = "mpc.yaml",
    control_config_url: str = "control.yaml",
):
    agent.properties["roll_steps"] = roll_steps
    object.__setattr__(agent, "_configured_mpc_config_url", algorithm_config_url)
    object.__setattr__(
        agent,
        "_configured_target_and_constrain_config_url",
        control_config_url,
    )
    agent._mpc_task_state_lifecycle._task_state = task_state


def test_power_scheduling_agent_uses_generic_central_base():
    module = _load_power_scheduling_module()

    assert issubclass(module.PowerCentralSchedulingAgent, CentralSchedulingAgent)
    assert not hasattr(module, "MpcCentralSchedulingAgent")

    agent, _, _ = _build_agent(module, "power-generic-central-base")
    assert not hasattr(agent, "_mpc_rolling_runtime")
    assert not hasattr(agent, "_mpc_optimization_service")


def test_power_outflow_planning_uses_embedded_power_series_and_returns_station_output():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-outflow-planning")
    agent._hydrosim_api.get_station_power_planning_series = Mock(
        return_value={
            "station_power_series": [
                {
                    "node_id": 20100,
                    "station": "Station-20100",
                    "time_series": [{"step": 4, "value": 500.0}],
                }
            ]
        }
    )
    agent._refresh_rolling_window_for_boundary_change = Mock()
    event = OutflowPlanningEvent(
        hydro_event_id="power-plan-event",
        auto_schedule_at_step=4,
        object_time_series=[
            ObjectTimeSeries(
                object_id=20100,
                object_type="Station",
                object_name="Station-20100",
                metrics_code="output_power",
                time_series=[TimeSeriesValue(step=4, value=500.0)],
            )
        ],
    )

    response = agent.on_outflow_planning(
        HydroEventCommand(
            command_id="power-plan-command",
            context=context,
            target_agent_instance=agent,
            payload=event,
        )
    )

    assert response.command_status == CommandStatus.SUCCEED
    assert response.hydro_event == event
    assert response.outflow_time_series_map["Station"][0].metrics_code == "output_power"
    assert response.outflow_time_series_map["Station"][0].time_series[0].value == 500.0
    assert agent._hydrosim_power_plan_loaded is True
    agent._hydrosim_api.get_station_power_planning_series.assert_called_once()
    assert agent._peek_mpc_task_state().hydro_events[0].hydro_event_source_type == "OUTFLOW_PLANNING"


def test_power_outflow_planning_uses_inflow_path_without_fallback():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-inflow-planning")
    agent._hydrosim_api.get_station_power_planning_series_from_inflow = Mock(
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
    agent._refresh_rolling_window_for_boundary_change = Mock()

    response = agent.on_outflow_planning(
        HydroEventCommand(
            command_id="power-inflow-command",
            context=context,
            target_agent_instance=agent,
            payload=OutflowPlanningEvent(
                auto_schedule_at_step=3,
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20100,
                        object_type="Station",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=3, value=334.0)],
                    )
                ],
            ),
        )
    )

    assert response.outflow_time_series_map["Station"][0].time_series[0].value == 480.0
    agent._hydrosim_api.get_station_power_planning_series_from_inflow.assert_called_once()


def test_power_planning_preload_falls_back_to_inflow_without_noisy_info(caplog):
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-preload-inflow-fallback")
    agent._hydrosim_power_plan_loaded = False
    agent._resolve_power_planning_file_for_load = Mock(return_value=("plan.json", None))
    agent._hydrosim_api.get_station_power_planning_series = Mock(side_effect=ValueError("not station power"))
    agent._hydrosim_api.get_station_power_planning_series_from_inflow = Mock(
        return_value={
            "station_power_series": [
                {
                    "node_id": 20100,
                    "station": "Station-20100",
                    "time_series": [{"step": 1, "value": 480.0}],
                }
            ]
        }
    )

    caplog.set_level("INFO", logger=module.__name__)

    agent._load_hydrosim_power_plan_locked()

    assert agent._hydrosim_power_plan_loaded is True
    agent._hydrosim_api.get_station_power_planning_series_from_inflow.assert_called_once_with("plan.json")
    assert not any(
        "Power planning file has no Station/output_power series; trying inflow-driven planning" in record.message
        for record in caplog.records
    )


def test_power_outflow_follow_up_is_ack_only():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-outflow-follow-up")
    agent._hydrosim_api.apply_time_series_event_update = Mock()

    response = agent.on_outflow_time_series_data_update(
        OutflowTimeSeriesDataUpdateRequest(
            command_id="power-outflow-follow-up-command",
            context=context,
            outflow_time_series_data_changed_event=OutflowTimeSeriesDataChangedEvent(
                hydro_event_source_type="OUTFLOW_PLANNING",
                object_type="Station",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20100,
                        object_type="Station",
                        metrics_code="output_power",
                        time_series=[TimeSeriesValue(step=3, value=480.0)],
                    )
                ],
            ),
        )
    )

    assert response.command_status == CommandStatus.SUCCEED
    agent._hydrosim_api.apply_time_series_event_update.assert_not_called()


def test_power_scheduling_init_preloads_power_plan_after_registration():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-init-lazy-plan")
    agent._hydrosim_initialized = False
    agent._hydrosim_power_plan_loaded = False
    agent.load_agent_configuration = Mock()
    agent._initialize_optimization_model = Mock()
    agent._initialize_hydrosim_session = Mock()
    agent._ensure_hydrosim_power_plan_loaded = Mock()
    agent._start_hydrosim_power_plan_preload = Mock()
    agent.subscribe_field_metrics = Mock()
    agent._agent_command_gateway.start = Mock()

    request = SimTaskInitRequest(
        command_id="init-lazy-plan",
        context=context,
        agent_list=[
            HydroAgent(
                agent_code="CENTRAL_SCHEDULING_AGENT_POWER",
                agent_type="CENTRAL_SCHEDULING_AGENT",
                agent_name="Power Scheduling Agent",
            )
        ],
    )

    response = agent.on_init(request)

    assert response.command_status == "SUCCEED"
    agent._initialize_hydrosim_session.assert_called_once_with()
    agent._ensure_hydrosim_power_plan_loaded.assert_not_called()
    agent._agent_command_gateway.start.assert_called_once_with()
    agent._start_hydrosim_power_plan_preload.assert_called_once_with()


def test_power_scheduling_tick_fails_fast_when_power_plan_preload_is_not_ready():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-plan-preload-wait")
    agent._hydrosim_power_plan_loaded = False
    agent.properties["hydrosim_power_plan_preload_wait_seconds"] = 0
    agent._hydrosim_power_plan_preload_done.clear()
    agent._hydrosim_power_plan_preload_thread = SimpleNamespace(
        is_alive=Mock(return_value=True)
    )

    response = agent.on_tick_simulation(
        TickCmdRequest(command_id="tick-preload-wait", context=context, step=1)
    )

    assert response.command_status == "FAILED"
    assert response.completed_step == 1
    assert "HydroSim power planning preload is still running" in response.error_message
    agent.dispatch_control_commands_and_await_execution.assert_not_called()


def test_power_scheduling_termination_clears_explicit_task_state():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-terminate")
    agent._mpc_task_state_lifecycle.ensure_task_state(3)
    agent._hydrosim_api.cancel = Mock()
    agent.discard_control_execution_waiters = Mock()
    agent._agent_command_gateway.shutdown = Mock()

    response = agent.on_terminate(
        SimTaskTerminateRequest(command_id="terminate-power", context=context)
    )

    assert response.command_status == "SUCCEED"
    assert agent.agent_status == AgentStatus.TERMINATED
    assert agent._mpc_task_state_lifecycle.task_state is None
    agent.discard_control_execution_waiters.assert_called_once_with()
    agent._agent_command_gateway.shutdown.assert_called_once_with()


def _build_session(step_count: int):
    station_series = [
        {
            "node_id": 20300,
            "station": "Station-20300",
            "time_series": [{"step": step, "value": 100.0 + step} for step in range(step_count)],
        },
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
            "object_id": 20304,
            "object_type": "Turbine",
            "object_name": "Turbine-20304",
            "metrics_code": "water_flow",
            "node_id": 20300,
            "time_series": [{"step": step, "value": 40.0 + step} for step in range(step_count)],
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
                "status": "ON",
            },
        ],
    }


def test_power_scheduling_tick_does_not_publish_internal_prediction_metrics():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-001")

    _configure_mpc_task_state(
        agent,
        roll_steps=1,
        task_state=SchedulingTaskState(
            context=context,
            rolling_interval_steps=1,
            start_step=3,
            current_step=3,
            max_steps=12,
        ),
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

    assert metrics_list == []
    assert len(enqueued) == 1
    report = enqueued[0]
    assert report.mpc_prediction_results[0].plan_type == "optimal"
    assert report.mpc_prediction_results[0].step == 3
    horizon_steps = {detail.horizon_step for detail in report.mpc_prediction_results[0].details}
    assert horizon_steps == {1}
    report_details = {
        (detail.object_id, detail.object_type, detail.command_type): (
            detail.target_value if detail.target_value is not None else detail.value
        )
        for detail in report.mpc_prediction_results[0].details
    }
    assert report_details[(20304, POWER_STATION_TURBINE, "output_power")] == 83.0
    assert report_details[(20101, POWER_STATION_GATE, "gate_opening")] == 1.3
    assert report_details[(20304, POWER_STATION_TURBINE, MPC_STATION_FLOW_COMMAND_TYPE)] == 43.0
    assert (20101, POWER_STATION_GATE, MPC_STATION_FLOW_COMMAND_TYPE) not in report_details
    turbine_station_detail = next(
        detail
        for detail in report.mpc_prediction_results[0].details
        if detail.object_type == POWER_STATION_TURBINE and detail.object_id == 20300
    )
    assert turbine_station_detail.node_id == 20300
    assert turbine_station_detail.object_id == 20300
    assert turbine_station_detail.command_type == MPC_STATION_POWER_COMMAND_TYPE
    assert turbine_station_detail.value == 83.0
    assert turbine_station_detail.target_value == 83.0
    agent.dispatch_control_commands_and_await_execution.assert_called_once()
    dispatched_commands = agent.dispatch_control_commands_and_await_execution.call_args.args[0]
    assert len(dispatched_commands) == 1
    dispatched = dispatched_commands[0]
    assert dispatched["target_agent_code"] == "TARGET_AGENT_20300"
    assert dispatched["target_command_type"] == "output_power"
    assert dispatched["target_value"] == 103.0
    assert dispatched["object_id"] == 20300
    assert dispatched["object_type"] == "PowerStation"
    assert dispatched["main_step_index"] == 3
    assert dispatched["group_size"] == 1
    assert dispatched["group_id"].startswith("POWER_STATION_OUTPUT_POWER:power-scene-001:3:TARGET_AGENT_20300:")
    agent._hydrosim_api.execute_step.assert_called_once_with(step_index=3)


def test_power_scheduling_optimization_builds_station_output_power_command():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-turbine-001")
    agent._hydrosim_api._session = _build_session(4)
    agent._hydrosim_api._session.latest_device_output_series = [
        device
        for device in agent._hydrosim_api._session.latest_device_output_series
        if device["object_type"] != "Gate"
    ]

    commands = agent.on_optimization(2)

    assert len(commands) == 1
    command = commands[0]
    assert command["target_agent_code"] == "TARGET_AGENT_20300"
    assert command["target_command_type"] == "output_power"
    assert command["target_value"] == 102.0
    assert command["object_id"] == 20300
    assert command["object_type"] == "PowerStation"
    assert command["main_step_index"] == 2
    assert command["group_size"] == 1
    assert command["group_id"].startswith("POWER_STATION_OUTPUT_POWER:power-scene-turbine-001:2:TARGET_AGENT_20300:")


def test_power_scheduling_optimization_groups_gate_station_flow_with_station_output_power_by_default():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-gate-001")
    agent._hydrosim_api._session = _build_session(4)
    agent._hydrosim_api._session.latest_station_power_series.append(
        {
            "node_id": 20100,
            "station": "Station-20100",
            "diversion_flow_time_series": [{"step": step, "value": 30.0 + step} for step in range(4)],
        }
    )
    agent._target_agent_resolver.resolve_target_agent_for_object = Mock(
        side_effect=lambda object_id, device_type=None: SimpleNamespace(
            agent_code=f"TARGET_AGENT_{object_id}",
            edge_node_code="EDGE_NODE_A",
        )
    )

    commands = agent.on_optimization(2)

    assert len(commands) == 2
    station_command = next(command for command in commands if command["object_type"] == "PowerStation")
    gate_command = next(command for command in commands if command["object_type"] == "GateStation")
    assert station_command["target_command_type"] == "output_power"
    assert station_command["target_value"] == 102.0
    assert station_command["object_id"] == 20300
    assert gate_command["target_command_type"] == "water_flow"
    assert gate_command["target_value"] == 32.0
    assert gate_command["object_id"] == 20100
    assert station_command["main_step_index"] == gate_command["main_step_index"] == 2
    assert station_command["group_id"] == gate_command["group_id"]
    assert station_command["group_size"] == gate_command["group_size"] == 2
    assert station_command["group_id"].startswith("POWER_STATION_OUTPUT_POWER:power-scene-gate-001:2:EDGE_NODE_A:")
    assert "_control_group_key" not in station_command
    assert "_control_group_key" not in gate_command


def test_power_scheduling_logs_gate_opening_intent_evidence(caplog):
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-gate-evidence-001")
    agent._hydrosim_api._session = SimpleNamespace(
        latest_station_power_series=[
            {
                "node_id": 20100,
                "station": "Station-20100",
                "time_series": [{"step": 2, "value": 321.0}],
                "diversion_flow_time_series": [{"step": 2, "value": 0.0}],
            }
        ],
        latest_device_output_series=[
            {
                "object_id": 20104,
                "object_type": "Turbine",
                "object_name": "Turbine-20104",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 120.0}],
            },
            {
                "object_id": 20104,
                "object_type": "Turbine",
                "object_name": "Turbine-20104",
                "metrics_code": DeviceValueTypeEnum.OUTPUT_POWER.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 300.0}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": DeviceValueTypeEnum.GATE_OPENING.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 0.0}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 0.0}],
            },
        ],
        step_runtime=SimpleNamespace(
            merged_event={},
            target_stage_by_node={20100: [842.0, 842.0, 842.0]},
            multi_reservoir=SimpleNamespace(
                Capacity_Stairs=[
                    SimpleNamespace(
                        history={
                            "time": [2],
                            "current_inflow": [100.0],
                            "current_outflow_power": [120.0],
                            "current_outflow_discharge_ff": [0.0],
                            "current_spill_ff_gain": [1.0],
                            "current_spill_ff_deadband": [20.0],
                            "current_spill_ff_surplus": [-40.0],
                            "current_spill_ff_force_pass": [False],
                            "current_pid_output": [0.0],
                            "current_target_spill": [0.0],
                            "current_spill_delta": [0.0],
                        }
                    )
                ]
            ),
        ),
    )

    caplog.set_level("INFO", logger=module.__name__)

    commands = agent.on_optimization(2)

    assert any(command["object_type"] == "GateStation" for command in commands)
    message = next(
        record.getMessage()
        for record in caplog.records
        if "Power gate control intent evidence" in record.getMessage()
    )
    assert "task_id=power-scene-gate-evidence-001" in message
    assert "step=2" in message
    assert "station_id=20100" in message
    assert "gate_count=1" in message
    assert "total_opening=0.000000" in message
    assert "station_diversion_flow=0.000000" in message
    assert "turbine_outflow=120.000000" in message
    assert "reservoir_inflow=100.000000" in message
    assert "reservoir_outflow_power=120.000000" in message
    assert "reservoir_spill_ff_surplus=-40.000000" in message
    assert "reservoir_pid_output=0.000000" in message
    assert "reservoir_target_spill=0.000000" in message
    assert "reason=water_level_not_triggered_or_no_spill_required" in message


def test_power_scheduling_logs_reservoir_evidence_from_planning_series(caplog):
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-gate-evidence-series-001")
    agent._hydrosim_api._session = SimpleNamespace(
        latest_station_power_series=[
            {
                "node_id": 20100,
                "station": "Station-20100",
                "time_series": [{"step": 2, "value": 321.0}],
                "diversion_flow_time_series": [{"step": 2, "value": 45.0}],
                "reservoir_evidence_time_series": [
                    {
                        "step": 2,
                        "current_inflow": 500.0,
                        "current_outflow_power": 300.0,
                        "current_outflow_discharge_ff": 180.0,
                        "current_spill_ff_gain": 1.0,
                        "current_spill_ff_deadband": 20.0,
                        "current_spill_ff_surplus": 180.0,
                        "current_spill_ff_force_pass": False,
                        "current_pid_output": 15.0,
                        "current_target_spill": 195.0,
                        "current_spill_delta": 45.0,
                    }
                ],
            }
        ],
        latest_device_output_series=[
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": DeviceValueTypeEnum.GATE_OPENING.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 0.5}],
            },
            {
                "object_id": 20101,
                "object_type": "Gate",
                "object_name": "Gate-20101",
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 45.0}],
            },
        ],
        step_runtime=SimpleNamespace(
            merged_event={},
            target_stage_by_node={},
            multi_reservoir=SimpleNamespace(
                Capacity_Stairs=[
                    SimpleNamespace(
                        history={
                            "time": [0],
                            "current_inflow": [999.0],
                        }
                    )
                ]
            ),
        ),
    )

    caplog.set_level("INFO", logger=module.__name__)

    commands = agent.on_optimization(2)

    assert any(command["object_type"] == "GateStation" for command in commands)
    message = next(
        record.getMessage()
        for record in caplog.records
        if "Power gate control intent evidence" in record.getMessage()
    )
    assert "reservoir_inflow=500.000000" in message
    assert "reservoir_spill_ff=180.000000" in message
    assert "reservoir_pid_output=15.000000" in message
    assert "reservoir_target_spill=195.000000" in message
    assert "reservoir_spill_delta=45.000000" in message


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


def test_power_scheduling_uses_bundled_data_default_planning_file():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-default-001")
    agent.properties["hydrosim_time_series_file"] = (
        "/mnt/e/Hydros/hydros-python-sdk/custom-agent/power/.runtime/"
        "obsolete/time_series_power_planning.json"
    )
    agent._hydrosim_api.initialize = Mock(return_value={"session": {"session_id": "session-default-runtime-002"}})

    agent._initialize_hydrosim_session()

    init_kwargs = agent._hydrosim_api.initialize.call_args.kwargs
    expected_path = os.path.abspath(
        os.path.join("custom-agent", "power", "data", "time_series_power_planning.json")
    )
    assert os.path.abspath(init_kwargs["time_series_file"]) == expected_path
    assert os.path.isfile(init_kwargs["time_series_file"])
    assert ".runtime" not in Path(init_kwargs["time_series_file"]).parts


def test_power_scheduling_step_21_recovery_does_not_read_planner_runtime():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-step-21-recovery")
    task_state = SchedulingTaskState(
        context=context,
        rolling_interval_steps=20,
        start_step=1,
        current_step=20,
        max_steps=60,
    )
    _configure_mpc_task_state(agent, roll_steps=20, task_state=task_state)
    agent._hydrosim_initialized = False
    agent._hydrosim_power_plan_loaded = True
    agent._hydrosim_api._session = _build_session(60)
    agent._hydrosim_api.initialize = Mock(
        return_value={"session": {"session_id": "session-step-21-recovery"}}
    )
    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(21))
    agent._rolling_window_start_step = 1
    agent._rolling_window_end_step = 20
    agent._rolling_window_dataset = [Mock()]
    agent.on_optimization = Mock(return_value=[])
    agent._refresh_rolling_window_dataset = Mock()

    agent.on_tick_simulation(
        TickCmdRequest(command_id="tick-step-21-recovery", context=context, step=21)
    )

    init_kwargs = agent._hydrosim_api.initialize.call_args.kwargs
    expected_path = os.path.abspath(
        os.path.join("custom-agent", "power", "data", "time_series_power_planning.json")
    )
    assert os.path.abspath(init_kwargs["time_series_file"]) == expected_path
    assert ".runtime" not in Path(init_kwargs["time_series_file"]).parts
    agent.on_optimization.assert_not_called()
    agent._refresh_rolling_window_dataset.assert_called_once_with(21, task_state)
    agent._hydrosim_api.execute_step.assert_called_once_with(step_index=21)


def test_power_scheduling_refreshes_window_only_at_roll_step_boundaries():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-002")

    task_state = SchedulingTaskState(
        context=context,
        rolling_interval_steps=10,
        start_step=1,
        current_step=1,
        max_steps=30,
    )
    _configure_mpc_task_state(agent, roll_steps=10, task_state=task_state)
    agent._hydrosim_api._session = _build_session(30)
    agent._hydrosim_api.execute_step = Mock(side_effect=lambda step_index: _build_step_result(step_index))

    agent.on_tick_simulation(TickCmdRequest(command_id="tick-001", context=context, step=1, broadcast=False))
    assert len(enqueued) == 1
    first_report = enqueued[0]
    assert len(first_report.mpc_prediction_results) == 1
    assert first_report.mpc_prediction_results[0].step == 1
    first_details = first_report.mpc_prediction_results[0].details
    assert {detail.horizon_step for detail in first_details} == set(range(1, 11))
    first_details_by_object = {}
    for detail in first_details:
        key = (detail.object_id, detail.command_type)
        first_details_by_object.setdefault(key, []).append(detail.horizon_step)
    assert first_details_by_object
    assert all(
        sorted(horizon_steps) == list(range(1, 11))
        for horizon_steps in first_details_by_object.values()
    )
    assert agent._rolling_window_start_step == 1
    assert agent._rolling_window_end_step == 10

    agent.on_tick_simulation(TickCmdRequest(command_id="tick-005", context=context, step=5, broadcast=False))
    assert len(enqueued) == 1
    assert agent._rolling_window_start_step == 1
    assert agent._rolling_window_end_step == 10

    agent.on_tick_simulation(TickCmdRequest(command_id="tick-010", context=context, step=10, broadcast=False))
    assert len(enqueued) == 2
    second_report = enqueued[1]
    assert len(second_report.mpc_prediction_results) == 1
    assert second_report.mpc_prediction_results[0].step == 11
    assert {detail.horizon_step for detail in second_report.mpc_prediction_results[0].details} == set(range(1, 11))
    assert agent._rolling_window_start_step == 11
    assert agent._rolling_window_end_step == 20
    assert agent.dispatch_control_commands_and_await_execution.call_count == 2
    dispatched_commands = agent.dispatch_control_commands_and_await_execution.call_args.args[0]
    assert dispatched_commands[0]["main_step_index"] == 11


def test_power_scheduling_reports_all_96_steps_in_10_rolling_batches():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-96-steps")
    task_state = SchedulingTaskState(
        context=context,
        rolling_interval_steps=10,
        start_step=0,
        current_step=0,
        max_steps=96,
    )
    _configure_mpc_task_state(agent, roll_steps=10, task_state=task_state)
    agent._hydrosim_api._session = _build_session(96)
    agent._hydrosim_api.execute_step = Mock(side_effect=lambda step_index: _build_step_result(step_index))

    for step in range(96):
        agent.on_tick_simulation(
            TickCmdRequest(command_id=f"tick-{step:03d}", context=context, step=step, broadcast=False)
        )

    assert len(enqueued) == 10
    assert [report.mpc_prediction_results[0].step for report in enqueued] == list(range(0, 96, 10))

    details_per_object = {}
    detail_counts_per_batch = []
    for report in enqueued:
        assert len(report.mpc_prediction_results) == 1
        result = report.mpc_prediction_results[0]
        detail_counts_per_batch.append(len(result.details))
        for detail in result.details:
            key = (detail.object_id, detail.command_type)
            absolute_step = result.step + detail.horizon_step - 1
            details_per_object.setdefault(key, []).append(absolute_step)

    assert detail_counts_per_batch == ([40] * 9) + [24]
    assert details_per_object
    assert all(steps == list(range(96)) for steps in details_per_object.values())


def test_power_scheduling_total_steps_uses_runtime_axis_instead_of_sampled_output_rows():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-runtime-axis")
    agent._hydrosim_api._session = SimpleNamespace(
        step_runtime=SimpleNamespace(steps=list(range(96))),
        latest_station_power_series=[
            {
                "time_series": [
                    {"step": step, "value": 100.0}
                    for step in (0, 15, 30, 45, 60, 75, 90, 95)
                ]
            }
        ],
    )

    assert agent._resolve_total_steps() == 96


def test_hydrosim_event_update_keeps_initialized_96_step_axis():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    session = hydrosim_api.HydroSimulationSession(
        session_id="session-fixed-96-steps",
        total_steps=96,
    )
    updated_event = {
        "object_time_series": [
            {
                "object_id": 20000,
                "object_type": "UnifiedCanal",
                "metrics_code": "water_flow",
                "time_series": [
                    {"step": 0, "value": 2534.0},
                    {"step": 96, "value": 2451.0},
                ],
            }
        ]
    }

    steps = api._build_session_time_axis(session, updated_event)

    assert len(steps) == 96
    assert steps[0] == 0
    assert steps[-1] == 95
    assert session.total_steps == 96


def test_power_scheduling_time_series_update_activates_window_anchor():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-003")

    _configure_mpc_task_state(agent, roll_steps=10)
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
    task_state = agent._mpc_task_state_lifecycle.task_state
    assert task_state is not None
    assert task_state.start_step == 1
    assert task_state.current_step == 1
    assert task_state.rolling_interval_steps == 10
    assert task_state.hydro_events
    _, kwargs = agent._hydrosim_api.apply_time_series_event_update.call_args
    assert kwargs["current_step"] == 1
    assert kwargs["current_step_metrics"] == []
    agent.dispatch_control_commands_and_await_execution.assert_not_called()
    assert agent._pending_boundary_control_commands
    assert agent._pending_boundary_control_target_step == 2
    assert agent._pending_boundary_control_commands[0]["target_command_type"] == MPC_STATION_POWER_COMMAND_TYPE
    assert agent._pending_boundary_control_commands[0]["target_value"] == 102.0


def test_power_scheduling_event_ack_does_not_wait_for_edge_control_execution():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-event-ack")
    _configure_mpc_task_state(agent, roll_steps=10)
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
            command_id="event-ack-001",
            context=context,
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                hydro_event_source_type="WATER_USE",
                auto_schedule_at_step=1,
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20100,
                        object_type="GateStation",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=1, value=600.0)],
                    )
                ],
            ),
        )
    )

    assert response.command_status == "SUCCEED"
    agent.dispatch_control_commands_and_await_execution.assert_not_called()
    pending_commands = list(agent._pending_boundary_control_commands)
    assert pending_commands
    assert pending_commands[0]["main_step_index"] == 2
    assert pending_commands[0]["target_command_type"] == MPC_STATION_POWER_COMMAND_TYPE

    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(1))
    agent.on_tick_simulation(
        TickCmdRequest(command_id="tick-after-event-001", context=context, step=1)
    )

    agent.dispatch_control_commands_and_await_execution.assert_called_once_with(
        pending_commands
    )
    assert agent._pending_boundary_control_commands == []
    assert agent._pending_boundary_control_target_step is None


def test_power_scheduling_weather_update_does_not_rewind_active_rolling_step():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-weather-rolling")
    task_state = SchedulingTaskState(
        context=context,
        rolling_interval_steps=10,
        start_step=1,
        current_step=21,
        max_steps=96,
    )
    _configure_mpc_task_state(agent, roll_steps=10, task_state=task_state)
    agent._hydrosim_api._session = _build_session(96)
    agent._hydrosim_api.apply_time_series_event_update = Mock(
        return_value={
            "station_power_series": agent._hydrosim_api._session.latest_station_power_series,
            "device_output_series": agent._hydrosim_api._session.latest_device_output_series,
            "updated_time_series_count": 1,
        }
    )
    agent._rolling_window_start_step = 21
    agent._rolling_window_end_step = 30
    agent._rolling_window_dataset = [Mock()]

    agent.on_time_series_data_update(
        TimeSeriesDataUpdateRequest(
            command_id="weather-update-001",
            context=context,
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                auto_schedule_at_step=0,
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20000,
                        object_type="UnifiedCanal",
                        object_name="sm-pbg",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=0, value=2534.0)],
                    )
                ],
            ),
            broadcast=False,
        )
    )

    assert task_state.start_step == 1
    assert task_state.current_step == 21
    _, kwargs = agent._hydrosim_api.apply_time_series_event_update.call_args
    assert kwargs["current_step"] == 21
    assert agent._rolling_window_start_step == 22
    assert agent._rolling_window_end_step == 31
    assert len(enqueued) == 1
    assert len(enqueued[0].mpc_prediction_results) == 1
    assert enqueued[0].mpc_prediction_results[0].step == 22
    assert {detail.horizon_step for detail in enqueued[0].mpc_prediction_results[0].details} == set(range(1, 11))

    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(21))
    agent.on_tick_simulation(
        TickCmdRequest(command_id="tick-after-weather-021", context=context, step=21, broadcast=False)
    )

    assert agent._rolling_window_start_step == 22
    assert agent._rolling_window_end_step == 31
    assert len(enqueued) == 1

    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(31))
    agent.on_tick_simulation(
        TickCmdRequest(command_id="tick-after-weather-031", context=context, step=31, broadcast=False)
    )

    assert agent._rolling_window_start_step == 31
    assert agent._rolling_window_end_step == 40
    assert len(enqueued) == 2
    assert len(enqueued[1].mpc_prediction_results) == 1
    assert enqueued[1].mpc_prediction_results[0].step == 31


def test_power_scheduling_mid_cycle_event_keeps_original_rolling_anchor():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-mid-cycle-event")
    task_state = SchedulingTaskState(
        context=context,
        rolling_interval_steps=10,
        start_step=1,
        current_step=21,
        max_steps=96,
    )
    _configure_mpc_task_state(agent, roll_steps=10, task_state=task_state)
    agent._hydrosim_api._session = _build_session(96)
    agent._hydrosim_api.apply_time_series_event_update = Mock(
        return_value={
            "station_power_series": agent._hydrosim_api._session.latest_station_power_series,
            "device_output_series": agent._hydrosim_api._session.latest_device_output_series,
            "updated_time_series_count": 1,
        }
    )

    agent.on_time_series_data_update(
        TimeSeriesDataUpdateRequest(
            command_id="mid-cycle-event-025",
            context=context,
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                auto_schedule_at_step=25,
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=20000,
                        object_type="UnifiedCanal",
                        object_name="sm-pbg",
                        metrics_code="water_flow",
                        time_series=[TimeSeriesValue(step=25, value=2500.0)],
                    )
                ],
            ),
            broadcast=False,
        )
    )

    assert task_state.start_step == 1
    assert task_state.current_step == 25
    assert agent._rolling_window_start_step == 26
    assert agent._rolling_window_end_step == 35
    assert len(enqueued) == 1

    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(25))
    agent.on_tick_simulation(
        TickCmdRequest(command_id="tick-mid-cycle-025", context=context, step=25)
    )
    assert len(enqueued) == 1
    assert agent.dispatch_control_commands_and_await_execution.call_count == 1
    dispatched_commands = agent.dispatch_control_commands_and_await_execution.call_args.args[0]
    assert dispatched_commands[0]["main_step_index"] == 26

    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(31))
    agent.on_tick_simulation(
        TickCmdRequest(command_id="tick-next-boundary-031", context=context, step=31)
    )
    assert len(enqueued) == 2
    assert agent._rolling_window_start_step == 31
    assert agent._rolling_window_end_step == 40


def test_power_scheduling_serializes_tick_and_time_series_update():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-runtime-lock")
    _configure_mpc_task_state(agent, roll_steps=10)
    agent._hydrosim_api._session = _build_session(30)
    agent._hydrosim_api.execute_step = Mock(return_value=_build_step_result(1))
    agent._hydrosim_api.apply_time_series_event_update = Mock(
        return_value={
            "station_power_series": agent._hydrosim_api._session.latest_station_power_series,
            "device_output_series": agent._hydrosim_api._session.latest_device_output_series,
            "updated_time_series_count": 1,
        }
    )
    tick_entered = Event()
    release_tick = Event()

    def blocking_optimization(step):
        tick_entered.set()
        assert release_tick.wait(1)
        return []

    agent.on_optimization = Mock(side_effect=blocking_optimization)
    tick_worker = Thread(
        target=lambda: agent.on_tick_simulation(
            TickCmdRequest(command_id="tick-lock-001", context=context, step=1)
        )
    )
    tick_worker.start()
    assert tick_entered.wait(0.2)

    event_attempted = Event()

    def update_time_series():
        event_attempted.set()
        agent.on_time_series_data_update(
            TimeSeriesDataUpdateRequest(
                command_id="event-lock-002",
                context=context,
                time_series_data_changed_event=TimeSeriesDataChangedEvent(
                    hydro_event_source_type="WEATHER_FORECAST",
                    auto_schedule_at_step=2,
                    object_time_series=[
                        ObjectTimeSeries(
                            object_id=20000,
                            object_type="UnifiedCanal",
                            metrics_code="water_flow",
                            time_series=[TimeSeriesValue(step=2, value=2500.0)],
                        )
                    ],
                ),
            )
        )

    event_worker = Thread(target=update_time_series)
    event_worker.start()
    assert event_attempted.wait(0.2)
    event_worker.join(timeout=0.05)
    assert event_worker.is_alive()
    agent._hydrosim_api.apply_time_series_event_update.assert_not_called()

    release_tick.set()
    tick_worker.join(timeout=0.5)
    event_worker.join(timeout=0.5)
    assert not tick_worker.is_alive()
    assert not event_worker.is_alive()
    agent._hydrosim_api.apply_time_series_event_update.assert_called_once()


def test_power_scheduling_time_series_update_refreshes_hydrosim_plan_for_optimization():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-004")

    _configure_mpc_task_state(agent, roll_steps=10)
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
    assert commands == []


def test_power_scheduling_report_only_contains_control_metrics():
    module = _load_power_scheduling_module()
    agent, context, enqueued = _build_agent(module, "power-scene-report-001")
    _configure_mpc_task_state(
        agent,
        roll_steps=1,
        task_state=SchedulingTaskState(
            context=context,
            rolling_interval_steps=1,
            start_step=2,
            current_step=2,
            max_steps=4,
        ),
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
        for detail in report.mpc_prediction_results[0].details
        if detail.object_type in {POWER_STATION_TURBINE, POWER_STATION_GATE} and detail.command_type != MPC_STATION_FLOW_COMMAND_TYPE
    }
    assert control_detail_keys == {
        (20304, POWER_STATION_TURBINE, "output_power"),
        (20101, POWER_STATION_GATE, "gate_opening"),
    }
    turbine_station_detail = next(
        detail
        for detail in report.mpc_prediction_results[0].details
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
        for detail in report.mpc_prediction_results[0].details
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
    _configure_mpc_task_state(
        agent,
        roll_steps=1,
        task_state=SchedulingTaskState(
            context=context,
            rolling_interval_steps=1,
            start_step=2,
            current_step=2,
            max_steps=4,
        ),
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
        for detail in report.mpc_prediction_results[0].details
        if detail.object_type == POWER_STATION_TURBINE and detail.command_type == MPC_STATION_POWER_COMMAND_TYPE
    )
    turbine_attributes = json.loads(turbine_station_detail.attributes)
    assert turbine_station_detail.node_id == 20300
    assert turbine_station_detail.object_id == 20300
    assert turbine_station_detail.value == 262.0
    assert turbine_station_detail.target_value == 262.0
    assert turbine_attributes["object_name"] == "Station-20300"
    assert turbine_attributes["front_water_level"] == 658.0
    assert turbine_attributes["back_water_level"] == 620.0
    assert turbine_attributes["final_target_water_level"] == 658.0
    assert turbine_attributes["final_target_output_power"] == 262.0
    assert turbine_attributes["out_flow"] == 100.0
    assert turbine_attributes["diversion_flow"] is None
    assert turbine_attributes["output_power"] == 262.0
    assert turbine_attributes["efficiency"] == 262.0

    gate_station_detail = next(
        detail
        for detail in report.mpc_prediction_results[0].details
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


def test_power_scheduling_report_uses_station_diversion_flow_without_gate_devices():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-station-spill-001")
    agent._hydrosim_api._session = SimpleNamespace(
        step_runtime=SimpleNamespace(
            merged_event={"object_time_series": []},
            target_stage_by_node={20300: [658.0, 658.0, 658.0]},
        )
    )

    predicted_results = agent._build_station_predicted_results(
        device_series=[],
        station_series=[
            {
                "node_id": 20300,
                "station": "Station-20300",
                "time_series": [{"step": 2, "value": 262.0}],
                "diversion_flow_time_series": [{"step": 2, "value": 31.5}],
            }
        ],
        step=2,
    )

    gate_result = next(
        item for item in predicted_results if item.object_type == POWER_STATION_GATE
    )
    predicted_values = {
        item.value_type: item.value for item in gate_result.predicted_value_list
    }
    assert gate_result.target_value.value == 31.5
    assert predicted_values["diversion_flow"] == 31.5


def test_power_scheduling_optimization_uses_station_output_power_without_turbine_flow():
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

    assert len(commands) == 1
    command = commands[0]
    assert command["target_agent_code"] == "TARGET_AGENT_20300"
    assert command["target_command_type"] == MPC_STATION_POWER_COMMAND_TYPE
    assert command["target_value"] == 321.0
    assert command["object_id"] == 20300
    assert command["object_type"] == "PowerStation"
    assert command["main_step_index"] == 2


def test_power_scheduling_optimization_uses_turbine_output_power_when_station_series_is_missing():
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

    assert len(commands) == 1
    command = commands[0]
    assert command["target_agent_code"] == "TARGET_AGENT_20300"
    assert command["target_command_type"] == MPC_STATION_POWER_COMMAND_TYPE
    assert command["target_value"] == 82.0
    assert command["object_id"] == 20300
    assert command["object_type"] == "PowerStation"
    assert command["main_step_index"] == 2
    assert command["group_size"] == 1
    assert command["group_id"].startswith(
        "POWER_STATION_OUTPUT_POWER:power-scene-command-filter-001:2:TARGET_AGENT_20300:"
    )


def test_power_scheduling_optimization_falls_back_to_turbine_out_flow_when_power_is_missing():
    module = _load_power_scheduling_module()
    agent, _, _ = _build_agent(module, "power-scene-flow-fallback-001")
    agent._hydrosim_api._session = SimpleNamespace(
        latest_station_power_series=[],
        latest_device_output_series=[
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
                "metrics_code": DeviceValueTypeEnum.WATER_FLOW.code,
                "node_id": 20100,
                "time_series": [{"step": 2, "value": 16.0}],
            },
        ],
    )

    commands = agent.on_optimization(2)

    assert len(commands) == 1
    command = commands[0]
    assert command["target_agent_code"] == "TARGET_AGENT_20300"
    assert command["target_command_type"] == MPC_STATION_FLOW_COMMAND_TYPE
    assert command["target_value"] == 42.0
    assert command["object_id"] == 20300
    assert command["object_type"] == "PowerStation"
    assert command["main_step_index"] == 2
    assert command["group_size"] == 1
    assert command["group_id"].startswith(
        "POWER_STATION_OUT_FLOW:power-scene-flow-fallback-001:2:TARGET_AGENT_20300:"
    )


def test_power_scheduling_outflow_update_is_ack_only():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-005")

    _configure_mpc_task_state(agent, roll_steps=10)
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
                hydro_event_source_type="OUTFLOW_PLANNING",
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
    agent._hydrosim_api.apply_time_series_event_update.assert_not_called()


def test_power_scheduling_time_series_update_passes_current_step_cache_to_hydrosim():
    module = _load_power_scheduling_module()
    agent, context, _ = _build_agent(module, "power-scene-006")

    _configure_mpc_task_state(agent, roll_steps=10)
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
    reservoirs = [
        SimpleNamespace(history={"current_outflow_discharge": []})
        for _ in stations
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
        multi_reservoir=SimpleNamespace(Capacity_Stairs=reservoirs),
        multi_stair=SimpleNamespace(multi_stair=stations),
    )
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-001",
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
        for reservoir, spill_flow in zip(reservoirs, (12.0, 8.0, 4.0, 2.0)):
            reservoir.history["current_outflow_discharge"].append(spill_flow)

    api._execute_runtime_step = Mock(side_effect=_fake_execute_runtime_step)

    result = api.execute_step(step_index=0)

    assert result["station_step_outputs"][0]["power"] == 1160.0
    assert result["station_step_outputs"][0]["diversion_flow"] == 12.0
    device_metrics = {
        (item["object_id"], item["metrics_code"]): item["value"]
        for item in result["device_step_outputs"]
    }
    assert device_metrics[(20304, "output_power")] == 87.6
    assert device_metrics[(20304, "water_flow")] == 42.5
    assert device_metrics[(20101, "water_flow")] == 16.2
    assert device_metrics[(20101, "gate_opening")] == 1.75


def test_hydrosim_station_power_series_contains_reservoir_evidence():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    stations = [
        SimpleNamespace(name="Station-20100", history={"current_power": [123.456789]}),
        SimpleNamespace(name="Station-20300", history={"current_power": [0.0]}),
        SimpleNamespace(name="Station-20500", history={"current_power": [0.0]}),
        SimpleNamespace(name="Station-20700", history={"current_power": [0.0]}),
    ]
    reservoirs = [
        SimpleNamespace(
            history={
                "current_outflow_discharge": [45.1234567],
                "current_inflow": [500.1234567],
                "current_outflow_power": [300.0],
                "current_outflow_discharge_ff": [180.0],
                "current_spill_ff_gain": [1.0],
                "current_spill_ff_deadband": [20.0],
                "current_spill_ff_surplus": [180.0],
                "current_spill_ff_force_pass": [False],
                "current_pid_output": [15.0],
                "current_target_spill": [195.0],
                "current_spill_delta": [45.0],
            }
        ),
        SimpleNamespace(history={"current_outflow_discharge": [0.0]}),
        SimpleNamespace(history={"current_outflow_discharge": [0.0]}),
        SimpleNamespace(history={"current_outflow_discharge": [0.0]}),
    ]

    series = api._build_station_power_series_from_runtime(
        [2],
        SimpleNamespace(multi_stair=stations),
        SimpleNamespace(Capacity_Stairs=reservoirs),
    )

    first_station = series[0]
    assert first_station["node_id"] == 20100
    assert first_station["time_series"] == [{"step": 2, "value": 123.456789}]
    assert first_station["diversion_flow_time_series"] == [{"step": 2, "value": 45.123457}]
    assert first_station["reservoir_evidence_time_series"][0]["step"] == 2
    assert first_station["reservoir_evidence_time_series"][0]["current_inflow"] == 500.123457
    assert first_station["reservoir_evidence_time_series"][0]["current_spill_ff_force_pass"] is False


def test_hydrosim_configured_yaml_extraction_contains_reservoir_evidence(tmp_path):
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    yaml_path = tmp_path / "configured_outputs.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "object_time_series": [
                    {
                        "object_type": "Station",
                        "object_ids": [20100],
                        "object_name": "Station-20100",
                        "metrics_code": "diversion_flow",
                        "time_series": [{"step": 2, "value": 45.1234567}],
                    }
                ],
                "station_power_plan_used": [
                    {
                        "node_id": 20100,
                        "station": "Station-20100",
                        "time_series": [{"step": 2, "value": 123.456789}],
                    }
                ],
                "station_reservoir_evidence": [
                    {
                        "node_id": 20100,
                        "station": "Station-20100",
                        "time_series": [
                            {
                                "step": 2,
                                "current_inflow": 500.1234567,
                                "current_outflow_power": 300.0,
                                "current_outflow_discharge_ff": 180.0,
                                "current_spill_ff_gain": 1.0,
                                "current_spill_ff_deadband": 20.0,
                                "current_spill_ff_surplus": 180.0,
                                "current_spill_ff_force_pass": False,
                                "current_pid_output": 15.0,
                                "current_target_spill": 195.0,
                                "current_spill_delta": 45.0,
                            }
                        ],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    series = api._extract_station_power_series_from_yaml(str(yaml_path))

    assert series[0]["node_id"] == 20100
    assert series[0]["time_series"] == [{"step": 2, "value": 123.456789}]
    assert series[0]["diversion_flow_time_series"] == [{"step": 2, "value": 45.123457}]
    evidence = series[0]["reservoir_evidence_time_series"][0]
    assert evidence["step"] == 2
    assert evidence["current_inflow"] == 500.123457
    assert evidence["current_spill_ff_force_pass"] is False


def test_hydrosim_result_factory_builds_configured_reservoir_evidence_series():
    _load_hydrosim_api_module()
    from hydrosim.result_factory import HydroSimulationResultFactory

    runtime = SimpleNamespace(
        __version__="test",
        STATION_NODE_IDS=[20100],
        NODE_TO_INDEX={20100: 0},
        _station_name_by_node=Mock(return_value={20100: "Station-20100"}),
    )
    result_factory = HydroSimulationResultFactory(runtime=runtime)
    reservoirs = [
        SimpleNamespace(
            history={
                "current_inflow": [500.1234567, 501.0],
                "current_outflow_power": [300.0, 301.0],
                "current_outflow_discharge_ff": [180.0, 181.0],
                "current_spill_ff_gain": [1.0, 1.0],
                "current_spill_ff_deadband": [20.0, 20.0],
                "current_spill_ff_surplus": [180.0, 181.0],
                "current_spill_ff_force_pass": [False, True],
                "current_pid_output": [15.0, 16.0],
                "current_target_spill": [195.0, 197.0],
                "current_spill_delta": [45.0, 46.0],
            }
        )
    ]

    series = result_factory._station_reservoir_evidence_series(
        [2, 3],
        SimpleNamespace(Capacity_Stairs=reservoirs),
        sample_interval=1,
    )

    assert series[0]["node_id"] == 20100
    assert series[0]["time_series"][0]["step"] == 2
    assert series[0]["time_series"][0]["current_inflow"] == 500.123457
    assert series[0]["time_series"][1]["current_spill_ff_force_pass"] is True


def test_hydrosim_execute_step_rounds_outputs_to_six_decimals():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    stations = [
        SimpleNamespace(name="Station-20100", history={"current_power": []}),
        SimpleNamespace(name="Station-20300", history={"current_power": []}),
        SimpleNamespace(name="Station-20500", history={"current_power": []}),
        SimpleNamespace(name="Station-20700", history={"current_power": []}),
    ]
    reservoirs = [
        SimpleNamespace(history={"current_outflow_discharge": []})
        for _ in stations
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
        multi_reservoir=SimpleNamespace(Capacity_Stairs=reservoirs),
        multi_stair=SimpleNamespace(multi_stair=stations),
    )
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-precision-001",
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
        for reservoir, spill_flow in zip(
            reservoirs,
            (12.123456789, 8.987654321, 4.222222222, 2.333333333),
        ):
            reservoir.history["current_outflow_discharge"].append(spill_flow)

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
    station_spill_metrics = {
        item["node_id"]: item["diversion_flow"]
        for item in result["station_step_outputs"]
    }
    planning_values = {
        item["object_id"]: item["value"]
        for item in result["current_step_power_planning_values"]
    }
    assert station_metrics[20100] == 1160.123457
    assert station_metrics[20300] == 180.987654
    assert station_spill_metrics[20100] == 12.123457
    assert station_spill_metrics[20300] == 8.987654
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
    assert merged_series[(20300, "output_power")] == 100.0
    assert result["updated_time_series_count"] == 2


def test_hydrosim_apply_time_series_event_update_replaces_matching_outflow_series():
    hydrosim_api = _load_hydrosim_api_module()
    api = hydrosim_api.HydroSimulationApi()
    api._session = hydrosim_api.HydroSimulationSession(
        session_id="session-merge-steps-001",
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
            hydro_event_source_type="OUTFLOW_PLANNING",
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
            hydro_event_source_type="OUTFLOW_PLANNING",
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
