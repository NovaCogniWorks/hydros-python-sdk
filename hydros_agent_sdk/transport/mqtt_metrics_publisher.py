"""MQTT metrics 发布服务。"""

from __future__ import annotations

from typing import List, Optional

from hydros_agent_sdk.runtime.env_settings import DEFAULT_METRICS_TOPIC, load_runtime_env_settings
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, send_metrics_batch


class MqttMetricsPublisher:
    """封装指标上报的 MQTT topic 和 publish 细节。"""

    def __init__(
        self,
        mqtt_client,
        topic: str,
        qos: int = 0,
        biz_scene_instance_id: Optional[str] = None,
        edge_node_code: Optional[str] = None,
    ):
        if mqtt_client is None:
            raise ValueError("mqtt_client is required")
        if not topic:
            raise ValueError("topic is required")
        self.mqtt_client = mqtt_client
        self.topic = topic
        self.qos = qos
        self.biz_scene_instance_id = biz_scene_instance_id
        self.edge_node_code = edge_node_code

    @classmethod
    def from_coordination_client(
        cls,
        coordination_client,
        metrics_topic: Optional[str] = None,
        qos: int = 0,
        biz_scene_instance_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
        edge_node_code: Optional[str] = None,
    ) -> "MqttMetricsPublisher":
        resolved_cluster_id = cluster_id or cls._resolve_cluster_id(coordination_client)
        topic = metrics_topic or cls.default_metrics_topic(
            coordination_client.topic,
            biz_scene_instance_id=biz_scene_instance_id,
            cluster_id=resolved_cluster_id,
        )
        return cls(
            mqtt_client=coordination_client.mqtt_client,
            topic=topic,
            qos=qos,
            biz_scene_instance_id=biz_scene_instance_id,
            edge_node_code=edge_node_code,
        )

    @staticmethod
    def default_metrics_topic(
        coordination_topic: str,
        biz_scene_instance_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
    ) -> str:
        if biz_scene_instance_id:
            settings = load_runtime_env_settings()
            base_topic = settings.render_topic(
                settings.metrics_topic or DEFAULT_METRICS_TOPIC,
                cluster_id=cluster_id,
            )
            if base_topic:
                return f"{base_topic.rstrip('/')}/{biz_scene_instance_id}"
        return f"{coordination_topic}/metrics"

    def publish_batch(self, metrics_list: List[MqttMetrics]) -> int:
        normalized_metrics = [self._with_context(metrics) for metrics in metrics_list]
        return send_metrics_batch(
            mqtt_client=self.mqtt_client,
            topic=self.topic,
            metrics_list=normalized_metrics,
            qos=self.qos,
        )

    def _with_context(self, metrics: MqttMetrics) -> MqttMetrics:
        updates = {}
        if self.biz_scene_instance_id:
            if not metrics.biz_scene_instance_id:
                updates["biz_scene_instance_id"] = self.biz_scene_instance_id
            if not metrics.job_instance_id:
                updates["job_instance_id"] = self.biz_scene_instance_id
        if self.edge_node_code and not metrics.edge_node_code:
            updates["edge_node_code"] = self.edge_node_code
        if not updates:
            return metrics
        return metrics.model_copy(update=updates)

    @staticmethod
    def _resolve_cluster_id(coordination_client) -> Optional[str]:
        state_manager = getattr(coordination_client, "state_manager", None)
        if state_manager is not None and hasattr(state_manager, "get_cluster_id"):
            return state_manager.get_cluster_id()
        return None
