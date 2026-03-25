import unittest

from paho.mqtt.reasoncodes import ReasonCode

from hydros_agent_sdk import AgentCommandClient, HydrosTopics, SimCoordinationCallback, SimCoordinationClient


class DummyCoordinationCallback(SimCoordinationCallback):
    def get_component(self) -> str:
        return "DUMMY_COMPONENT"

    def on_sim_task_init(self, request):
        return None

    def on_tick(self, request):
        return None


class HydrosTopicsTest(unittest.TestCase):
    def test_coordination_client_on_connect_accepts_reason_code_object(self):
        client = SimCoordinationClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo_cluster",
            sim_coordination_callback=DummyCoordinationCallback(),
        )

        subscriptions = []
        client.mqtt_client.subscribe = lambda topic, qos=0: subscriptions.append((topic, qos))

        client._on_connect(
            None,
            None,
            None,
            ReasonCode(packetType=2, aName="Success"),
        )

        self.assertTrue(client.connected.is_set())
        self.assertEqual(subscriptions, [("/hydros/commands/coordination/demo_cluster", 1)])

    def test_agent_command_client_on_connect_accepts_reason_code_object(self):
        client = AgentCommandClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo_cluster",
        )

        subscriptions = []
        client.mqtt_client.subscribe = lambda topic, qos=0: subscriptions.append((topic, qos))

        client._on_connect(
            None,
            None,
            None,
            ReasonCode(packetType=2, aName="Success"),
        )

        self.assertTrue(client._connected.is_set())
        self.assertEqual(subscriptions, [("/hydros/commands/agent/demo_cluster", 1)])

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
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo_cluster",
        )
        self.assertEqual(client.topic, "/hydros/commands/agent/demo_cluster")

    def test_agent_command_client_requires_topic_or_cluster_id(self):
        with self.assertRaises(ValueError):
            AgentCommandClient(
                broker_url="tcp://127.0.0.1",
                broker_port=1883,
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


if __name__ == "__main__":
    unittest.main()
