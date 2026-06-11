"""MQTT metrics 发布服务。"""

from __future__ import annotations

from typing import List, Optional

from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, send_metrics_batch


class MqttMetricsPublisher:
    """封装指标上报的 MQTT topic 和 publish 细节。"""

    def __init__(self, mqtt_client, topic: str, qos: int = 0):
        if mqtt_client is None:
            raise ValueError("mqtt_client is required")
        if not topic:
            raise ValueError("topic is required")
        self.mqtt_client = mqtt_client
        self.topic = topic
        self.qos = qos

    @classmethod
    def from_coordination_client(
        cls,
        coordination_client,
        metrics_topic: Optional[str] = None,
        qos: int = 0,
    ) -> "MqttMetricsPublisher":
        topic = metrics_topic or cls.default_metrics_topic(coordination_client.topic)
        return cls(
            mqtt_client=coordination_client.mqtt_client,
            topic=topic,
            qos=qos,
        )

    @staticmethod
    def default_metrics_topic(coordination_topic: str) -> str:
        return f"{coordination_topic}/metrics"

    def publish_batch(self, metrics_list: List[MqttMetrics]) -> int:
        return send_metrics_batch(
            mqtt_client=self.mqtt_client,
            topic=self.topic,
            metrics_list=metrics_list,
            qos=self.qos,
        )
