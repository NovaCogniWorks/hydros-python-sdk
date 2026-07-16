"""
基于回调架构的仿真协调客户端。

本模块提供一个封装通用 MQTT 逻辑的高层客户端，让开发者通过实现回调
专注于业务逻辑。

功能类似 Java 侧的 SimCoordinationSlave 类。
"""

import json
import logging
import time
from typing import Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.message_filter import MessageFilter
from hydros_agent_sdk.topics import HydrosTopics
from hydros_agent_sdk.protocol.commands import (
    SimCommand,
    SimCommandEnvelope,
)
from hydros_agent_sdk.runtime.coordination_outbox import CoordinationOutboxPublisher
from hydros_agent_sdk.runtime.task_runtime import TaskRuntime
from hydros_agent_sdk.transport.base import Transport
from hydros_agent_sdk.transport.mqtt_coordination import MqttCoordinationTransport

logger = logging.getLogger(__name__)

IGNORED_COORDINATION_COMMAND_TYPES = {
    "update_monitor_rule_request",
    "update_monitor_rule_response",
}


class SimCoordinationClient:
    """
    基于回调架构的高层仿真协调客户端。

    该类只装配协调传输、消息过滤和任务运行时：
    - 将 transport raw payload 解码、过滤并投递给 TaskRuntime
    - 将 TaskRuntime 产生的响应交给 CoordinationOutboxPublisher
    - 把 MQTT/Paho 生命周期交给 CoordinationTransport

    开发者只需要实现 SimCoordinationCallback 来提供业务逻辑。

    功能类似 Java 侧的 SimCoordinationSlave 类。

    示例：
        ```python
        class MyCallback(SimCoordinationCallback):
        
            def on_sim_task_init(self, request):
                # 你的业务逻辑写在这里
                pass

            def on_tick(self, request):
                # 你的业务逻辑写在这里
                pass

        # 创建并启动客户端
        callback = MyCallback()
        client = SimCoordinationClient(
            broker_url="tcp://192.168.1.24",
            broker_port=1883,
            topic="/hydros/commands/coordination/my_cluster",
            callback=callback
        )
        client.start()
        ```
    """

    def __init__(
        self,
        broker_url: str,
        broker_port: int,
        topic: Optional[str] = None,
        hydros_cluster_id: Optional[str] = None,
        sim_coordination_callback: Optional[SimCoordinationCallback] = None,
        state_manager: Optional[AgentStateManager] = None,
        qos: int = 1,
        max_retry_count: int = 5,
        base_retry_delay_ms: int = 1000,
        mqtt_username: Optional[str] = None,
        mqtt_password: Optional[str] = None,
        control_queue_size: int = 1000,
        business_queue_size: int = 1000,
        transport: Optional[Transport] = None,
    ):
        """
        初始化协调客户端。

        Args:
            broker_url: MQTT broker URL（例如 "tcp://192.168.1.24"）
            broker_port: MQTT broker 端口（默认 1883）
            topic: 要订阅的 MQTT topic
            hydros_cluster_id: 可选集群 ID，用于推导协调 topic
            sim_coordination_callback: SimCoordinationCallback 实现
            state_manager: 可选状态管理器，未提供时自动创建
            qos: MQTT QoS 级别（默认 1）
            max_retry_count: 发送消息的最大重试次数（默认 5）
            base_retry_delay_ms: 基础重试延迟，单位毫秒（默认 1000）
            mqtt_username: 可选 MQTT 认证用户名；None 表示不启用认证
            mqtt_password: 可选 MQTT 认证密码；None 表示不启用认证
            control_queue_size: 生命周期/控制指令最大积压数量
            business_queue_size: 业务指令最大积压数量
        """
        self.broker_url = broker_url.replace("tcp://", "")
        self.broker_port = broker_port
        if topic:
            self.topic = topic
        elif hydros_cluster_id:
            self.topic = HydrosTopics.get_coordination_command_topic(hydros_cluster_id)
        else:
            raise ValueError("topic 和 hydros_cluster_id 不能同时为空")
        if sim_coordination_callback is None:
            raise ValueError("sim_coordination_callback is required")
        self.sim_coordination_callback = sim_coordination_callback
        self.qos = qos
        self.max_retry_count = max_retry_count
        self.base_retry_delay_ms = base_retry_delay_ms
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password

        # 生成客户端 ID
        self.client_id = f"hydros_node_{int(time.time() * 1000)}"

        # 初始化状态管理器
        if state_manager is None:
            state_manager = AgentStateManager()
        self.state_manager = state_manager

        # 初始化消息过滤器
        self.message_filter = MessageFilter(self.state_manager)

        if transport is None:
            transport = MqttCoordinationTransport(
                broker_url=self.broker_url,
                broker_port=self.broker_port,
                client_id=self.client_id,
                topic=self.topic,
                handler=self._handle_transport_payload,
                qos=self.qos,
                mqtt_username=mqtt_username,
                mqtt_password=mqtt_password,
            )
        else:
            transport.subscribe(self.topic, self._handle_transport_payload, qos=self.qos)
        self.transport = transport
        self.outbox_publisher = CoordinationOutboxPublisher(
            transport=self.transport,
            state_manager=self.state_manager,
            topic=self.topic,
            qos=self.qos,
            max_retry_count=self.max_retry_count,
            base_retry_delay_ms=self.base_retry_delay_ms,
        )
        self.task_runtime = TaskRuntime(
            callback=self.sim_coordination_callback,
            state_manager=self.state_manager,
            outbound_submitter=self.outbox_publisher.enqueue,
            control_queue_size=control_queue_size,
            business_queue_size=business_queue_size,
            log=logger,
        )
        logger.info("Registered %s command handlers", len(self.task_runtime.router.handlers))

        logger.info(f"SimCoordinationClient initialized: client_id={self.client_id}, topic={self.topic}")

    def start(self):
        """
        启动协调客户端。

        该方法会：
        1. 连接 MQTT broker
        2. 订阅协调 topic
        3. 启动任务运行时和出站发布器
        """
        if self.task_runtime.running.is_set():
            logger.warning("Client already running")
            return

        logger.info(f"Starting SimCoordinationClient: {self.client_id}")

        self.outbox_publisher.start()
        self.task_runtime.start()
        try:
            self.transport.start()
        except Exception:
            self.task_runtime.stop()
            self.outbox_publisher.stop()
            raise

        logger.info(f"SimCoordinationClient started successfully")

    def stop(self):
        """
        停止协调客户端。

        该方法会：
        1. 停止任务运行时和出站发布器
        2. 断开 MQTT broker
        3. 清理资源
        """
        if not self.task_runtime.running.is_set():
            logger.warning("Client not running")
            return

        logger.info("Stopping SimCoordinationClient...")

        self.task_runtime.stop()
        self.outbox_publisher.stop()
        self.transport.stop()

        logger.info("SimCoordinationClient stopped")

    def enqueue(self, command: SimCommand):
        """Submit a locally produced coordination command to the outbox."""
        self.outbox_publisher.enqueue(command)

    def _handle_transport_payload(self, topic: str, payload_str: str) -> None:
        """Decode, filter and enqueue one raw payload delivered by the transport."""
        data = None
        try:
            logger.debug("Received message on topic %s: %s...", topic, payload_str[:200])

            # 解析 JSON
            data = json.loads(payload_str)
            logger.debug(
                "MQTT command received: topic=%s, rawType=%s, commandId=%s, context=%s",
                topic,
                data.get("command_type") if isinstance(data, dict) else None,
                data.get("command_id") if isinstance(data, dict) else None,
                self._raw_context_id(data),
            )
            if self._should_ignore_raw_command(data):
                logger.debug(
                    "MQTT command ignored: type=%s, id=%s, context=%s, reason=disabled_command_type",
                    data.get("command_type"),
                    data.get("command_id"),
                    self._raw_context_id(data),
                )
                return

            envelope = SimCommandEnvelope(command=data)
            command = envelope.command
            # 应用消息过滤器
            if not self.message_filter.should_process_message(command):
                return

            # 将业务处理推迟给 SDK 工作线程，避免 MQTT 网络回调
            # 被较慢的 tick/event/MPC 处理阻塞。
            self.task_runtime.enqueue(command)

        except Exception as e:
            logger.error(
                "Error processing MQTT message: rawType=%s, commandId=%s, context=%s, error=%s, payloadPrefix=%s",
                data.get("command_type") if isinstance(data, dict) else None,
                data.get("command_id") if isinstance(data, dict) else None,
                self._raw_context_id(data),
                e,
                payload_str[:500] if payload_str else None,
                exc_info=True,
            )

    @staticmethod
    def _raw_context_id(data):
        if not isinstance(data, dict):
            return None
        context = data.get("context")
        if isinstance(context, dict):
            return context.get("biz_scene_instance_id") or context.get("bizSceneInstanceId")
        return None

    @staticmethod
    def _should_ignore_raw_command(data) -> bool:
        if not isinstance(data, dict):
            return False
        return data.get("command_type") in IGNORED_COORDINATION_COMMAND_TYPES
