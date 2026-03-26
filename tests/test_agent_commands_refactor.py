import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hydros_agent_sdk import HydroObjectType, generate_agent_command_id
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
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    AgentBizStatus,
    AgentDriveMode,
    BizScenario,
    HydroAgent,
    CommandStatus,
    HydroAgentInstance,
    SimulationContext,
)
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
        agent_biz_status=AgentBizStatus.INIT,
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


class TestCentralSchedulingAgent(CentralSchedulingAgent):
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
        return None

    def on_terminate(self, request: SimTaskTerminateRequest):
        self._shutdown_agent_command_client()
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )


class TestSiblingCacheCallback(SimCoordinationCallback):
    def get_component(self) -> str:
        return "TEST_CALLBACK"

    def on_sim_task_init(self, request: SimTaskInitRequest):
        return None

    def on_tick(self, request):
        return None

    def is_remote_agent(self, agent_instance) -> bool:
        return True


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
        )

        context = SimulationContext(biz_scene_instance_id="scene-004")
        agent = TestCentralSchedulingAgent(
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
        agent = TestCentralSchedulingAgent(
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
                step=12,
                target_agent_code="PUMP_AGENT_001",
                target_command_type=DeviceValueTypeEnum.GATE_OPENING.code,
                target_value=1.25,
                object_id=1023,
                object_type=HydroObjectType.PUMP,
            )

        self.assertIsNotNone(request)
        self.assertEqual(request.target.agent_code, "PUMP_AGENT_001")
        self.assertEqual(request.target_value_type, DeviceValueTypeEnum.GATE_OPENING.code)
        self.assertEqual(request.target_value, 1.25)

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

        agent = TestCentralSchedulingAgent(
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
