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


class MqttMetricsPublisherTest(unittest.TestCase):
    def test_builds_default_topic_from_coordination_client(self):
        publisher = MqttMetricsPublisher.from_coordination_client(FakeCoordinationClient())

        self.assertEqual(
            publisher.topic,
            "/hydros/commands/coordination/test/metrics",
        )

    def test_publish_batch_delegates_to_mqtt_client(self):
        client = FakeCoordinationClient()
        publisher = MqttMetricsPublisher.from_coordination_client(client)
        metrics = MqttMetrics(
            source_id="agent-a",
            job_instance_id="task-a",
            object_id=1,
            object_name="obj-a",
            step_index=2,
            source_timestamp_ms=123,
            metrics_code="WATER_LEVEL",
            value=73.2,
        )

        published_count = publisher.publish_batch([metrics])

        self.assertEqual(published_count, 1)
        self.assertEqual(len(client.mqtt_client.published), 1)
        topic, payload, qos = client.mqtt_client.published[0]
        self.assertEqual(topic, "/hydros/commands/coordination/test/metrics")
        self.assertEqual(qos, 0)
        self.assertIn('"metrics_code":"WATER_LEVEL"', payload)


if __name__ == "__main__":
    unittest.main()
