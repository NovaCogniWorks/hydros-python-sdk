import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from hydros_agent_sdk.agent_commands import (
    AgentCommandClient,
    AgentCommandEnvelope,
    AgentCommandHandler,
    AgentCommandRuntime,
    HydroDirectGateOpeningRequest,
    HydroDirectGateOpeningResponse,
)
from hydros_agent_sdk.agent_commands.runtime.testing import wait_command_completed
from hydros_agent_sdk.protocol.models import (
    AgentBizStatus,
    AgentDriveMode,
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
        self.assertFalse(os.path.exists(os.path.join("data", "agent_command.db")))

        runtime = client.runtime

        self.assertIsNotNone(runtime)
        self.assertIsNotNone(client._runtime)
        self.assertTrue(os.path.exists(os.path.join("data", "agent_command.db")))

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
        self.assertTrue(os.path.exists(os.path.join("data", "agent_command.db")))

        runtime.start()
        send_and_wait("cmd-003b", 0.24)
        runtime.stop()

        self.assertEqual(sent_commands, [])


if __name__ == "__main__":
    unittest.main()
