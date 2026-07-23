"""现地指标的 MQTT 订阅辅助对象。"""

import json
import logging
from typing import Any, Dict, Optional

from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache

logger = logging.getLogger(__name__)


class MqttMetricsSubscriber:
    """订阅 MQTT 现地指标 topic，并把解析后的 payload 写入缓存。"""

    def __init__(self, transport: Any, metrics_data_cache: FieldMetricsCache):
        self.transport = transport
        self.metrics_data_cache = metrics_data_cache
        self.subscription_topic: Optional[str] = None

    def subscribe(self, metrics_topic: str) -> None:
        self.subscription_topic = metrics_topic
        self.transport.subscribe(metrics_topic, self._handle_transport_payload)

    def _handle_transport_payload(self, topic: str, payload_str: str) -> None:
        try:
            payload = json.loads(payload_str)
            self.handle_payload(topic, payload)
        except Exception as exc:
            logger.error("Error parsing field metrics payload on %s: %s", topic, exc)

    def handle_message(self, msg) -> Optional[str]:
        """处理 Paho 风格的消息，供单元测试直接调用。"""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            return self.handle_payload(msg.topic, payload)
        except Exception as exc:
            logger.error("Error parsing field metrics payload on %s: %s", msg.topic, exc)
            return None

    def handle_payload(self, topic: str, payload: Dict[str, Any]) -> Optional[str]:
        try:
            return self.metrics_data_cache.update(payload)
        except Exception as exc:
            logger.error("Error processing field metrics: %s", exc, exc_info=True)
            return None
