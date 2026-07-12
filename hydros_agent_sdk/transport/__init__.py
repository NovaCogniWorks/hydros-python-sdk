"""
Hydros 协调消息的传输抽象。

现有 SimCoordinationClient 仍然负责生产 MQTT 路径。这些接口为测试和未来
传输方式提供一个小扩展点，同时暂不重组当前客户端。
"""

from hydros_agent_sdk.transport.base import MessageHandler, PublishRecord, Transport
from hydros_agent_sdk.transport.in_memory import InMemoryTransport
from hydros_agent_sdk.transport.mqtt_coordination import MqttCoordinationTransport
from hydros_agent_sdk.transport.mqtt_metrics_publisher import MqttMetricsPublisher
from hydros_agent_sdk.transport.mqtt_metrics_subscriber import MqttMetricsSubscriber

__all__ = [
    "MessageHandler",
    "PublishRecord",
    "Transport",
    "InMemoryTransport",
    "MqttCoordinationTransport",
    "MqttMetricsPublisher",
    "MqttMetricsSubscriber",
]
