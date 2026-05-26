import json
import unittest
from types import SimpleNamespace

from hydros_agent_sdk.mpc.metrics_data_cache import MetricsDataCache
from hydros_agent_sdk.transport.mqtt_metrics_subscriber import MqttMetricsSubscriber


class FakeMqttClient:
    def __init__(self):
        self.callbacks = {}
        self.subscriptions = []

    def message_callback_add(self, topic, callback):
        self.callbacks[topic] = callback

    def subscribe(self, topic):
        self.subscriptions.append(topic)


class MqttMetricsSubscriberTest(unittest.TestCase):
    def test_subscribes_and_caches_parsed_metrics_payload(self):
        mqtt_client = FakeMqttClient()
        cache = MetricsDataCache(max_steps=3)
        subscriber = MqttMetricsSubscriber(mqtt_client, cache)

        subscriber.subscribe("/metrics/topic")
        msg = SimpleNamespace(
            topic="/metrics/topic",
            payload=json.dumps(
                {
                    "object_id": 1001,
                    "metrics_code": "flow",
                    "value": 2.5,
                    "step_index": 4,
                    "position_code": "none",
                }
            ).encode("utf-8"),
        )
        mqtt_client.callbacks["/metrics/topic"](None, None, msg)

        self.assertEqual(mqtt_client.subscriptions, ["/metrics/topic"])
        self.assertEqual(cache.get_value(1001, "flow"), 2.5)
        self.assertEqual(cache.by_step(4)["1001_flow"]["position_code"], "none")

    def test_invalid_json_is_ignored(self):
        cache = MetricsDataCache(max_steps=3)
        subscriber = MqttMetricsSubscriber(FakeMqttClient(), cache)
        msg = SimpleNamespace(topic="/metrics/topic", payload=b"{not-json")

        with self.assertLogs("hydros_agent_sdk.transport.mqtt_metrics_subscriber", level="ERROR"):
            self.assertIsNone(subscriber.handle_message(msg))
        self.assertEqual(cache.history(), {})


if __name__ == "__main__":
    unittest.main()
