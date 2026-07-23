"""MQTT metrics 发布服务。"""

from __future__ import annotations

from typing import List, Optional

from hydros_agent_sdk.runtime.env_settings import DEFAULT_METRICS_TOPIC, load_runtime_env_settings
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, send_metrics_batch


class MqttMetricsPublisher:
    """封装指标上报的 MQTT topic 和 publish 细节。"""

    def __init__(
        self,
        transport,
        topic: str,
        qos: int = 0,
        biz_scene_instance_id: Optional[str] = None,
        edge_node_code: Optional[str] = None,
    ):
        if transport is None:
            raise ValueError("transport is required")
        if not topic:
            raise ValueError("topic is required")
        self.transport = transport
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
            transport=coordination_client.transport,
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
            transport=self.transport,
            topic=self.topic,
            metrics_list=normalized_metrics,
            qos=self.qos,
        )

    def _with_context(self, metrics: MqttMetrics) -> MqttMetrics:
        metric_context_id = metrics.biz_scene_instance_id or metrics.job_instance_id
        if metrics.biz_scene_instance_id and metrics.job_instance_id:
            if metrics.biz_scene_instance_id != metrics.job_instance_id:
                raise ValueError(
                    "metrics biz_scene_instance_id and job_instance_id must match: "
                    f"{metrics.biz_scene_instance_id} != {metrics.job_instance_id}"
                )
        if self.biz_scene_instance_id and metric_context_id:
            if metric_context_id != self.biz_scene_instance_id:
                raise ValueError(
                    "metrics context does not match publisher context: "
                    f"{metric_context_id} != {self.biz_scene_instance_id}"
                )

        context_id = metric_context_id or self.biz_scene_instance_id
        updates = {}
        if context_id:
            if metrics.biz_scene_instance_id != context_id:
                updates["biz_scene_instance_id"] = context_id
            if metrics.job_instance_id != context_id:
                updates["job_instance_id"] = context_id
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
