"""
用于发送指标数据的 MQTT Metrics 工具。

本模块提供通过 MQTT 发送指标数据的工具，并与 Java 实现
com.hydros.agent.edge.channel.biz.model.MqttMetrics 保持匹配。
"""

import time
import logging
from typing import Optional, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MqttMetrics(BaseModel):
    """
    匹配 Java MqttMetrics 类的 MQTT Metrics 模型。

    该模型表示水网对象通过 MQTT 发送的指标数据。
    """
    source_id: str = Field(..., description="Source identifier (e.g., agent code)")
    job_instance_id: str = Field(..., description="Job instance ID (e.g., biz_scene_instance_id)")
    object_id: int = Field(..., description="Water network object ID")
    object_name: str = Field(..., description="Water network object name")
    step_index: int = Field(..., description="Simulation step index")
    source_timestamp_ms: int = Field(..., description="Source timestamp in milliseconds")
    metrics_code: str = Field(..., description="Metrics code (e.g., water_level, flow_rate)")
    value: float = Field(..., description="Metrics value")

    class Config:
        """用于 Pydantic 的配置。"""
        json_schema_extra = {
            "example": {
                "source_id": "TWINS_SIMULATION_AGENT",
                "job_instance_id": "task_123",
                "object_id": 1001,
                "object_name": "Gate_01",
                "step_index": 10,
                "source_timestamp_ms": 1706601234567,
                "metrics_code": "gate_opening",
                "value": 0.75
            }
        }


def send_metrics(
    mqtt_client,
    topic: str,
    metrics: MqttMetrics,
    qos: int = 0
) -> bool:
    """
    通过 MQTT 发送单条指标消息。

    Args:
        mqtt_client: 提供 publish(topic, payload, qos=...) 方法的 MQTT 客户端实例
        topic: 要发布到的 MQTT topic
        metrics: 要发送的 MqttMetrics 对象
        qos: 服务质量等级（0、1 或 2）

    Returns:
        发送成功返回 True，否则返回 False
    """
    try:
        # 序列化为 JSON
        payload = metrics.model_dump_json()

        # 通过 MQTT 发布
        result = mqtt_client.publish(topic, payload, qos=qos)

        # 检查发布是否成功
        if hasattr(result, 'rc') and result.rc == 0:
            logger.debug(f"Sent metrics: {metrics.metrics_code}={metrics.value} "
                        f"for object {metrics.object_name} (step {metrics.step_index})")
            return True
        else:
            logger.warning(f"Failed to send metrics: {metrics.metrics_code}")
            return False

    except Exception as e:
        logger.error(f"Error sending metrics: {e}", exc_info=True)
        return False


def send_metrics_batch(
    mqtt_client,
    topic: str,
    metrics_list: List[MqttMetrics],
    qos: int = 0
) -> int:
    """
    通过 MQTT 批量发送指标消息。

    Args:
        mqtt_client: MQTT 客户端实例
        topic: 要发布到的 MQTT topic
        metrics_list: 要发送的 MqttMetrics 对象列表
        qos: 服务质量等级（0、1 或 2）

    Returns:
        成功发送的消息数量
    """
    success_count = 0

    for metrics in metrics_list:
        if send_metrics(mqtt_client, topic, metrics, qos):
            success_count += 1

    logger.info(f"Sent {success_count}/{len(metrics_list)} metrics messages")
    return success_count


def create_mock_metrics(
    source_id: str,
    job_instance_id: str,
    object_id: int,
    object_name: str,
    step_index: int,
    metrics_code: str,
    value: float,
    timestamp_ms: Optional[int] = None
) -> MqttMetrics:
    """
    创建用于测试的模拟指标对象。

    Args:
        source_id: 来源标识（例如 agent code）
        job_instance_id: 作业实例 ID（例如 biz_scene_instance_id）
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
        job_instance_id=job_instance_id,
        object_id=object_id,
        object_name=object_name,
        step_index=step_index,
        source_timestamp_ms=timestamp_ms,
        metrics_code=metrics_code,
        value=value
    )
