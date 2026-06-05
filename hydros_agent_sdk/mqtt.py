import json
import logging
from typing import Callable, Dict, Any, Type, Optional
import paho.mqtt.client as mqtt
from pydantic import ValidationError

from hydros_agent_sdk.protocol.commands import SimCommandEnvelope, HydroCmd, SimCommand
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.message_filter import MessageFilter

logger = logging.getLogger(__name__)

# 回调类型定义：接收 HydroCmd（或其子类），不返回内容或返回响应
CommandHandler = Callable[[HydroCmd], Any]

class CommandDispatcher:
    def __init__(self, message_filter: Optional[MessageFilter] = None):
        self._handlers: Dict[str, CommandHandler] = {}
        self._message_filter = message_filter

    def register_handler(self, command_type: str, handler: CommandHandler):
        """
        为指定指令类型注册处理函数。
        """
        self._handlers[command_type] = handler
        logger.info(f"Registered handler for command type: {command_type}")

    def set_message_filter(self, message_filter: MessageFilter):
        """
        设置用于过滤传入指令的消息过滤器。

        Args:
            message_filter: 要使用的 MessageFilter 实例
        """
        self._message_filter = message_filter
        logger.info("Message filter configured for dispatcher")

    def dispatch(self, payload: bytes) -> Any:
        """
        解析 payload 并分派给合适的处理器。

        实现类似 Java SimCoordinationSlave.messageArrived() 的消息过滤逻辑：
        1. 解析指令
        2. 应用消息过滤器（isActiveToTaskSimCommand、isReceived）
        3. 过滤通过后分派给处理器
        """
        try:
            # 将 bytes 解码为字符串
            payload_str = payload.decode("utf-8")
            logger.debug(f"Received payload: {payload_str[:200]}...")  # 记录前 200 个字符

            # 解析 JSON
            data = json.loads(payload_str)

            # 使用 Pydantic 和 Discriminated Union 解析为正确对象类型
            envelope = SimCommandEnvelope(command=data)
            command_obj = envelope.command

            # 如果已配置消息过滤器，则应用过滤
            if self._message_filter and isinstance(command_obj, SimCommand):
                if not self._message_filter.should_process_message(command_obj):
                    logger.info(f"Message filtered out: {command_obj.command_type}, "
                              f"command_id={command_obj.command_id}")
                    return None

            command_type = command_obj.command_type
            handler = self._handlers.get(command_type)

            if handler:
                logger.info(f"Dispatching command {command_type} to handler")
                return handler(command_obj)
            else:
                logger.warning(f"No handler registered for command type: {command_type}")
                return None

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON payload: {e}")
        except ValidationError as e:
            logger.error(f"Validation error during command parsing: {e}")
        except Exception as e:
            logger.error(f"Error during dispatch: {e}", exc_info=True)
        return None

class HydrosMqttClient:
    def __init__(self, client_id: str, dispatcher: Optional[CommandDispatcher] = None,
                 state_manager: Optional['AgentStateManager'] = None):
        self.client_id = client_id

        # 未提供状态管理器时初始化
        if state_manager is None:
            state_manager = AgentStateManager()
        self.state_manager = state_manager

        # 未提供分派器时初始化
        if dispatcher is None:
            message_filter = MessageFilter(self.state_manager)
            dispatcher = CommandDispatcher(message_filter)
        self.dispatcher = dispatcher

        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._connected = False

    def connect(self, broker_url: str, port: int = 1883, keepalive: int = 60,
                username: Optional[str] = None, password: Optional[str] = None):
        """
        连接 MQTT broker。

        Args:
            broker_url: MQTT broker URL（例如 "tcp://192.168.1.24"）
            port: MQTT broker 端口（默认 1883）
            keepalive: keepalive 间隔，单位秒（默认 60）
            username: 可选 MQTT 认证用户名（None 表示不认证）
            password: 可选 MQTT 认证密码（None 表示不认证）
        """
        logger.info(f"Connecting to MQTT broker at {broker_url}:{port}")
        # 解析 broker_url，处理可能存在的 tcp:// 前缀
        host = broker_url.replace("tcp://", "")

        # 如果提供凭据，则设置认证
        if username:
            self.client.username_pw_set(username, password)
            logger.info(f"MQTT authentication configured for user: {username}")

        self.client.connect(host, port, keepalive)
        self.client.loop_start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe(self, topic: str):
        """
        订阅 topic。
        """
        logger.info(f"Subscribing to topic: {topic}")
        self.client.subscribe(topic)

    def publish_command(self, topic: str, command: HydroCmd):
        """
        序列化指令/响应对象并发布到 topic。
        """
        try:
            # Pydantic v2 使用 model_dump_json
            payload = command.model_dump_json(by_alias=True)
            logger.info(f"Publishing to {topic}: {payload}")
            self.client.publish(topic, payload)
        except Exception as e:
            logger.error(f"Failed to publish command: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        _ = client, userdata, flags  # 标记为有意未使用
        if rc == 0:
            logger.info("Connected to MQTT broker successfully")
            self._connected = True
        else:
            logger.error(f"Failed to connect to MQTT broker, return code: {rc}")

    def _on_message(self, client, userdata, msg):
        _ = client, userdata  # 标记为有意未使用
        logger.debug(f"Received message on topic {msg.topic}")
        # 将消息分派给已注册的处理器
        response = self.dispatcher.dispatch(msg.payload)
        
        # 注意：如果需要回传响应，处理器或本方法需要知道 reply topic。
        # 当前假设由处理器处理必要的响应逻辑，或返回一个我们可能需要发布的响应对象。
        # 需求中提到“通过 MQTT 返回响应”。
        # 通常请求会有 reply-to 字段，或按约定发布到某个 topic。
        # 由于接口未指定，这里暂时把响应发布留给调用方/处理器，
        # 或后续在返回值为 HydroCmd 时扩展该逻辑。
        
        if isinstance(response, HydroCmd):
            # 是否乐观地尝试发布到默认 topic？
            # 或假设调用方处理它。
            # 分布式 RPC 通常需要 reply topic。
            # 当前假设 Stub/业务逻辑负责发布响应，
            # 或后续给 dispatch 增加 reply_topic 参数。
            pass
