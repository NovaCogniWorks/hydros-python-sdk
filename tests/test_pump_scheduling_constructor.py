import importlib
import os
import sys
import types
from threading import Event, Thread
from unittest.mock import Mock

from hydros_agent_sdk.control_algorithms import ControlSignal, SignalType
from hydros_agent_sdk.utils import HydroObjectType, MetricsCodes
from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.mpc.models import ControlObjectResult, HorizonStep, ValueItem
from hydros_agent_sdk.protocol.agent_commands import (
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.protocol.commands import (
    EdgeControlExecutionReport,
    SimTaskInitRequest,
    SimTaskTerminateRequest,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    CommandStatus,
    HydroAgent,
    HydroAgentInstance,
    ObjectTimeSeries,
    SimulationContext,
)


def _install_optional_dependency_stubs(monkeypatch):
    scipy_module = types.ModuleType("scipy")
    scipy_optimize_module = types.ModuleType("scipy.optimize")
    scipy_optimize_module.differential_evolution = lambda *args, **kwargs: None
    scipy_module.optimize = scipy_optimize_module

    numpy_module = types.ModuleType("numpy")
    pandas_module = types.ModuleType("pandas")
    pandas_module.DataFrame = lambda *args, **kwargs: []

    flow_depart_module = types.ModuleType("flow_depart")
    flow_depart_module.generate_flow_depart = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "scipy", scipy_module)
    monkeypatch.setitem(sys.modules, "scipy.optimize", scipy_optimize_module)
    monkeypatch.setitem(sys.modules, "numpy", numpy_module)
    monkeypatch.setitem(sys.modules, "pandas", pandas_module)
    monkeypatch.setitem(sys.modules, "flow_depart", flow_depart_module)


def test_pump_scheduling_agent_uses_generic_central_base(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")

    assert issubclass(module.PumpCentralSchedulingAgent, CentralSchedulingAgent)
    assert not hasattr(module, "MpcCentralSchedulingAgent")

    client = Mock(state_manager=Mock())
    context = SimulationContext(biz_scene_instance_id="task-001")
    agent = module.PumpCentralSchedulingAgent(
        sim_coordination_client=client,
        agent_id="agent-001",
        agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Pump Scheduling Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        mpc_config_url="custom-agent/pump/data/config_xhh.yaml",
    )

    assert not hasattr(agent, "_mpc_rolling_runtime")
    assert not hasattr(agent, "_mpc_optimization_service")
    assert agent._configured_mpc_config_url == "custom-agent/pump/data/config_xhh.yaml"

    commands = [{"target_agent_code": "agent", "target_command_type": "BLADE_ANGLE"}]
    object.__setattr__(agent, "on_optimization", Mock(return_value=commands))
    agent.dispatch_control_commands_and_await_execution = Mock()

    result = agent.on_tick_simulation(
        TickCmdRequest(
            command_id="tick-001",
            context=context,
            step=7,
        )
    )

    assert result is None
    agent.on_optimization.assert_called_once_with(7)
    agent.dispatch_control_commands_and_await_execution.assert_called_once_with(commands)


def test_pump_tick_waits_for_edge_terminal_report_before_returning(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")
    client = Mock(state_manager=Mock(), transport=Mock())
    context = SimulationContext(biz_scene_instance_id="pump-terminal-barrier")
    agent = module.PumpCentralSchedulingAgent(
        sim_coordination_client=client,
        agent_id="pump-central",
        agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Pump Scheduling Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        control_execution_timeout_seconds=1,
    )
    target = HydroAgentInstance(
        agent_id="station",
        agent_code="GATE_STATION_AGENT",
        agent_type="GATE_STATION_AGENT",
        agent_name="Station",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster",
        hydros_node_id="node-edge",
        context=context,
        drive_mode=AgentDriveMode.PROACTIVE,
    )
    command = HydroStationTargetValueRequest(
        command_id="AGTCMD_PUMP_TERMINAL",
        context=context,
        source=agent,
        target=target,
        object_id=20000,
        object_type="PumpStation",
        target_value=32.0,
        target_value_type="water_flow",
        group_id="pump-station-flow:12",
        group_size=1,
        main_step_index=12,
    )
    agent._ensure_mpc_task_state = Mock(return_value=Mock())
    agent.on_optimization = Mock(return_value=[{"unused": "dict-intent"}])
    agent._control_command_dispatcher.prepare = Mock(return_value=[command])
    dispatched = Event()
    returned = Event()

    def send_command(dispatched_command):
        assert dispatched_command is command
        agent._handle_control_command_response(
            HydroStationTargetValueResponse.from_request(
                command,
                command_status=CommandStatus.SUCCEED,
                success=True,
            )
        )
        dispatched.set()

    agent._control_command_dispatcher.send_command = send_command

    worker = Thread(
        target=lambda: (
            agent.on_tick_simulation(
                TickCmdRequest(command_id="tick-pump-terminal", context=context, step=12)
            ),
            returned.set(),
        )
    )
    worker.start()
    assert dispatched.wait(0.2)
    assert not returned.is_set(), "command acceptance must not release the pump tick"

    agent.on_station_control_execution(
        EdgeControlExecutionReport(
            command_id="SIMCMD_PUMP_TERMINAL",
            context=context,
            broadcast=True,
            source_agent_instance=target,
            target_agent_instance=agent,
            exec_command_id=command.command_id,
            object_type=command.object_type,
            object_id=command.object_id,
            target_value_type=command.target_value_type,
            target_value=command.target_value,
            exec_status="COMPLETED",
        )
    )
    worker.join(timeout=0.2)
    assert not worker.is_alive()
    assert returned.is_set()


def test_pump_scheduling_builds_grouped_station_flow_commands_from_current_horizon(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")
    horizon_step_list = [
        HorizonStep(
            horizon_step=1,
            control_object_list=[
                ControlObjectResult(
                    object_id=1001,
                    object_type=HydroObjectType.PUMP_STATION,
                    target_value_list=[
                        ValueItem(value_type=MetricsCodes.WATER_FLOW, value=123.456),
                    ],
                ),
                ControlObjectResult(
                    object_id=2001,
                    object_type=HydroObjectType.PUMP,
                    target_value_list=[
                        ValueItem(value_type="blade_angle", value=4.5),
                    ],
                ),
            ],
        ),
        HorizonStep(
            horizon_step=2,
            control_object_list=[
                ControlObjectResult(
                    object_id=1001,
                    object_type=HydroObjectType.PUMP_STATION,
                    target_value_list=[
                        ValueItem(value_type=MetricsCodes.WATER_FLOW, value=999.0),
                    ],
                ),
            ],
        ),
    ]

    commands = module.PumpCentralSchedulingAgent._build_station_flow_control_commands(
        horizon_step_list=horizon_step_list,
        current_step=8,
    )

    assert commands == [
        {
            "target_agent_code": "STATION_AGENT",
            "target_command_type": "water_flow",
            "target_value": "123.46",
            "object_id": 1001,
            "object_type": "PumpStation",
            "group_id": "pump-station-flow:8",
            "group_size": 1,
            "main_step_index": 8,
        }
    ]


def test_pump_scheduling_preserves_algo_required_inputs_in_station_flow_command(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")
    planning_signal = ControlSignal(
        type=SignalType.REFERENCE,
        object_type=HydroObjectType.PUMP_STATION,
        object_id=1001,
        value_type="station_front_water_level",
        series=[12.3, 12.4],
    )
    commands = module.PumpCentralSchedulingAgent._build_station_flow_control_commands(
        horizon_step_list=[
            HorizonStep(
                horizon_step=1,
                control_object_list=[
                    ControlObjectResult(
                        object_id=1001,
                        object_type=HydroObjectType.PUMP_STATION,
                        target_value_list=[
                            ValueItem(
                                value_type=MetricsCodes.WATER_FLOW,
                                value=123.456,
                            ),
                        ],
                        algo_required_inputs=[planning_signal],
                    ),
                ],
            ),
        ],
        current_step=8,
    )

    assert commands[0]["algo_required_inputs"] == [planning_signal]


def test_pump_scheduling_agent_subscribes_metrics_before_lazy_init(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")

    client = Mock(state_manager=Mock())
    context = SimulationContext(biz_scene_instance_id="task-init")
    agent = module.PumpCentralSchedulingAgent(
        sim_coordination_client=client,
        agent_id="agent-init",
        agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Pump Scheduling Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
    )
    call_order = []
    agent.load_agent_configuration = Mock(side_effect=lambda request: call_order.append("load_config"))
    agent.subscribe_field_metrics = Mock(side_effect=lambda: call_order.append("subscribe_metrics"))
    agent._lazy_init_odd_mpc = Mock(side_effect=lambda: call_order.append("lazy_init"))
    agent._agent_command_gateway.start = Mock(side_effect=lambda: call_order.append("start_gateway"))

    request = SimTaskInitRequest(
        command_id="init-001",
        context=context,
        agent_list=[
            HydroAgent(
                agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
                agent_type="CENTRAL_SCHEDULING_AGENT",
                agent_name="Pump Scheduling Agent",
                agent_configuration_url="",
            )
        ],
    )

    response = agent.on_init(request)

    assert response.command_status == CommandStatus.SUCCEED
    assert call_order[:3] == ["load_config", "subscribe_metrics", "lazy_init"]
    agent.subscribe_field_metrics.assert_called_once_with()
    agent._lazy_init_odd_mpc.assert_called_once_with()


def test_pump_scheduling_time_series_update_activates_mpc_task_state(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")

    client = Mock(state_manager=Mock())
    context = SimulationContext(biz_scene_instance_id="task-002")
    agent = module.PumpCentralSchedulingAgent(
        sim_coordination_client=client,
        agent_id="agent-002",
        agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Pump Scheduling Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        mpc_config_url="custom-agent/pump/data/config_xhh.yaml",
    )

    request = TimeSeriesDataUpdateRequest(
        command_id="ts-001",
        context=context,
        time_series_data_changed_event=TimeSeriesDataChangedEvent(
            hydro_event_source_type="WATER_USE",
            auto_schedule_at_step=12,
            object_time_series=[
                ObjectTimeSeries(object_id=1001, object_name="water-use")
            ],
        ),
        broadcast=False,
    )

    response = agent.on_time_series_data_update(request)

    assert response.command_status == CommandStatus.SUCCEED
    task_state = agent._mpc_task_state_lifecycle.task_state
    assert task_state is not None
    assert task_state.current_step == 12
    assert task_state.context is context
    assert task_state.algorithm_config_url == "custom-agent/pump/data/config_xhh.yaml"
    assert task_state.hydro_events == [request.time_series_data_changed_event]


def test_pump_scheduling_termination_clears_mpc_task_state(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")
    context = SimulationContext(biz_scene_instance_id="task-terminate")
    agent = module.PumpCentralSchedulingAgent(
        sim_coordination_client=Mock(state_manager=Mock()),
        agent_id="agent-terminate",
        agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Pump Scheduling Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
    )
    agent._mpc_task_state_lifecycle.ensure_task_state(1)
    agent.discard_control_execution_waiters = Mock()
    agent._agent_command_gateway.shutdown = Mock()

    response = agent.on_terminate(
        SimTaskTerminateRequest(command_id="terminate-pump", context=context)
    )

    assert response.command_status == CommandStatus.SUCCEED
    assert agent._mpc_task_state_lifecycle.task_state is None
    agent.discard_control_execution_waiters.assert_called_once_with()
    agent._agent_command_gateway.shutdown.assert_called_once_with()
