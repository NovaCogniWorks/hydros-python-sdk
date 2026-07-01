import importlib
import os
import sys
import types
from unittest.mock import Mock

from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import SimTaskInitRequest, TickCmdRequest, TimeSeriesDataUpdateRequest
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import CommandStatus, HydroAgent, ObjectTimeSeries, SimulationContext


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

    client = Mock(mqtt_client=Mock(), state_manager=Mock())
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
    agent._control_command_dispatcher.dispatch = Mock()

    result = agent.on_tick_simulation(
        TickCmdRequest(
            command_id="tick-001",
            context=context,
            step=7,
        )
    )

    assert result is None
    agent.on_optimization.assert_called_once_with(7)
    agent._control_command_dispatcher.dispatch.assert_called_once_with(commands)


def test_pump_scheduling_agent_subscribes_metrics_before_lazy_init(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")

    client = Mock(mqtt_client=Mock(), state_manager=Mock())
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


def test_pump_scheduling_time_series_update_activates_generic_task_state(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")

    client = Mock(mqtt_client=Mock(), state_manager=Mock())
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
    task_state = agent._task_state_lifecycle.task_state
    assert task_state is not None
    assert task_state.current_step == 12
    assert task_state.context is context
    assert task_state.algorithm_config_url == "custom-agent/pump/data/config_xhh.yaml"
    assert task_state.hydro_events == [request.time_series_data_changed_event]
