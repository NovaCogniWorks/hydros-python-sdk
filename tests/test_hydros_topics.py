import os
import socket
import tempfile
import unittest
from unittest.mock import Mock

from paho.mqtt.reasoncodes import ReasonCode

from hydros_agent_sdk import SimCoordinationCallback, SimCoordinationClient
from hydros_agent_sdk.agent_commands.transport.client import AgentCommandClient
from hydros_agent_sdk.topics import HydrosTopics
from hydros_agent_sdk.transport.mqtt_coordination import MqttCoordinationTransport


class DummyCoordinationCallback(SimCoordinationCallback):
    def get_component(self) -> str:
        return "DUMMY_COMPONENT"

    def on_sim_task_init(self, request):
        return None

    def on_tick(self, request):
        return None


class HydrosTopicsTest(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._temp_dir.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._temp_dir.cleanup()

    def test_coordination_transport_on_connect_accepts_reason_code_object(self):
        transport = MqttCoordinationTransport(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            client_id="test-client",
            topic="/hydros/commands/coordination/demo_cluster",
            handler=lambda _topic, _payload: None,
        )

        subscriptions = []
        transport.mqtt_client.subscribe = lambda topic, qos=0: subscriptions.append((topic, qos))

        transport._on_connect(
            None,
            None,
            None,
            ReasonCode(packetType=2, aName="Success"),
        )

        self.assertTrue(transport.connected.is_set())
        self.assertEqual(subscriptions, [("/hydros/commands/coordination/demo_cluster", 1)])

    def test_agent_command_client_subscribes_through_shared_transport(self):
        transport = Mock()
        client = AgentCommandClient(
            transport=transport,
            hydros_cluster_id="demo_cluster",
        )

        transport.subscribe.assert_called_once_with(
            "/hydros/commands/agent/demo_cluster",
            client._handle_transport_payload,
            qos=1,
        )

    def test_topic_builders_match_java_rules(self):
        self.assertEqual(
            HydrosTopics.get_coordination_command_topic("demo_cluster"),
            "/hydros/commands/coordination/demo_cluster",
        )
        self.assertEqual(
            HydrosTopics.get_agent_command_topic("demo_cluster"),
            "/hydros/commands/agent/demo_cluster",
        )
        self.assertEqual(
            HydrosTopics.get_system_command_topic("demo_cluster"),
            "/hydros/commands/system/demo_cluster",
        )
        self.assertEqual(
            HydrosTopics.get_hydro_data_topic("demo_cluster"),
            "/hydros/data/edges/demo_cluster",
        )
        self.assertEqual(
            HydrosTopics.get_hydro_data_generic_topic("demo_cluster"),
            "/hydros/data/edges/demo_cluster/+",
        )

    def test_topic_builder_normalizes_cluster_id(self):
        self.assertEqual(
            HydrosTopics.get_agent_command_topic(" /demo_cluster/ "),
            "/hydros/commands/agent/demo_cluster",
        )

    def test_topic_builder_rejects_blank_cluster_id(self):
        with self.assertRaises(ValueError):
            HydrosTopics.get_agent_command_topic("   ")

    def test_agent_command_client_can_build_topic_from_cluster_id(self):
        client = AgentCommandClient(
            transport=Mock(),
            hydros_cluster_id="demo_cluster",
        )
        self.assertEqual(client.topic, "/hydros/commands/agent/demo_cluster")

    def test_agent_command_client_requires_topic_or_cluster_id(self):
        with self.assertRaises(ValueError):
            AgentCommandClient(
                transport=Mock(),
            )

    def test_coordination_client_can_build_topic_from_cluster_id(self):
        client = SimCoordinationClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo_cluster",
            sim_coordination_callback=DummyCoordinationCallback(),
        )
        self.assertEqual(client.topic, "/hydros/commands/coordination/demo_cluster")

    def test_coordination_client_requires_topic_or_cluster_id(self):
        with self.assertRaises(ValueError):
            SimCoordinationClient(
                broker_url="tcp://127.0.0.1",
                broker_port=1883,
                sim_coordination_callback=DummyCoordinationCallback(),
            )

    def test_coordination_client_start_wraps_dns_failure(self):
        client = SimCoordinationClient(
            broker_url="tcp://hydros-mqtt-broker-internal.hydros.svc.cluster.local",
            broker_port=1883,
            hydros_cluster_id="demo_cluster",
            sim_coordination_callback=DummyCoordinationCallback(),
        )

        def fail_connect(*_args, **_kwargs):
            raise socket.gaierror(-2, "Name or service not known")

        client.transport.mqtt_client.connect = fail_connect

        with self.assertRaisesRegex(
            RuntimeError,
            "Failed to connect to MQTT broker "
            "hydros-mqtt-broker-internal.hydros.svc.cluster.local:1883",
        ) as context:
            client.start()

        self.assertIn("env.properties mqtt_broker_url/mqtt_broker_port", str(context.exception))
        self.assertIn("DNS resolution", str(context.exception))
        self.assertFalse(client.task_runtime.running.is_set())


if __name__ == "__main__":
    unittest.main()
