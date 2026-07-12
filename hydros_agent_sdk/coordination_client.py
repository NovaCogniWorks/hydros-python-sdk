"""
基于回调架构的仿真协调客户端。

本模块提供一个封装通用 MQTT 逻辑的高层客户端，让开发者通过实现回调
专注于业务逻辑。

功能类似 Java 侧的 SimCoordinationSlave 类。
"""

import logging
import time
import socket
from typing import Optional
from queue import Empty, Queue
from threading import Thread, Event
import paho.mqtt.client as mqtt

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
import json

logger = logging.getLogger(__name__)

IGNORED_COORDINATION_COMMAND_TYPES = {
    "update_monitor_rule_request",
    "update_monitor_rule_response",
}


class SimCoordinationClient:
    """
    基于回调架构的高层仿真协调客户端。

    该类封装全部通用 MQTT 和消息处理逻辑：
    - MQTT 连接和订阅
    - 消息解析和序列化
    - 消息过滤（活跃上下文、本地/远端）
    - 自动将消息路由到回调
    - 带重试逻辑的出站消息队列
    - 线程管理

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

        # 初始化 MQTT 客户端
        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
        )
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        # 使用指数退避配置自动重连
        # min_delay=1s，max_delay=120s（每次尝试翻倍：1、2、4、8、...、120）
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)

        # 如果提供凭据，则设置 MQTT 认证
        if mqtt_username:
            self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
            logger.info(f"MQTT authentication configured for user: {mqtt_username}")

        # 跟踪主动断开，用于区分非预期断开
        self._intentional_disconnect = False

        # 出站消息队列
        self.out_message_queue: Queue[SimCommand] = Queue()
        self.outbox_publisher = CoordinationOutboxPublisher(
            mqtt_client=self.mqtt_client,
            state_manager=self.state_manager,
            topic=self.topic,
            qos=self.qos,
            max_retry_count=self.max_retry_count,
            base_retry_delay_ms=self.base_retry_delay_ms,
            log=logger,
        )

        self.task_runtime = TaskRuntime(
            callback=self.sim_coordination_callback,
            state_manager=self.state_manager,
            outbound_submitter=self.enqueue,
            control_queue_size=control_queue_size,
            business_queue_size=business_queue_size,
            log=logger,
        )
        self.running = self.task_runtime.running
        self.inbound_runtime = self.task_runtime.inbound
        self.control_message_queue = self.inbound_runtime.control_message_queue
        self.business_queue_size = self.inbound_runtime.business_queue_size
        self.business_message_queues = self.inbound_runtime.business_message_queues
        self._business_workers_lock = self.inbound_runtime.business_workers_lock

        # 线程管理
        self.queue_thread: Optional[Thread] = None
        self.control_worker_thread = self.inbound_runtime.control_worker_thread
        self.business_worker_threads = self.inbound_runtime.business_worker_threads
        self.connected = Event()

        self.command_router = self.task_runtime.router
        self.error_response_factory = self.task_runtime.error_response_factory
        logger.info(f"Registered {len(self.command_router.handlers)} command handlers")

        logger.info(f"SimCoordinationClient initialized: client_id={self.client_id}, topic={self.topic}")

    def start(self):
        """
        启动协调客户端。

        该方法会：
        1. 连接 MQTT broker
        2. 订阅协调 topic
        3. 启动出站消息队列线程
        """
        if self.running.is_set():
            logger.warning("Client already running")
            return

        logger.info(f"Starting SimCoordinationClient: {self.client_id}")

        # 连接 MQTT 代理
        logger.info(f"Connecting to MQTT broker: {self.broker_url}:{self.broker_port}")
        try:
            self.mqtt_client.connect(self.broker_url, self.broker_port, keepalive=60)
            self.mqtt_client.loop_start()
        except (OSError, socket.gaierror) as exc:
            raise RuntimeError(self._connection_failure_message(exc)) from exc

        # 等待连接建立
        if not self.connected.wait(timeout=10):
            self._cleanup_failed_start()
            raise RuntimeError(
                self._connection_failure_message(
                    "connection acknowledgement timed out after 10 seconds"
                )
            )

        # 启动队列处理线程
        self.task_runtime.start()
        self.control_worker_thread = self.inbound_runtime.control_worker_thread
        self.queue_thread = Thread(target=self._queue_loop, daemon=True, name="QueueThread")
        self.queue_thread.start()

        logger.info(f"SimCoordinationClient started successfully")

    def _connection_failure_message(self, cause) -> str:
        return (
            "Failed to connect to MQTT broker "
            f"{self.broker_url}:{self.broker_port} for topic {self.topic}: {cause}. "
            "Check env.properties mqtt_broker_url/mqtt_broker_port, DNS resolution, "
            "Kubernetes namespace/service name, and network reachability from this runtime."
        )

    def _cleanup_failed_start(self) -> None:
        try:
            self.mqtt_client.loop_stop()
        except Exception:
            logger.debug("Failed to stop MQTT loop after startup failure", exc_info=True)
        try:
            self.mqtt_client.disconnect()
        except Exception:
            logger.debug("Failed to disconnect MQTT client after startup failure", exc_info=True)

    def stop(self):
        """
        停止协调客户端。

        该方法会：
        1. 停止队列处理线程
        2. 断开 MQTT broker
        3. 清理资源
        """
        if not self.running.is_set():
            logger.warning("Client not running")
            return

        logger.info("Stopping SimCoordinationClient...")

        # 停止队列线程
        self.task_runtime.stop()
        self.control_worker_thread = self.inbound_runtime.control_worker_thread
        if self.queue_thread and self.queue_thread.is_alive():
            self.queue_thread.join(timeout=5)

        # 断开 MQTT 连接
        self._intentional_disconnect = True
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

        logger.info("SimCoordinationClient stopped")

    def enqueue(self, command: SimCommand):
        """
        将指令加入待发送队列。

        队列线程会异步发送该指令。

        Args:
            command: 要发送的指令
        """
        self.out_message_queue.put(command)
        # 使用 Pydantic 的 model_dump() 正确序列化嵌套模型
        logger.info(
            "Enqueued command: %s",
            CoordinationOutboxPublisher.format_command_for_log(command),
        )

    def send_command(self, command: SimCommand):
        """
        立即同步发送指令。

        Args:
            command: 要发送的指令
        """
        self.outbox_publisher.send_with_retry(command)

    # ========================================================================
    # MQTT 回调
    # ========================================================================

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT 连接回调，同时处理自动重连后的重新订阅。"""
        rc = reason_code.value
        if rc == 0:
            was_connected = self.connected.is_set()
            if was_connected:
                logger.info(f"Reconnected to MQTT broker: {self.broker_url}:{self.broker_port}")
            else:
                logger.info(f"Connected to MQTT broker: {self.broker_url}:{self.broker_port}")
            # 每次连接或重连后都重新订阅主题
            self.mqtt_client.subscribe(self.topic, qos=self.qos)
            logger.info(f"Subscribed to topic: {self.topic}")
            self.connected.set()
        else:
            rc_reasons = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized",
                128: "unspecified error",
                129: "malformed packet",
                130: "protocol error",
                131: "implementation specific error",
                132: "unsupported protocol version",
                133: "client identifier not valid",
                134: "bad username or password",
                135: "not authorized",
                136: "server unavailable",
                137: "server busy",
                138: "banned",
                139: "bad authentication method",
                140: "topic name invalid",
                141: "packet too large",
                142: "quota exceeded",
                143: "payload format invalid",
                144: "retain not supported",
                145: "QoS not supported",
                146: "use another server",
                147: "server moved",
                148: "connection rate exceeded",
            }
            reason = rc_reasons.get(rc, "unknown")
            logger.error(f"Failed to connect to MQTT broker, return code: {rc} ({reason})")

    def _on_disconnect(self, client, userdata, disconnect_flags=None, reason_code=0, properties=None):
        """MQTT 断开连接回调。"""
        rc = reason_code.value
        self.connected.clear()
        if rc == 0 or self._intentional_disconnect:
            logger.info("Disconnected from MQTT broker (clean)")
        else:
            rc_reasons = {
                1: "unexpected disconnect",
                7: "connection lost (keepalive timeout or broker idle disconnect)",
            }
            reason = rc_reasons.get(rc, f"unexpected, code={rc}")
            logger.warning(f"Disconnected from MQTT broker: {reason}. Auto-reconnecting...")

    def _on_message(self, client, userdata, msg):
        """MQTT 消息接收回调。"""
        payload_str = None
        data = None
        try:
            # 解析消息
            payload_str = msg.payload.decode("utf-8")
            logger.debug(f"Received message on topic {msg.topic}: {payload_str[:200]}...")

            # 解析 JSON
            data = json.loads(payload_str)
            logger.debug(
                "MQTT command received: topic=%s, rawType=%s, commandId=%s, context=%s",
                msg.topic,
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

    def _handle_incoming_message(self, command: SimCommand):
        """Delegate parsed coordination commands to the task runtime."""
        self.task_runtime.handle(command)

    # ========================================================================
    # 出站消息队列
    # ========================================================================

    def _queue_loop(self):
        """
        处理出站消息队列的主循环。

        该循环运行在独立线程中，并使用重试逻辑发送消息。
        """
        logger.info("Queue processing thread started")
        while self.running.is_set():
            try:
                # 从队列获取下一条指令（带超时，以便检查运行标记）
                command = self.out_message_queue.get(timeout=1)

                # 检查消息是否应发送
                if self.outbox_publisher.should_send(command):
                    self.outbox_publisher.send_with_retry(command)

            except Empty:
                # 超时，继续循环
                continue
            except Exception as e:
                logger.error(f"Error in queue loop: {e}", exc_info=True)

        logger.info("Queue processing thread stopped")
