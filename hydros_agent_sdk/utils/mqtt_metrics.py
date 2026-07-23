"""
用于发送指标数据的 MQTT Metrics 工具。

本模块提供通过 MQTT 发送指标数据的工具，并与 Java 实现
com.hydros.edge.agent.channel.etl.model.MqttMetrics 保持匹配。
"""

import time
import logging
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class MqttMetrics(BaseModel):
    """
    匹配 Java MqttMetrics 类的 MQTT Metrics 模型。

    该模型表示水网对象通过 MQTT 发送的指标数据。
    """
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "source_id": "TWINS_SIMULATION_AGENT",
                "biz_scene_instance_id": "task_123",
                "job_instance_id": "task_123",
                "edge_node_code": "edge-a",
                "object_id": 1001,
                "object_type": "Gate",
                "object_name": "Gate_01",
                "step_index": 10,
                "source_timestamp_ms": 1706601234567,
                "metrics_code": "gate_opening",
                "position_code": "none",
                "value": 0.75,
                "status": "ON",
            }
        },
    )

    source_id: Optional[str] = Field(default=None, description="Source identifier (e.g., agent code)")
    biz_scene_instance_id: Optional[str] = Field(default=None, description="Canonical Hydros scene instance ID")
    job_instance_id: Optional[str] = Field(default=None, description="Legacy job instance ID; mirrors biz_scene_instance_id")
    edge_node_code: Optional[str] = Field(default=None, description="Edge node code")
    object_id: int = Field(..., description="Water network object ID")
    object_type: Optional[str] = Field(default=None, description="Water network object type")
    object_name: Optional[str] = Field(default=None, description="Water network object name")
    step_index: Optional[int] = Field(default=None, description="Simulation step index")
    source_timestamp_ms: int = Field(default_factory=lambda: int(time.time() * 1000),
                                     description="Source timestamp in milliseconds")
    metrics_code: Optional[str] = Field(default=None, description="Metrics code (e.g., water_level, water_flow)")
    position_code: str = Field(default="none", description="Metrics position code")
    value: Optional[float] = Field(default=None, description="Metrics value")
    status: Optional[str] = Field(default=None, description="Device power status: ON or OFF")
    attributes: Optional[str] = Field(default=None, description="Extended metrics attributes JSON")
    front_water_flow: Optional[float] = Field(default=None, description="Upstream/front water flow")
    back_water_flow: Optional[float] = Field(default=None, description="Downstream/back water flow")
    front_water_level: Optional[float] = Field(default=None, description="Upstream/front water level")
    back_water_level: Optional[float] = Field(default=None, description="Downstream/back water level")

    @model_validator(mode="after")
    def sync_instance_ids(self) -> "MqttMetrics":
        """保持场景实例 ID 一致，供 Java edge 和 central 消费。"""
        if not self.biz_scene_instance_id and self.job_instance_id:
            self.biz_scene_instance_id = self.job_instance_id
        if not self.job_instance_id and self.biz_scene_instance_id:
            self.job_instance_id = self.biz_scene_instance_id
        return self


def send_metrics(
    transport,
    topic: str,
    metrics: MqttMetrics,
    qos: int = 0
) -> bool:
    """
    通过 MQTT 发送单条指标消息。

    Args:
        transport: 提供 publish(topic, payload, qos=...) 方法的传输对象
        topic: 要发布到的 MQTT topic
        metrics: 要发送的 MqttMetrics 对象
        qos: 服务质量等级（0、1 或 2）

    Returns:
        发送成功返回 True，否则返回 False
    """
    try:
        # 序列化为 JSON
        payload = metrics.model_dump_json(exclude_none=True)

        transport.publish(topic, payload, qos=qos)
        logger.debug(f"Sent metrics: {metrics.metrics_code}={metrics.value} "
                    f"for object {metrics.object_name} (step {metrics.step_index})")
        return True

    except Exception as e:
        logger.error(f"Error sending metrics: {e}", exc_info=True)
        return False


def send_metrics_batch(
    transport,
    topic: str,
    metrics_list: List[MqttMetrics],
    qos: int = 0
) -> int:
    """
    通过 MQTT 批量发送指标消息。

    Args:
        transport: 提供 publish 的传输对象
        topic: 要发布到的 MQTT topic
        metrics_list: 要发送的 MqttMetrics 对象列表
        qos: 服务质量等级（0、1 或 2）

    Returns:
        成功发送的消息数量
    """
    success_count = 0

    for metrics in metrics_list:
        if send_metrics(transport, topic, metrics, qos):
            success_count += 1

    logger.info(f"Sent {success_count}/{len(metrics_list)} metrics messages")
    return success_count


def create_mock_metrics(
    source_id: str,
    job_instance_id: Optional[str],
    object_id: int,
    object_name: str,
    step_index: int,
    metrics_code: str,
    value: float,
    timestamp_ms: Optional[int] = None,
    biz_scene_instance_id: Optional[str] = None,
    object_type: Optional[str] = None,
    edge_node_code: Optional[str] = None,
    position_code: str = "none",
    status: Optional[str] = None,
    attributes: Optional[str] = None,
) -> MqttMetrics:
    """
    创建用于测试的模拟指标对象。

    Args:
        source_id: 来源标识（例如 agent code）
        job_instance_id: 作业实例 ID（兼容字段，通常等于 biz_scene_instance_id）
        object_id: 水网对象 ID
        object_name: 水网对象名称
        step_index: 仿真步索引
        metrics_code: 指标编码（例如 water_level、flow_rate）
        value: 指标值
        timestamp_ms: 可选毫秒时间戳（默认使用当前时间）

    Returns:
        MqttMetrics 对象
    """
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    return MqttMetrics(
        source_id=source_id,
        biz_scene_instance_id=biz_scene_instance_id or job_instance_id,
        job_instance_id=job_instance_id,
        edge_node_code=edge_node_code,
        object_id=object_id,
        object_type=object_type,
        object_name=object_name,
        step_index=step_index,
        source_timestamp_ms=timestamp_ms,
        metrics_code=metrics_code,
        position_code=position_code,
        value=value,
        status=status,
        attributes=attributes,
    )
