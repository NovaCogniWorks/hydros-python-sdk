import unittest

from hydros_agent_sdk.transport import MqttMetricsPublisher
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics


class PublishResult:
    rc = 0


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return PublishResult()


class FakeCoordinationClient:
    def __init__(self):
        self.topic = "/hydros/commands/coordination/test"
        self.mqtt_client = FakeMqttClient()
        self.state_manager = None


class MqttMetricsPublisherTest(unittest.TestCase):
    def test_builds_metrics_topic_when_context_is_available(self):
        publisher = MqttMetricsPublisher.from_coordination_client(
            FakeCoordinationClient(),
            biz_scene_instance_id="task-a",
            cluster_id="cluster-a",
        )

        self.assertEqual(
            publisher.topic,
            "/hydros/data/edges/cluster-a/task-a",
        )

    def test_falls_back_to_coordination_metrics_topic_without_context(self):
        publisher = MqttMetricsPublisher.from_coordination_client(FakeCoordinationClient())

        self.assertEqual(publisher.topic, "/hydros/commands/coordination/test/metrics")

    def test_publish_batch_delegates_to_mqtt_client(self):
        client = FakeCoordinationClient()
        publisher = MqttMetricsPublisher.from_coordination_client(
            client,
            biz_scene_instance_id="task-a",
            cluster_id="cluster-a",
            edge_node_code="node-a",
        )
        metrics = MqttMetrics(
            source_id="agent-a",
            object_id=1,
            object_name="obj-a",
            step_index=2,
            source_timestamp_ms=123,
            metrics_code="water_level",
            value=73.2,
        )

        published_count = publisher.publish_batch([metrics])

        self.assertEqual(published_count, 1)
        self.assertEqual(len(client.mqtt_client.published), 1)
        topic, payload, qos = client.mqtt_client.published[0]
        self.assertEqual(topic, "/hydros/data/edges/cluster-a/task-a")
        self.assertEqual(qos, 0)
        self.assertIn('"biz_scene_instance_id":"task-a"', payload)
        self.assertIn('"job_instance_id":"task-a"', payload)
        self.assertIn('"edge_node_code":"node-a"', payload)
        self.assertIn('"metrics_code":"water_level"', payload)
        self.assertNotIn('"attributes":null', payload)

    def test_publish_batch_rejects_mismatched_context_ids(self):
        client = FakeCoordinationClient()
        publisher = MqttMetricsPublisher.from_coordination_client(
            client,
            biz_scene_instance_id="task-a",
            cluster_id="cluster-a",
        )
        metrics = MqttMetrics(
            source_id="agent-a",
            biz_scene_instance_id="task-b",
            object_id=1,
            object_name="obj-a",
            step_index=2,
            source_timestamp_ms=123,
            metrics_code="water_level",
            value=73.2,
        )

        with self.assertRaises(ValueError):
            publisher.publish_batch([metrics])

    def test_publish_batch_rejects_mismatched_payload_instance_ids(self):
        client = FakeCoordinationClient()
        publisher = MqttMetricsPublisher.from_coordination_client(client)
        metrics = MqttMetrics(
            source_id="agent-a",
            biz_scene_instance_id="task-a",
            job_instance_id="task-b",
            object_id=1,
            object_name="obj-a",
            step_index=2,
            source_timestamp_ms=123,
            metrics_code="water_level",
            value=73.2,
        )

        with self.assertRaises(ValueError):
            publisher.publish_batch([metrics])


if __name__ == "__main__":
    unittest.main()
