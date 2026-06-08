"""
基于回调架构的仿真协调客户端。

本模块提供一个封装通用 MQTT 逻辑的高层客户端，让开发者通过实现回调
专注于业务逻辑。

功能类似 Java 侧的 SimCoordinationSlave 类。
"""

import logging
import time
import traceback
from dataclasses import dataclass
from typing import Optional, Dict, Callable
from queue import Queue, Empty, Full
from threading import Thread, Event, RLock
import paho.mqtt.client as mqtt

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.message_filter import MessageFilter
from hydros_agent_sdk.topics import HydrosTopics
from hydros_agent_sdk.logging_config import (
    set_biz_scene_instance_id,
    set_biz_component,
    set_hydros_cluster_id,
    set_hydros_node_id
)
from hydros_agent_sdk.protocol.commands import (
    SimCommand,
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    OutflowTimeSeriesDataUpdateRequest,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
    HydroEventAckResponse,
    HydroEventCommand,
    MpcResultReport,
    OutflowTimeSeriesDataUpdateResponse,
    SimCoordinationRequest,
    SimCoordinationResponse,
    SimCommandEnvelope,
    OutflowTimeSeriesRequest,
    OutflowTimeSeriesResponse,

    # 指令类型常量
    SIMCMD_TASK_INIT_REQUEST,
    SIMCMD_TASK_INIT_RESPONSE,
    SIMCMD_TICK_CMD_REQUEST,
    SIMCMD_TASK_TERMINATE_REQUEST,
    SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST,
    SIMCMD_HYDRO_EVENT_COMMAND,
    SIMCMD_TIME_SERIES_CALCULATION_REQUEST,
    SIMCMD_AGENT_INSTANCE_STATUS_REPORT,
    SIMCMD_MPC_RESULT_REPORT,
    SIMCMD_OUTFLOW_TIME_SERIES_REQUEST,
    SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST
)
from hydros_agent_sdk.error_codes import ErrorCodes
from hydros_agent_sdk.protocol.events import (
    OutflowTimeSeriesDataChangedEvent,
    OutflowTimeSeriesEvent,
    TimeSeriesDataChangedEvent,
)
from hydros_agent_sdk.protocol.models import CommandStatus, HydroAgentInstance
from hydros_agent_sdk.runtime import ResponseFactory
import json

logger = logging.getLogger(__name__)

IGNORED_COORDINATION_COMMAND_TYPES = {
    "update_monitor_rule_request",
    "update_monitor_rule_response",
}


@dataclass(frozen=True)
class InboundCommand:
    command: SimCommand
    received_at: float
    queue_name: str


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

        # 入站消息队列。MQTT 回调必须保持轻量，
        # 可能较慢的业务处理器由工作线程执行。
        self.control_message_queue: Queue[InboundCommand] = Queue(maxsize=control_queue_size)
        self.business_queue_size = business_queue_size
        self.business_message_queues: Dict[str, Queue[InboundCommand]] = {}
        self._business_workers_lock = RLock()

        # 线程管理
        self.running = Event()
        self.queue_thread: Optional[Thread] = None
        self.control_worker_thread: Optional[Thread] = None
        self.business_worker_threads: Dict[str, Thread] = {}
        self.connected = Event()

        # 注册指令处理器
        self._register_handlers()

        logger.info(f"SimCoordinationClient initialized: client_id={self.client_id}, topic={self.topic}")

    def _register_handlers(self):
        """注册全部会路由到回调方法的指令处理器。"""
        self.handlers: Dict[str, Callable[[SimCommand], None]] = {
            SIMCMD_TASK_INIT_REQUEST: self._handle_task_init,
            SIMCMD_TASK_INIT_RESPONSE: self._handle_task_init_response,
            SIMCMD_TICK_CMD_REQUEST: self._handle_tick,
            SIMCMD_TASK_TERMINATE_REQUEST: self._handle_task_terminate,
            SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST: self._handle_time_series_data_update,
            SIMCMD_HYDRO_EVENT_COMMAND: self._handle_hydro_event_command,
            SIMCMD_TIME_SERIES_CALCULATION_REQUEST: self._handle_time_series_calculation,
            SIMCMD_AGENT_INSTANCE_STATUS_REPORT: self._handle_agent_status_report,
            SIMCMD_MPC_RESULT_REPORT: self._handle_mpc_result_report,
            SIMCMD_OUTFLOW_TIME_SERIES_REQUEST: self._handle_outflow_time_series_request,
            SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST: self._handle_outflow_time_series_data_update
        }
        logger.info(f"Registered {len(self.handlers)} command handlers")

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
        self.mqtt_client.connect(self.broker_url, self.broker_port, keepalive=60)
        self.mqtt_client.loop_start()

        # 等待连接建立
        if not self.connected.wait(timeout=10):
            raise RuntimeError("Failed to connect to MQTT broker within 10 seconds")

        # 启动队列处理线程
        self.running.set()
        self._start_inbound_workers()
        self.queue_thread = Thread(target=self._queue_loop, daemon=True, name="QueueThread")
        self.queue_thread.start()

        logger.info(f"SimCoordinationClient started successfully")

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
        self.running.clear()
        self._stop_inbound_workers()
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
        logger.info(f"Enqueued command: {self._format_command_for_log(command)}")

    def send_command(self, command: SimCommand):
        """
        立即同步发送指令。

        Args:
            command: 要发送的指令
        """
        self._send_with_retry(command)

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
            self._enqueue_incoming(command)

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

    @staticmethod
    def _command_context_id(command: SimCommand):
        context = getattr(command, "context", None)
        return getattr(context, "biz_scene_instance_id", None)

    @staticmethod
    def _command_event_type(command: SimCommand):
        if isinstance(command, HydroEventCommand):
            return getattr(command.payload, "hydro_event_type", None)
        event = getattr(command, "time_series_data_changed_event", None)
        if event is not None:
            return getattr(event, "hydro_event_type", None)
        event = getattr(command, "outflow_time_series_data_changed_event", None)
        if event is not None:
            return getattr(event, "hydro_event_type", None)
        event = getattr(command, "hydro_event", None)
        if event is not None:
            return getattr(event, "hydro_event_type", None)
        return None

    # ========================================================================
    # 消息处理
    # ========================================================================

    def _start_inbound_workers(self):
        """如果入站指令工作线程尚未运行，则启动它们。"""
        if self.control_worker_thread is None or not self.control_worker_thread.is_alive():
            self.control_worker_thread = Thread(
                target=self._inbound_worker_loop,
                args=(self.control_message_queue, "ControlWorker"),
                daemon=True,
                name="ControlWorker",
            )
            self.control_worker_thread.start()

    def _stop_inbound_workers(self):
        """运行标记清除后，短暂等待入站工作线程停止。"""
        with self._business_workers_lock:
            business_workers = list(self.business_worker_threads.values())
            self.business_worker_threads.clear()
            self.business_message_queues.clear()

        for worker in [self.control_worker_thread, *business_workers]:
            if worker and worker.is_alive():
                worker.join(timeout=5)

    def _enqueue_incoming(self, command: SimCommand):
        queue_name, target_queue = self._select_inbound_queue(command)
        item = InboundCommand(command=command, received_at=time.monotonic(), queue_name=queue_name)
        try:
            target_queue.put_nowait(item)
            logger.info(
                "Inbound command enqueued: type=%s, id=%s, context=%s, queue=%s, queueSize=%s",
                command.command_type,
                command.command_id,
                self._command_context_id(command),
                queue_name,
                target_queue.qsize(),
            )
        except Full:
            logger.error(
                "Inbound queue full: type=%s, id=%s, context=%s, queue=%s, capacity=%s",
                command.command_type,
                command.command_id,
                self._command_context_id(command),
                queue_name,
                target_queue.maxsize,
            )

    def _select_inbound_queue(self, command: SimCommand):
        if isinstance(command, (SimTaskInitRequest, SimTaskTerminateRequest)):
            return "control", self.control_message_queue

        context_id = self._command_context_id(command) or "__no_context__"
        return f"business:{context_id}", self._get_or_start_business_queue(context_id)

    def _get_or_start_business_queue(self, context_id: str) -> Queue[InboundCommand]:
        with self._business_workers_lock:
            business_queue = self.business_message_queues.get(context_id)
            if business_queue is None:
                business_queue = Queue(maxsize=self.business_queue_size)
                self.business_message_queues[context_id] = business_queue

            worker = self.business_worker_threads.get(context_id)
            if worker is None or not worker.is_alive():
                worker_name = f"BusinessWorker:{context_id}"
                worker = Thread(
                    target=self._inbound_worker_loop,
                    args=(business_queue, worker_name),
                    daemon=True,
                    name=worker_name,
                )
                self.business_worker_threads[context_id] = worker
                worker.start()
        return business_queue

    def _inbound_worker_loop(self, source_queue: Queue[InboundCommand], worker_name: str):
        logger.info("Inbound command worker started: %s", worker_name)
        while self.running.is_set():
            try:
                item = source_queue.get(timeout=1)
            except Empty:
                continue

            queue_wait_ms = (time.monotonic() - item.received_at) * 1000
            started_at = time.monotonic()
            command = item.command
            try:
                logger.info(
                    "Inbound command handling started: type=%s, id=%s, context=%s, queue=%s, queueWaitMs=%.2f, worker=%s",
                    command.command_type,
                    command.command_id,
                    self._command_context_id(command),
                    item.queue_name,
                    queue_wait_ms,
                    worker_name,
                )
                self._handle_incoming_message(command)
                duration_ms = (time.monotonic() - started_at) * 1000
                logger.debug(
                    "Inbound command handled: type=%s, id=%s, context=%s, handlerDurationMs=%.2f, worker=%s",
                    command.command_type,
                    command.command_id,
                    self._command_context_id(command),
                    duration_ms,
                    worker_name,
                )
            except Exception as e:
                logger.error(
                    "Error in inbound worker %s: type=%s, id=%s, context=%s, error=%s",
                    worker_name,
                    command.command_type,
                    command.command_id,
                    self._command_context_id(command),
                    e,
                    exc_info=True,
                )
            finally:
                source_queue.task_done()

        logger.info("Inbound command worker stopped: %s", worker_name)

    def _set_logging_context(self, command: SimCommand):
        """
        从指令设置日志上下文，用于结构化日志。

        从指令中提取上下文信息并写入日志上下文，确保后续日志包含这些信息。

        日志上下文包括：
        - hydros_cluster_id: 来自 state_manager（从 env.properties 加载）
        - hydros_node_id: 来自 state_manager（从 env.properties 加载）
        - biz_scene_instance_id: 来自指令的 SimulationContext
        - biz_component: 智能体 ID 或组件名称（例如 "SIM_COORDINATOR"）

        Args:
            command: 用于提取上下文的指令
        """
        # 从 state_manager 设置 hydros_cluster_id
        cluster_id = self.state_manager.get_cluster_id()
        if cluster_id:
            set_hydros_cluster_id(cluster_id)

        # 从 state_manager 设置 hydros_node_id
        node_id = self.state_manager.get_node_id()
        if node_id:
            set_hydros_node_id(node_id)

        # 从指令上下文（SimulationContext）设置 biz_scene_instance_id
        if hasattr(command, 'context') and command.context:
            biz_scene_instance_id = command.context.biz_scene_instance_id
            if biz_scene_instance_id:
                set_biz_scene_instance_id(biz_scene_instance_id)

        # 从 callback 的 component 设置 biz_component
        # 在智能体上下文中为 agent_id，在基础设施上下文中为 component 名称
        component = self.sim_coordination_callback.get_component()
        if component:
            set_biz_component(component)

    def _handle_incoming_message(self, command: SimCommand):
        """
        处理入站指令，并路由到合适的处理器。

        调用处理器前会自动设置日志上下文（task_id、biz_component、node_id），
        使处理器内的全部日志都包含该上下文。

        Args:
            command: 要处理的指令
        """
        # 根据指令设置日志上下文
        self._set_logging_context(command)

        handler = self.handlers.get(command.command_type)
        if handler:
            try:
                logger.debug(
                    "MQTT command accepted: type=%s, id=%s, context=%s, eventType=%s, handler=%s",
                    command.command_type,
                    command.command_id,
                    self._command_context_id(command),
                    self._command_event_type(command),
                    getattr(handler, "__name__", str(handler)),
                )
                result = handler(command)
                self._handle_callback_result(result)
            except Exception as e:
                logger.error(f"Error handling command {command.command_type}: {e}", exc_info=True)
                error_response = self._create_error_response(command, e)
                if error_response:
                    self.enqueue(error_response)
        else:
            logger.warning(f"No handler registered for command type: {command.command_type}")

    def _handle_callback_result(self, result):
        """
        通过正常出站队列发送回调返回值。

        这样既保留现有副作用式回调的工作方式，也支持从回调直接返回响应的
        更简单模式。
        """
        if result is None:
            return

        if isinstance(result, SimCommand):
            self.enqueue(result)
            return

        if isinstance(result, (list, tuple)):
            for item in result:
                self._handle_callback_result(item)
            return

        logger.debug("Ignoring unsupported callback result type: %s", type(result).__name__)

    def _create_error_response(self, command: SimCommand, error: Exception) -> Optional[SimCoordinationResponse]:
        """
        尽可能将未捕获的处理器异常转换为失败响应。

        某些请求类型，尤其是智能体创建前的任务初始化请求，可能缺少足够的
        本地智能体上下文来满足协议要求的 source_agent_instance 字段。
        这种情况下只记录日志，并将异常视为基础设施错误，而不是构造无效响应。
        """
        source_agent = self._resolve_error_source_agent(command)
        if source_agent is None:
            logger.error(
                "Cannot create error response for command %s (%s): no source agent available",
                command.command_id,
                command.command_type,
            )
            return None

        error_code = ErrorCodes.SYSTEM_ERROR

        if isinstance(command, SimTaskInitRequest):
            error_code = ErrorCodes.AGENT_INIT_FAILURE
            factory_method = ResponseFactory.init_failed
        elif isinstance(command, TickCmdRequest):
            error_code = ErrorCodes.AGENT_TICK_FAILURE
            factory_method = ResponseFactory.tick_failed
        elif isinstance(command, SimTaskTerminateRequest):
            error_code = ErrorCodes.AGENT_TERMINATE_FAILURE
            factory_method = ResponseFactory.terminate_failed
        elif isinstance(command, TimeSeriesDataUpdateRequest):
            error_code = ErrorCodes.TIME_SERIES_UPDATE_FAILURE
            factory_method = ResponseFactory.time_series_data_update_failed
        elif isinstance(command, HydroEventCommand):
            response = HydroEventAckResponse(
                context=command.context,
                command_id=command.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=source_agent,
                broadcast=False,
                error_code=ErrorCodes.SYSTEM_ERROR.code,
                error_message=f"{error}\n{traceback.format_exc()}",
            )
            return response
        elif isinstance(command, TimeSeriesCalculationRequest):
            error_code = ErrorCodes.TIME_SERIES_CALCULATION_FAILURE
            factory_method = ResponseFactory.time_series_calculation_failed
        else:
            factory_method = None

        if factory_method is None:
            logger.debug("No error response mapping for command type: %s", command.command_type)
            return None

        agent_name = getattr(source_agent, "agent_code", self.sim_coordination_callback.get_component())
        error_detail = f"{error}\n{traceback.format_exc()}"
        error_message = error_code.format_message(agent_name, error_detail)

        return factory_method(
            source_agent,
            command,
            error_code=error_code.code,
            error_message=error_message,
        )

    def _resolve_error_source_agent(self, command: SimCommand) -> Optional[HydroAgentInstance]:
        """查找适合作为 source_agent_instance 的本地智能体实例。"""
        target_agent = getattr(command, "target_agent_instance", None)
        if target_agent is not None:
            return target_agent

        context = getattr(command, "context", None)
        context_id = getattr(context, "biz_scene_instance_id", None)
        if context_id:
            agents = self.state_manager.get_agents_for_context(context_id)
            if agents:
                return agents[0]

            callback_agents = getattr(self.sim_coordination_callback, "agents", None)
            if isinstance(callback_agents, dict):
                context_agents = callback_agents.get(context_id)
                if isinstance(context_agents, dict) and context_agents:
                    return next(iter(context_agents.values()))

        return None

    # ========================================================================
    # 指令处理器（路由到 callback）
    # ========================================================================

    def _handle_task_init(self, command: SimCommand):
        """处理任务初始化请求。"""
        request = command
        assert isinstance(request, SimTaskInitRequest)
        return self.sim_coordination_callback.on_sim_task_init(request)

    def _handle_task_init_response(self, command: SimCommand):
        """处理远端智能体的任务初始化响应。"""
        response = command
        assert isinstance(response, SimTaskInitResponse)
        if self.sim_coordination_callback.is_remote_agent(response.source_agent_instance):
            return self.sim_coordination_callback.on_agent_instance_sibling_created(response)
        return None

    def _handle_tick(self, command: SimCommand):
        """处理 tick 指令。"""
        request = command
        assert isinstance(request, TickCmdRequest)
        return self.sim_coordination_callback.on_tick(request)

    def _handle_task_terminate(self, command: SimCommand):
        """处理任务终止请求。"""
        request = command
        assert isinstance(request, SimTaskTerminateRequest)
        return self.sim_coordination_callback.on_task_terminate(request)

    def _handle_time_series_data_update(self, command: SimCommand):
        """处理时间序列数据更新。"""
        request = command
        assert isinstance(request, TimeSeriesDataUpdateRequest)
        return self.sim_coordination_callback.on_time_series_data_update(request)

    def _handle_hydro_event_command(self, command: SimCommand):
        """处理兼容 Java 侧的 hydro_event_command payload 路由。"""
        request = command
        assert isinstance(request, HydroEventCommand)
        payload = request.payload

        if isinstance(payload, TimeSeriesDataChangedEvent):
            update_request = TimeSeriesDataUpdateRequest(
                command_id=request.command_id,
                context=request.context,
                broadcast=request.broadcast,
                time_series_data_changed_event=payload,
            )
            result = self.sim_coordination_callback.on_time_series_data_update(update_request)
            return self._to_hydro_event_ack_response(request, result)

        if isinstance(payload, OutflowTimeSeriesDataChangedEvent):
            update_request = OutflowTimeSeriesDataUpdateRequest(
                command_id=request.command_id,
                context=request.context,
                broadcast=request.broadcast,
                outflow_time_series_data_changed_event=payload,
            )
            result = self.sim_coordination_callback.on_outflow_time_series_data_update(update_request)
            return self._to_hydro_event_ack_response(request, result)

        if isinstance(payload, OutflowTimeSeriesEvent):
            if request.target_agent_instance is None:
                logger.warning(
                    "Ignoring outflow hydro_event_command without target_agent_instance: id=%s",
                    request.command_id,
                )
                return None
            outflow_request = OutflowTimeSeriesRequest(
                command_id=request.command_id,
                context=request.context,
                broadcast=request.broadcast,
                target_agent_instance=request.target_agent_instance,
                hydro_event=payload,
            )
            return self.sim_coordination_callback.on_outflow_time_series(outflow_request)

        logger.warning(
            "Ignoring unsupported hydro_event_command payload: id=%s, eventType=%s",
            request.command_id,
            getattr(payload, "hydro_event_type", None),
        )
        return None

    def _to_hydro_event_ack_response(self, request: HydroEventCommand, result):
        """将更新响应转换为兼容 Java 侧的 hydro_event_ack_response。"""
        if result is None:
            return None

        if isinstance(result, HydroEventAckResponse):
            return result

        if isinstance(result, (TimeSeriesDataUpdateResponse, OutflowTimeSeriesDataUpdateResponse)):
            return self._build_hydro_event_ack_response(request, result)

        if isinstance(result, list):
            responses = []
            for item in result:
                if isinstance(item, HydroEventAckResponse):
                    responses.append(item)
                elif isinstance(item, (TimeSeriesDataUpdateResponse, OutflowTimeSeriesDataUpdateResponse)):
                    responses.append(self._build_hydro_event_ack_response(request, item))
            return responses

        return None

    @staticmethod
    def _build_hydro_event_ack_response(
        request: HydroEventCommand,
        response: SimCoordinationResponse,
    ) -> HydroEventAckResponse:
        return HydroEventAckResponse(
            context=request.context,
            command_id=request.command_id,
            command_status=response.command_status,
            source_agent_instance=response.source_agent_instance,
            broadcast=False,
            error_code=response.error_code,
            error_message=response.error_message,
        )

    def _handle_outflow_time_series_data_update(self, command: SimCommand):
        """处理出流时间序列数据更新。"""
        request = command
        assert isinstance(request, OutflowTimeSeriesDataUpdateRequest)
        return self.sim_coordination_callback.on_outflow_time_series_data_update(request)

    def _handle_time_series_calculation(self, command: SimCommand):
        """处理时间序列计算。"""
        request = command
        assert isinstance(request, TimeSeriesCalculationRequest)
        return self.sim_coordination_callback.on_time_series_calculation(request)

    def _handle_agent_status_report(self, command: SimCommand):
        """处理远端智能体状态报告。"""
        report = command
        assert isinstance(report, AgentInstanceStatusReport)
        if self.sim_coordination_callback.is_remote_agent(report.source_agent_instance):
            return self.sim_coordination_callback.on_agent_instance_sibling_status_updated(report)
        return None

    def _handle_mpc_result_report(self, command: SimCommand):
        """处理远端智能体的 MPC 结果报告。"""
        report = command
        assert isinstance(report, MpcResultReport)
        if self.sim_coordination_callback.is_remote_agent(report.source_agent_instance):
            return self.sim_coordination_callback.on_mpc_result(report)
        return None

    def _handle_outflow_time_series_request(self, command: SimCommand):
        """处理出流时间序列请求。"""
        request = command
        assert isinstance(request, OutflowTimeSeriesRequest)
        return self.sim_coordination_callback.on_outflow_time_series(request)

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
                if self._should_send(command):
                    self._send_with_retry(command)

            except Empty:
                # 超时，继续循环
                continue
            except Exception as e:
                logger.error(f"Error in queue loop: {e}", exc_info=True)

        logger.info("Queue processing thread stopped")

    def _should_send(self, command: SimCommand) -> bool:
        """
        检查指令是否应该发送。

        类似 Java 侧的 needSend() 方法。

        Args:
            command: 要检查的指令

        Returns:
            应发送时返回 True，否则返回 False
        """
        # 不发送请求（只发送响应和报告）
        if isinstance(command, SimCoordinationRequest):
            return False

        # 只发送本地智能体的响应
        if isinstance(command, SimCoordinationResponse):
            if isinstance(command, SimTaskTerminateResponse):
                node_id = self.state_manager.get_node_id()
                if node_id and command.source_agent_instance.hydros_node_id == node_id:
                    return True
            return self.state_manager.is_local_agent(command.source_agent_instance)

        # 发送本地智能体的状态报告。任务终止时，本地智能体注册表可能在异步发送循环
        # 清空之前已被清理，因此仅对状态报告使用当前节点 ID 兜底。
        if isinstance(command, AgentInstanceStatusReport):
            if self.state_manager.is_local_agent(command.source_agent_instance):
                return True
            node_id = self.state_manager.get_node_id()
            return bool(node_id and command.source_agent_instance.hydros_node_id == node_id)

        # 只发送已注册本地智能体的 MPC 结果报告。
        if isinstance(command, MpcResultReport):
            return self.state_manager.is_local_agent(command.source_agent_instance)

        return False

    def _send_with_retry(self, command: SimCommand):
        """
        使用重试逻辑发送指令。

        类似 Java 侧的 sendAsyncWithRetry() 方法。

        Args:
            command: 要发送的指令
        """
        attempt = 0
        command_id = command.command_id

        while attempt <= self.max_retry_count:
            try:
                # 序列化指令
                payload = command.model_dump_json(by_alias=True)

                # 发布到 MQTT
                result = self.mqtt_client.publish(self.topic, payload, qos=self.qos)
                result.wait_for_publish()

                if isinstance(command, MpcResultReport):
                    logger.info(
                        "MPC result report sent to coordinator: topic=%s, command_id=%s, "
                        "result_count=%s, detail_count=%s",
                        self.topic,
                        command_id,
                        len(command.mpc_results or []),
                        self._count_mpc_result_details(command),
                    )
                return  # 发送成功

            except Exception as e:
                logger.error(f"Failed to send command: id={command_id}, attempt={attempt}/{self.max_retry_count}: {e}")

                attempt += 1
                if attempt > self.max_retry_count:
                    logger.error(f"Max retry count exceeded for command: id={command_id}")
                    raise

                # 指数退避：2^attempt * 基础延迟
                delay_ms = self.base_retry_delay_ms * (2 ** attempt)
                logger.info(f"Retrying after {delay_ms}ms... (attempt {attempt}/{self.max_retry_count})")
                time.sleep(delay_ms / 1000.0)

    @staticmethod
    def _format_command_for_log(command: SimCommand) -> str:
        if isinstance(command, MpcResultReport):
            summary = {
                "command_type": command.command_type,
                "command_id": command.command_id,
                "biz_scene_instance_id": (
                    command.context.biz_scene_instance_id
                    if command.context is not None
                    else None
                ),
                "result_count": len(command.mpc_results or []),
                "detail_count": SimCoordinationClient._count_mpc_result_details(command),
            }
            return json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        return command.model_dump_json(indent=None)

    @staticmethod
    def _count_mpc_result_details(command: MpcResultReport) -> int:
        return sum(len(result.details or []) for result in command.mpc_results or [])
