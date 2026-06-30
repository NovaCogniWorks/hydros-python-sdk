"""现地指标的 MQTT 订阅辅助对象。"""

import json
import logging
from typing import Any, Dict, Optional

from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache

logger = logging.getLogger(__name__)


class MqttMetricsSubscriber:
    """订阅 MQTT 现地指标 topic，并把解析后的 payload 写入缓存。"""

    def __init__(self, mqtt_client: Any, metrics_data_cache: FieldMetricsCache):
        self.mqtt_client = mqtt_client
        self.metrics_data_cache = metrics_data_cache
        self.subscription_topic: Optional[str] = None

    def subscribe(self, metrics_topic: str) -> None:
        self.subscription_topic = metrics_topic
        self.mqtt_client.message_callback_add(metrics_topic, self._on_message)
        self.mqtt_client.subscribe(metrics_topic)

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
        try:
            logger.info(
                "HYDROS_DIAG_FIELD_METRICS_CACHE_MISMATCH payload received: "
                "topic=%s object_id=%s object_type=%s "
                "metrics_code=%s position_code=%s has_attributes=%s "
                "top_front_water_flow=%s top_back_water_flow=%s keys=%s",
                topic,
                payload.get("object_id"),
                payload.get("object_type"),
                payload.get("metrics_code"),
                payload.get("position_code"),
                "attributes" in payload,
                payload.get("front_water_flow"),
                payload.get("back_water_flow"),
                sorted(payload.keys()),
            )
            return self.metrics_data_cache.update(payload)
        except Exception as exc:
            logger.error("Error processing field metrics: %s", exc, exc_info=True)
            return None
