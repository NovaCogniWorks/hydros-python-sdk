"""
MQTT Metrics utility for sending metrics data.

This module provides utilities for sending metrics data via MQTT,
matching the Java implementation in com.hydros.agent.edge.channel.biz.model.MqttMetrics.
"""

import json
import time
import logging
from typing import Optional, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MqttMetrics(BaseModel):
    """
    MQTT Metrics model matching Java MqttMetrics class.

    This model represents metrics data sent via MQTT for water network objects.
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
        """Pydantic configuration."""
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
    Send a single metrics message via MQTT.

    Args:
        mqtt_client: MQTT client instance (paho.mqtt.client.Client or HydrosMqttClient)
        topic: MQTT topic to publish to
        metrics: MqttMetrics object to send
        qos: Quality of Service level (0, 1, or 2)

    Returns:
        True if message was sent successfully, False otherwise
    """
    try:
        # Serialize to JSON
        payload = metrics.model_dump_json()

        # Publish via MQTT
        result = mqtt_client.publish(topic, payload, qos=qos)

        # Check if publish was successful
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
    Send multiple metrics messages via MQTT.

    Args:
        mqtt_client: MQTT client instance
        topic: MQTT topic to publish to
        metrics_list: List of MqttMetrics objects to send
        qos: Quality of Service level (0, 1, or 2)

    Returns:
        Number of messages sent successfully
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
    Create a mock metrics object for testing.

    Args:
        source_id: Source identifier (e.g., agent code)
        job_instance_id: Job instance ID (e.g., biz_scene_instance_id)
        object_id: Water network object ID
        object_name: Water network object name
        step_index: Simulation step index
        metrics_code: Metrics code (e.g., water_level, flow_rate)
        value: Metrics value
        timestamp_ms: Optional timestamp in milliseconds (defaults to current time)

    Returns:
        MqttMetrics object
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
