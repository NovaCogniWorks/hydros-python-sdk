"""MQTT subscription helper for field metrics."""

import json
import logging
from typing import Any, Dict, Optional

from hydros_agent_sdk.mpc.metrics_data_cache import MetricsDataCache

logger = logging.getLogger(__name__)


class MqttMetricsSubscriber:
    """Subscribe to MQTT field metrics topics and feed parsed payloads into a cache."""

    def __init__(self, mqtt_client: Any, metrics_data_cache: MetricsDataCache):
        self.mqtt_client = mqtt_client
        self.metrics_data_cache = metrics_data_cache
        self.subscription_topic: Optional[str] = None

    def subscribe(self, metrics_topic: str) -> None:
        logger.info("Subscribing to field metrics topic: %s", metrics_topic)
        self.subscription_topic = metrics_topic
        self.mqtt_client.message_callback_add(metrics_topic, self._on_message)
        self.mqtt_client.subscribe(metrics_topic)
        logger.info("Subscribed to field metrics: %s", metrics_topic)

    def _on_message(self, client, userdata, msg) -> None:
        self.handle_message(msg)

    def handle_message(self, msg) -> Optional[str]:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            return self.handle_payload(msg.topic, payload)
        except Exception as exc:
            logger.error("Error parsing field metrics payload on %s: %s", msg.topic, exc)
            return None

    def handle_payload(self, topic: str, payload: Dict[str, Any]) -> Optional[str]:
        logger.debug("Received field metrics from topic: %s", topic)
        try:
            cache_key = self.metrics_data_cache.update(payload)
            if cache_key:
                logger.debug("Cached field metrics: %s = %s", cache_key, payload.get("value"))
            return cache_key
        except Exception as exc:
            logger.error("Error processing field metrics: %s", exc, exc_info=True)
            return None
