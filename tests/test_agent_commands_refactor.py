import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hydros_agent_sdk import HydroObjectType, generate_agent_command_id, get_default_env_config_path, load_env_config
from hydros_agent_sdk.agent_commands import (
    AgentCommandClient,
    AgentCommandEnvelope,
    AgentCommandHandler,
    AgentCommandRuntime,
    HydroDirectGateOpeningRequest,
    HydroDirectGateOpeningResponse,
)
from hydros_agent_sdk.agent_commands.models import DeviceValueTypeEnum
from hydros_agent_sdk.agent_commands.runtime.testing import wait_command_completed
from hydros_agent_sdk.agents import CentralSchedulingAgent
from hydros_agent_sdk.agents.central_scheduling_agent import MpcTaskState
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.mpc.client import MpcPlanningClient, MpcPlanningError
from hydros_agent_sdk.mpc.models import (
    DeviceOpening,
    HorizonControlStep,
    MpcOptimizeResponse,
    SensorData,
    TargetNode,
)
from hydros_agent_sdk.mpc.reporter import MpcResultReporter
from hydros_agent_sdk.protocol.commands import (
    MpcResultReport,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    AgentDriveMode,
    BizScenario,
    HydroAgent,
    CommandStatus,
    HydroAgentInstance,
    ObjectTimeSeries,
    SimulationContext,
    Tenant,
    TimeSeriesValue,
    Waterway,
)
from hydros_agent_sdk.runtime import RuntimeEnvSettings
from hydros_agent_sdk.state_manager import AgentStateManager


def build_agent_instance(agent_id: str, agent_code: str, node_id: str, context: SimulationContext) -> HydroAgentInstance:
    return HydroAgentInstance(
        agent_id=agent_id,
        agent_code=agent_code,
        agent_type=agent_code,
        agent_name=agent_code,
        agent_configuration_url="",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="demo-cluster",
        hydros_node_id=node_id,
        context=context,
        agent_status=AgentStatus.INIT,
        drive_mode=AgentDriveMode.PROACTIVE,
    )


class DirectGateHandler(AgentCommandHandler[HydroDirectGateOpeningRequest, HydroDirectGateOpeningResponse]):
    def get_command(self) -> str:
        return "direct_gate_opening_request"

    @property
    def response_type(self):
        return HydroDirectGateOpeningResponse

    def execute(self, request: HydroDirectGateOpeningRequest) -> HydroDirectGateOpeningResponse:
        return HydroDirectGateOpeningResponse.from_request(
            request,
            command_status=CommandStatus.SUCCEED,
            success=True,
            final_gate_opening=request.gate_opening,
        )


class CentralSchedulingAgentForTest(CentralSchedulingAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.optimization_steps = []
        self.optimization_result = None

    def load_agent_configuration(self, request):
        # 测试里不走外部配置，直接给一个空 properties 就够了。
        return None

    def on_init(self, request: SimTaskInitRequest):
        self._start_agent_command_client()
        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False,
        )

    def on_optimization(self, step: int):
        self.optimization_steps.append(step)
        return self.optimization_result

    def on_terminate(self, request: SimTaskTerminateRequest):
        self._shutdown_agent_command_client()
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )


class ProductionCentralSchedulingAgentForTest(CentralSchedulingAgent):
    def load_agent_configuration(self, request):
        return None

    def on_init(self, request: SimTaskInitRequest):
        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False,
        )

    def on_terminate(self, request: SimTaskTerminateRequest):
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )


class FakeMpcPlanningClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def execute_optimization(self, mpc_task_state, sensor_data, sensor_provider=None):
        self.calls.append(
            {
                "state": mpc_task_state,
                "sensor_data": list(sensor_data),
                "sensor_provider": sensor_provider,
            }
        )
        return self.responses


class FakeMpcResultReporter:
    def __init__(self):
        self.published = []

    def publish(self, source_agent_instance, mpc_task_state, responses):
        self.published.append(
            {
                "source": source_agent_instance,
                "state": mpc_task_state,
                "responses": list(responses),
            }
        )
        return None


class TestSiblingCacheCallback(SimCoordinationCallback):
    def get_component(self) -> str:
        return "TEST_CALLBACK"

    def on_sim_task_init(self, request: SimTaskInitRequest):
        return None

    def on_tick(self, request):
        return None

    def is_remote_agent(self, agent_instance) -> bool:
        return True


def build_time_series_update_request(
    context: SimulationContext,
    command_id: str = "ts-update-001",
    auto_schedule_at_step: int = 1,
) -> TimeSeriesDataUpdateRequest:
    return TimeSeriesDataUpdateRequest(
        command_id=command_id,
        context=context,
        time_series_data_changed_event=TimeSeriesDataChangedEvent(
            auto_schedule_at_step=auto_schedule_at_step,
            hydro_event_source_type="WEATHER_FORECAST",
            object_time_series=[
                ObjectTimeSeries(
                    object_id=1001,
                    object_name="node-1001",
                    metrics_code="water_flow",
                    time_series=[
                        TimeSeriesValue(step=auto_schedule_at_step, value=12.0),
                        TimeSeriesValue(step=auto_schedule_at_step + 3, value=15.0),
                    ],
                )
            ],
        ),
    )


class AgentCommandsRefactorTest(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._temp_dir.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._temp_dir.cleanup()

    def test_agent_command_envelope_uses_registry_parser(self):
        context = SimulationContext(biz_scene_instance_id="scene-001")
        source = build_agent_instance("source-001", "SOURCE_AGENT", "node-a", context)
        target = build_agent_instance("target-001", "TARGET_AGENT", "node-b", context)

        envelope = AgentCommandEnvelope(
            command={
                "command_id": "cmd-001",
                "command_type": "direct_gate_opening_request",
                "source": source.model_dump(mode="json"),
                "target": target.model_dump(mode="json"),
                "gate_opening": 0.75,
            }
        )

        self.assertIsInstance(envelope.command, HydroDirectGateOpeningRequest)
        self.assertEqual(envelope.command.command_id, "cmd-001")
        self.assertAlmostEqual(envelope.command.gate_opening, 0.75)

    def test_client_on_message_no_longer_filters_remote_target_early(self):
        client = AgentCommandClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
        )
        client.runtime.handle_incoming_command = Mock()

        context = SimulationContext(biz_scene_instance_id="scene-002")
        source = build_agent_instance("source-002", "SOURCE_AGENT", "node-a", context)
        remote_target = build_agent_instance("target-002", "TARGET_AGENT", "node-remote", context)
        payload = {
            "command_id": "cmd-002",
            "command_type": "direct_gate_opening_request",
            "source": source.model_dump(mode="json"),
            "target": remote_target.model_dump(mode="json"),
            "gate_opening": 0.31,
        }

        client._on_message(None, None, SimpleNamespace(payload=json.dumps(payload).encode("utf-8")))

        client.runtime.handle_incoming_command.assert_called_once()

    def test_client_start_cleans_up_when_connection_times_out(self):
        client = AgentCommandClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
        )
        client.mqtt_client.connect = Mock()
        client.mqtt_client.loop_start = Mock()
        client.mqtt_client.loop_stop = Mock()
        client.mqtt_client.disconnect = Mock()
        client._connected.wait = Mock(return_value=False)
        client.runtime.start = Mock()

        with self.assertRaises(RuntimeError):
            client.start()

        client.mqtt_client.loop_stop.assert_called_once()
        client.mqtt_client.disconnect.assert_called_once()
        client.runtime.start.assert_not_called()
        self.assertTrue(client._intentional_disconnect)

    def test_client_lazy_builds_runtime(self):
        client = AgentCommandClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
        )

        self.assertIsNone(client._runtime)
        self.assertFalse(os.path.exists(os.path.join("data", "agent_data.db")))

        runtime = client.runtime

        self.assertIsNotNone(runtime)
        self.assertIsNotNone(client._runtime)
        self.assertTrue(os.path.exists(os.path.join("data", "agent_data.db")))

    def test_runtime_serializes_biz_scenario_id_as_string(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        context = SimulationContext(
            biz_scene_instance_id="scene-010",
            biz_scenario=BizScenario(
                biz_scenario_id="biz-scenario-010",
                biz_scenario_name="Demo Scenario",
            ),
        )
        source = build_agent_instance("source-010", "SOURCE_AGENT", "node-a", context)
        target = build_agent_instance("target-010", "TARGET_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        state_manager.add_local_agent(target)

        runtime = AgentCommandRuntime(
            state_manager=state_manager,
            sender=lambda command: None,
            max_workers=1,
        )

        runtime.send_command(
            HydroDirectGateOpeningRequest(
                command_id="cmd-010",
                source=source,
                target=target,
                gate_opening=0.42,
            )
        )

        entry = runtime.log_store.find_command_log_by_request_id("cmd-010", "node-a")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.biz_scenario_id, "biz-scenario-010")
        self.assertIsInstance(entry.biz_scenario_id, str)

    def test_runtime_can_restart_after_stop(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        context = SimulationContext(biz_scene_instance_id="scene-003")
        source = build_agent_instance("source-003", "SOURCE_AGENT", "node-a", context)
        target = build_agent_instance("target-003", "TARGET_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        state_manager.add_local_agent(target)

        sent_commands = []
        runtime = AgentCommandRuntime(
            state_manager=state_manager,
            sender=sent_commands.append,
            max_workers=1,
        )
        runtime.register_handler(DirectGateHandler())

        def send_and_wait(command_id: str, gate_opening: float):
            runtime.send_command(
                HydroDirectGateOpeningRequest(
                    command_id=command_id,
                    source=source,
                    target=target,
                    gate_opening=gate_opening,
                )
            )
            entry = wait_command_completed(runtime, command_id, timeout_seconds=2.0)
            self.assertEqual(entry.command_status, CommandStatus.SUCCEED)
            self.assertIsNotNone(entry.command_response)

        runtime.start()
        send_and_wait("cmd-003a", 0.12)
        runtime.stop()
        self.assertTrue(os.path.exists(os.path.join("data", "agent_data.db")))

        runtime.start()
        send_and_wait("cmd-003b", 0.24)
        runtime.stop()

        self.assertEqual(sent_commands, [])

    def test_central_scheduling_agent_starts_agent_command_client(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            mqtt_username="cmd-user",
            mqtt_password="cmd-pass",
        )

        context = SimulationContext(biz_scene_instance_id="scene-004")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-004",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        request = SimTaskInitRequest(
            command_id="init-004",
            context=context,
            agent_list=[
                HydroAgent(
                    agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
                    agent_type="CENTRAL_SCHEDULING_AGENT",
                    agent_name="中央调度智能体",
                )
            ],
        )

        with patch("hydros_agent_sdk.agents.central_scheduling_agent.AgentCommandClient") as mock_client_cls:
            mock_client = Mock()
            mock_client_cls.return_value = mock_client

            agent.on_init(request)
            agent.send_command(Mock())
            agent.on_terminate(SimTaskTerminateRequest(command_id="term-004", context=context))

            mock_client_cls.assert_called_once_with(
                broker_url="127.0.0.1",
                broker_port=1883,
                hydros_cluster_id="demo-cluster",
                state_manager=state_manager,
                mqtt_username="cmd-user",
                mqtt_password="cmd-pass",
            )
            mock_client.start.assert_called_once()
            mock_client.send_command.assert_called_once()
            mock_client.stop.assert_called_once()

    def test_central_scheduling_agent_builds_station_target_value_request(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-006")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-006",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        target = build_agent_instance("target-006", "PUMP_AGENT_001", "node-b", context)

        with patch.object(agent, "get_sibling_agent_instance", return_value=target):
            request = agent._build_station_target_value_request(
                target_agent_code="PUMP_AGENT_001",
                target_command_type=DeviceValueTypeEnum.GATE_OPENING.code,
                target_value=1.25,
                object_id=1023,
                object_type=HydroObjectType.PUMP,
            )

        self.assertIsNotNone(request)
        self.assertEqual(request.command_type, "update_station_target_value_request")
        self.assertEqual(request.target.agent_code, "PUMP_AGENT_001")
        self.assertEqual(request.target_value_type, DeviceValueTypeEnum.GATE_OPENING.code)
        self.assertEqual(request.target_value, 1.25)

    def test_central_scheduling_agent_sends_control_commands_in_base_method(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-008")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-008",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        control_command = {
            "target_agent_code": "PUMP_AGENT_001",
            "target_command_type": DeviceValueTypeEnum.OUTPUT_POWER.code,
            "target_value": 85.5,
            "object_id": 1021,
            "object_type": HydroObjectType.TURBINE,
        }
        pump_request = Mock(name="pump_request")
        with patch.object(CentralSchedulingAgent, "_build_station_target_value_request", return_value=pump_request) as build_request, \
             patch.object(CentralSchedulingAgent, "send_command") as send_command:
            agent._send_control_commands([control_command])

        build_request.assert_called_once_with(
            target_agent_code="PUMP_AGENT_001",
            target_command_type=DeviceValueTypeEnum.OUTPUT_POWER.code,
            target_value=85.5,
            object_id=1021,
            object_type=HydroObjectType.TURBINE,
        )
        send_command.assert_called_once_with(pump_request)

    def test_central_scheduling_agent_caches_recent_field_metrics_by_horizon(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-007")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-007",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
        )

        for step_index, value in [(1, 1.0), (2, 2.0), (3, 3.0), (4, 4.0)]:
            agent._on_field_metrics_received(
                "metrics/topic",
                {
                    "object_id": 1001,
                    "metrics_code": "flow",
                    "value": value,
                    "timestamp": f"ts-{step_index}",
                    "step_index": step_index,
                    "position_code": "none",
                },
            )

        self.assertEqual(agent.get_field_metrics_value(1001, "flow"), 4.0)
        self.assertEqual(set(agent.get_field_metrics_history().keys()), {2, 3, 4})
        self.assertNotIn(1, agent.get_field_metrics_history())
        self.assertEqual(agent.get_field_metrics_by_step(4)["1001_flow"]["value"], 4.0)

    def test_central_scheduling_agent_filters_field_metrics_by_position_code(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-007-position")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-007-position",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
        )

        agent._on_field_metrics_received(
            "metrics/topic",
            {
                "object_id": 1001,
                "metrics_code": "flow",
                "value": 1.0,
                "step_index": 1,
                "position_code": "upstream",
            },
        )
        agent._on_field_metrics_received(
            "metrics/topic",
            {
                "object_id": 1001,
                "metrics_code": "flow",
                "value": 2.0,
                "step_index": 2,
                "position_code": "none",
            },
        )

        self.assertEqual(agent.get_field_metrics_value(1001, "flow"), 2.0)
        self.assertEqual(agent.get_field_metrics_by_step(1), {})
        self.assertEqual(agent.get_field_metrics_by_step(2)["1001_flow"]["position_code"], "none")

    def test_central_scheduling_agent_activates_mpc_on_time_series_update(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-011")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-011",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
            total_steps=20,
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )

        response = agent.on_time_series_data_update(
            build_time_series_update_request(context, auto_schedule_at_step=5)
        )

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        self.assertEqual(agent.optimization_steps, [5])
        self.assertTrue(agent.is_mpc_optimizing_on_the_loop())
        self.assertEqual(agent.mpc_task_state.start_step, 5)
        self.assertEqual(agent.mpc_task_state.current_step, 5)
        self.assertEqual(agent.mpc_task_state.rolling_interval_steps, 3)
        self.assertEqual(agent.mpc_task_state.total_steps, 20)
        self.assertEqual(agent.mpc_task_state.mpc_config_url, "http://config/mpc.yaml")
        self.assertEqual(agent.mpc_task_state.target_and_constrain_config_url, "http://config/control.yaml")
        self.assertEqual(len(agent.mpc_task_state.hydro_events), 1)
        self.assertEqual(agent.agent_status, AgentStatus.ACTIVE)

    def test_central_scheduling_agent_reads_mpc_config_urls_from_configured_property_names(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-011-config-alias")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-011-config-alias",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
            total_steps=20,
        )
        agent.properties.update(
            {
                "mpc_config_url": "http://config/mpc.yaml",
                "target_and_constrain_config_url": "http://config/control.yaml",
            }
        )

        response = agent.on_time_series_data_update(
            build_time_series_update_request(context, auto_schedule_at_step=5)
        )

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        self.assertEqual(agent.mpc_task_state.mpc_config_url, "http://config/mpc.yaml")
        self.assertEqual(
            agent.mpc_task_state.target_and_constrain_config_url,
            "http://config/control.yaml",
        )

    def test_central_scheduling_agent_auto_starts_mpc_on_tick_and_rolls(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-012")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-012",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
            total_steps=20,
        )

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-before", context=context, step=0))
        self.assertEqual(agent.optimization_steps, [0])
        self.assertTrue(agent.is_mpc_optimizing_on_the_loop())
        self.assertEqual(agent.mpc_task_state.start_step, 0)

        agent.on_time_series_data_update(
            build_time_series_update_request(context, command_id="ts-update-012", auto_schedule_at_step=1)
        )
        self.assertEqual(agent.optimization_steps, [0])
        self.assertEqual(len(agent.mpc_task_state.hydro_events), 1)

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-2", context=context, step=2))
        self.assertEqual(agent.optimization_steps, [0])

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-3", context=context, step=3))
        self.assertEqual(agent.optimization_steps, [0, 3])
        self.assertEqual(agent.mpc_task_state.current_loop, 3)

    def test_central_scheduling_agent_can_disable_tick_auto_start(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-012-disabled")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-012-disabled",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
            total_steps=20,
        )
        agent.properties["auto_start_mpc_on_tick"] = False

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-disabled", context=context, step=0))

        self.assertEqual(agent.optimization_steps, [])
        self.assertFalse(agent.is_mpc_optimizing_on_the_loop())

    def test_central_scheduling_agent_reads_mpc_service_base_url_from_environment(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-012-env-url")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-012-env-url",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
        )

        with patch.dict(
            os.environ,
            {"HYDROS_MPC_SERVICE_BASE_URL": "http://mpc.local/hydros/api/v1/mpc/planning/start"},
            clear=False,
        ):
            self.assertEqual(
                agent.get_mpc_service_base_url(),
                "http://mpc.local/hydros/api/v1/mpc/planning/start",
            )

    def test_runtime_env_settings_centralizes_defaults_and_overrides(self):
        with patch.dict(
            os.environ,
            {
                "HYDROS_CLUSTER_ID": "env-cluster",
                "HYDROS_MPC_SERVICE_BASE_URL": "http://mpc.env/hydros/api/v1/mpc/planning/start",
            },
            clear=True,
        ):
            settings = RuntimeEnvSettings.from_config(
                {
                    "hydros_cluster_id": "config-cluster",
                    "metrics_topic": "/hydros/data/edges/{hydros_cluster_id}",
                    "mpc_service_base_url": "http://mpc.config/hydros/api/v1/mpc/planning/start",
                }
            )

        self.assertEqual(settings.hydros_cluster_id, "env-cluster")
        self.assertEqual(settings.mpc_service_base_url, "http://mpc.env/hydros/api/v1/mpc/planning/start")
        self.assertEqual(settings.rendered_metrics_topic(), "/hydros/data/edges/env-cluster")

    def test_load_env_config_defaults_to_sdk_agents_env_properties(self):
        default_env_path = get_default_env_config_path()

        self.assertTrue(default_env_path.endswith("hydros_agent_sdk/agents/env.properties"))
        self.assertTrue(os.path.exists(default_env_path))
        self.assertEqual(load_env_config(), load_env_config(default_env_path))
        self.assertEqual(
            load_env_config()["mpc_service_base_url"],
            "http://192.168.20.52:8020/hydros/api/v1/mpc/planning/start",
        )

    def test_system_central_factory_passes_mpc_service_base_url_from_env_config(self):
        from hydros_agent_sdk.factory import SystemCentralSchedulingAgentFactory

        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )
        context = SimulationContext(biz_scene_instance_id="scene-012-factory-url")
        factory = SystemCentralSchedulingAgentFactory(
            env_config={
                "hydros_cluster_id": "demo-cluster",
                "hydros_node_id": "node-a",
                "mpc_service_base_url": "http://mpc.local/hydros/api/v1/mpc/planning/start",
            }
        )

        agent = factory.create_agent(sim_client, context)

        self.assertEqual(
            agent.get_mpc_service_base_url(),
            "http://mpc.local/hydros/api/v1/mpc/planning/start",
        )

    def test_mpc_planning_client_builds_java_compatible_request(self):
        context = SimulationContext(biz_scene_instance_id="scene-013")
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=10,
            current_step=15,
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )
        state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=1001,
                        object_name="lateral-inflow",
                        time_series=[
                            TimeSeriesValue(step=10, value=100.0),
                            TimeSeriesValue(step=20, value=200.0),
                        ],
                    )
                ],
            )
        )
        state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="DEVICE_FAULT",
                object_time_series=[ObjectTimeSeries(object_id=2001)],
            )
        )
        state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="WATER_USE",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=3001,
                        time_series=[
                            TimeSeriesValue(step=15, value=3.0),
                            TimeSeriesValue(step=18, value=4.0),
                        ],
                    )
                ],
            )
        )
        client = MpcPlanningClient(
            base_url="http://mpc.local/hydros/api/v1/mpc/planning/start",
            require_sensor_data=True,
        )

        request = client.build_optimize_request(
            state,
            [SensorData(object_id=9001, metrics_code="water_level", value=12.5, step_index=15)],
        )
        payload = request.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(payload["bizSceneInstanceId"], "scene-013")
        self.assertEqual(payload["stepIndex"], 15)
        self.assertEqual(payload["mpcConfigUrl"], "http://config/mpc.yaml")
        self.assertEqual(payload["controlConfigUrl"], "http://config/control.yaml")
        self.assertEqual(payload["upstreamBoundaries"]["1001"], [150.0, 200.0])
        self.assertEqual(payload["sensorData"][0]["objectId"], 9001)
        self.assertEqual(payload["sensorData"][0]["metricsCode"], "water_level")
        self.assertEqual(payload["fixedControls"], {"2001": 0.0})
        self.assertTrue(payload["includeDiversion"])
        self.assertNotIn("biz_scene_instance_id", payload)
        self.assertNotIn("upstream_boundaries", payload)
        self.assertNotIn("targets", payload)
        self.assert_no_snake_case_keys(payload)

    def test_mpc_planning_client_logs_request_and_response_payloads(self):
        context = SimulationContext(biz_scene_instance_id="scene-013-log")
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=2,
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )
        raw_response = {
            "success": True,
            "data": [
                {
                    "plan_type": "OPTIMAL",
                    "loss": 0.5,
                    "horizon_controls": [
                        {
                            "horizon_step": 1,
                            "opening_list": [
                                {
                                    "device_type": "Gate",
                                    "object_id": 501,
                                    "value": 0.8,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        class FakeHttpResponse:
            def read(self):
                return json.dumps(raw_response).encode("utf-8")

        def fake_opener(request, timeout_seconds):
            self.assertEqual(request.full_url, "http://mpc.local/hydros/api/v1/mpc/planning/start")
            self.assertIn(b'"bizSceneInstanceId": "scene-013-log"', request.data)
            self.assertNotIn(b'"biz_scene_instance_id"', request.data)
            self.assertNotIn(b'"targets"', request.data)
            self.assertEqual(timeout_seconds, 150.0)
            return FakeHttpResponse()

        client = MpcPlanningClient(
            base_url="http://mpc.local/hydros/api/v1/mpc/planning/start",
            opener=fake_opener,
            require_sensor_data=True,
        )

        with self.assertLogs("hydros_agent_sdk.mpc.client", level="INFO") as logs:
            responses = client.execute_optimization(
                state,
                [SensorData(object_id=9001, metrics_code="water_level", value=12.5, step_index=2)],
            )

        log_output = "\n".join(logs.output)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].plan_type, "OPTIMAL")
        self.assertIn("MPC optimization request payload", log_output)
        self.assertIn('"bizSceneInstanceId": "scene-013-log"', log_output)
        self.assertNotIn('"biz_scene_instance_id"', log_output)
        self.assertNotIn('"targets"', log_output)
        self.assertIn('"objectId": 9001', log_output)
        self.assertIn("MPC optimization raw response", log_output)
        self.assertIn('"success": true', log_output)
        self.assertIn("MPC optimization parsed response", log_output)
        self.assertIn('"plan_type": "OPTIMAL"', log_output)

    def assert_no_snake_case_keys(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                self.assertNotIn("_", key)
                self.assert_no_snake_case_keys(child)
            return
        if isinstance(value, list):
            for child in value:
                self.assert_no_snake_case_keys(child)

    def test_mpc_planning_client_uses_configured_full_planning_start_url(self):
        client = MpcPlanningClient(base_url="http://mpc.local/hydros/api/v1/mpc/planning/start")

        self.assertEqual(
            client.planning_start_url,
            "http://mpc.local/hydros/api/v1/mpc/planning/start",
        )

    def test_mpc_planning_client_logs_empty_sensor_data_before_request(self):
        context = SimulationContext(biz_scene_instance_id="scene-013-empty-sensor")
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=2,
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )
        opener = Mock()
        client = MpcPlanningClient(
            base_url="http://mpc.local/hydros/api/v1/mpc/planning/start",
            opener=opener,
            require_sensor_data=True,
            empty_sensor_retry_delay_seconds=0,
            empty_sensor_retry_count=1,
        )

        with self.assertLogs("hydros_agent_sdk.mpc.client", level="INFO") as logs:
            with self.assertRaises(MpcPlanningError):
                client.execute_optimization(state, [], sensor_provider=lambda: [])

        log_output = "\n".join(logs.output)
        self.assertIn("MPC optimization sensorData before request build", log_output)
        self.assertIn("sensorDataCount=0", log_output)
        self.assertIn("MPC sensorData is empty before retry", log_output)
        self.assertIn("MPC sensorData after retry", log_output)
        self.assertIn("MPC sensorData is empty; request will not be sent", log_output)
        opener.assert_not_called()

    def test_mpc_result_reporter_builds_result_report_payload(self):
        context = SimulationContext(
            biz_scene_instance_id="scene-014",
            tenant=Tenant(tenant_id="tenant-014", tenant_name="Tenant"),
            biz_scenario=BizScenario(
                biz_scenario_id="scenario-014",
                biz_scenario_name="Scenario",
            ),
            waterway=Waterway(waterway_id="waterway-014", waterway_name="Waterway"),
        )
        source = build_agent_instance("agent-014", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=4,
        )
        response = MpcOptimizeResponse(
            plan_type="OPTIMAL",
            loss=0.12,
            gate_operations=1,
            gate_amplitude=0.4,
            horizon_controls=[
                HorizonControlStep(
                    horizon_step=1,
                    opening_list=[
                        DeviceOpening(
                            device_type="Gate",
                            node_id=101,
                            object_id=501,
                            value=0.45,
                        )
                    ],
                    target_node_list=[
                        TargetNode(
                            device_type="Canal",
                            node_id=102,
                            water_level=2.1,
                            target_water_level=2.3,
                            out_water_level=1.9,
                            total_flow=33.0,
                        )
                    ],
                )
            ],
        )

        report = MpcResultReporter().build_report(source, state, [response])
        payload = report.model_dump(by_alias=True)

        self.assertIsInstance(report, MpcResultReport)
        self.assertEqual(report.command_type, "mpc_result_report")
        self.assertTrue(report.broadcast)
        self.assertEqual(payload["source_agent_instance"]["agent_id"], "agent-014")
        self.assertEqual(payload["mpc_results"][0]["biz_scene_instance_id"], "scene-014")
        self.assertEqual(payload["mpc_results"][0]["waterway_id"], "waterway-014")
        self.assertEqual(payload["mpc_results"][0]["tenant_id"], "tenant-014")
        self.assertEqual(payload["mpc_results"][0]["biz_scenario_id"], "scenario-014")
        self.assertEqual(payload["mpc_results"][0]["details"][0]["command_type"], "OPENING")
        self.assertEqual(payload["mpc_results"][0]["details"][1]["command_type"], "WATER_LEVEL")
        self.assertEqual(payload["mpc_results"][0]["details"][1]["target_value"], 2.3)

    def test_central_scheduling_agent_default_mpc_path_reports_and_sends_opening(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        callback = TestSiblingCacheCallback()

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            sim_coordination_callback=callback,
        )

        context = SimulationContext(biz_scene_instance_id="scene-015")
        target = build_agent_instance("gate-agent-015", "GATE_AGENT_015", "node-b", context)
        callback._store_sibling_agent_instance(target)
        mpc_response = MpcOptimizeResponse(
            plan_type="OPTIMAL",
            horizon_controls=[
                HorizonControlStep(
                    horizon_step=1,
                    opening_list=[
                        DeviceOpening(
                            device_type="Gate",
                            object_id=501,
                            object_name="Gate 501",
                            value=0.45,
                        )
                    ],
                )
            ],
        )
        mpc_client = FakeMpcPlanningClient([mpc_response])
        reporter = FakeMpcResultReporter()
        agent = ProductionCentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-015",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            optimization_horizon=3,
            total_steps=20,
            mpc_planning_client=mpc_client,
            mpc_result_reporter=reporter,
            object_agent_code_map={501: "GATE_AGENT_015"},
        )
        agent._on_field_metrics_received(
            "metrics/topic",
            {
                "object_id": 9001,
                "object_type": "Sensor",
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 1,
                "position_code": "none",
            },
        )
        sent_commands = []

        with patch.object(agent, "send_command", side_effect=sent_commands.append):
            agent.on_time_series_data_update(
                build_time_series_update_request(context, command_id="ts-update-015", auto_schedule_at_step=1)
            )

        self.assertEqual(len(mpc_client.calls), 1)
        self.assertEqual(mpc_client.calls[0]["state"].current_step, 1)
        self.assertEqual(mpc_client.calls[0]["sensor_data"][0].object_id, 9001)
        self.assertEqual(len(reporter.published), 1)
        self.assertEqual(reporter.published[0]["source"], agent)
        self.assertEqual(len(sent_commands), 1)
        self.assertIsInstance(sent_commands[0], HydroDirectGateOpeningRequest)
        self.assertEqual(sent_commands[0].target.agent_code, "GATE_AGENT_015")
        self.assertEqual(sent_commands[0].object_id, 501)
        self.assertEqual(sent_commands[0].gate_opening, 0.45)

    def test_coordination_client_sends_local_mpc_result_report(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        context = SimulationContext(biz_scene_instance_id="scene-016")
        source = build_agent_instance("agent-016", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        client = SimCoordinationClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
            sim_coordination_callback=TestSiblingCacheCallback(),
            state_manager=state_manager,
        )
        report = MpcResultReport(
            command_id="report-016",
            context=context,
            source_agent_instance=source,
            mpc_results=[],
            broadcast=True,
        )

        self.assertTrue(client._should_send(report))

    def test_central_scheduling_agent_generates_java_style_command_id(self):
        with patch("hydros_agent_sdk.utils.id_generator.datetime") as mock_datetime, \
             patch("hydros_agent_sdk.utils.id_generator.choice", return_value="A"):
            mock_now = Mock()
            mock_now.strftime.return_value = "202601011230"
            mock_datetime.now.return_value = mock_now

            command_id = generate_agent_command_id()

        self.assertEqual(command_id, "AGTCMD202601011230AAAAAAAAAAAA")
        self.assertTrue(command_id.startswith("AGTCMD"))
        self.assertEqual(len(command_id), 30)

    def test_sibling_agent_cache_is_available_to_central_scheduling_agent(self):
        callback = TestSiblingCacheCallback()

        context = SimulationContext(biz_scene_instance_id="scene-005")
        sibling = build_agent_instance("agent-005", "SOURCE_AGENT", "node-a", context)
        response = SimTaskInitResponse(
            command_id="init-005",
            context=context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=sibling,
            created_agent_instances=[sibling],
            managed_top_objects={},
        )

        callback.on_agent_instance_sibling_created(response)
        self.assertIsNone(callback.get_sibling_agent_instance("agent-005"))
        self.assertIs(callback.get_sibling_agent_instance("SOURCE_AGENT"), sibling)
        self.assertIsNone(callback.get_sibling_agent_instance("agent-005", biz_scene_instance_id="other-scene"))

        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            sim_coordination_callback=callback,
        )

        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-006",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        self.assertIs(agent.get_sibling_agent_instance("SOURCE_AGENT"), sibling)

        terminate_request = SimTaskTerminateRequest(command_id="term-005", context=context)
        callback.on_task_terminate(terminate_request)
        self.assertIsNone(callback.get_sibling_agent_instance("agent-005"))


if __name__ == "__main__":
    unittest.main()
