import json
import unittest
from types import SimpleNamespace

from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache
from hydros_agent_sdk.transport.mqtt_metrics_subscriber import MqttMetricsSubscriber


class FakeTransport:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, topic, handler, qos=1):
        self.subscriptions.append((topic, handler, qos))


class MqttMetricsSubscriberTest(unittest.TestCase):
    def test_subscribes_and_caches_parsed_metrics_payload(self):
        transport = FakeTransport()
        cache = FieldMetricsCache(max_steps=3, biz_scene_instance_id="task-a")
        subscriber = MqttMetricsSubscriber(transport, cache)

        subscriber.subscribe("/metrics/topic")
        topic, handler, qos = transport.subscriptions[0]
        handler(
            topic,
            json.dumps(
                {
                    "object_id": 1001,
                    "metrics_code": "water_flow",
                    "value": 2.5,
                    "step_index": 4,
                    "position_code": "none",
                    "attributes": "{\"front_water_flow\":2.5}",
                }
            ),
        )

        self.assertEqual(qos, 1)
        self.assertEqual(cache.get_value(1001, "water_flow"), 2.5)
        cache_key = "task-a#1001#water_flow#none"
        self.assertEqual(cache.by_step(4)[cache_key]["position_code"], "none")
        self.assertEqual(cache.by_step(4)[cache_key]["attributes"], "{\"front_water_flow\":2.5}")

    def test_invalid_json_is_ignored(self):
        cache = FieldMetricsCache(max_steps=3)
        subscriber = MqttMetricsSubscriber(FakeTransport(), cache)
        msg = SimpleNamespace(topic="/metrics/topic", payload=b"{not-json")

        with self.assertLogs("hydros_agent_sdk.transport.mqtt_metrics_subscriber", level="ERROR"):
            self.assertIsNone(subscriber.handle_message(msg))
        self.assertEqual(cache.history(), {})


if __name__ == "__main__":
    unittest.main()
