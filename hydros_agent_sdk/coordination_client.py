"""
Simulation coordination client with callback-based architecture.

This module provides a high-level client that encapsulates all common MQTT logic,
allowing developers to focus on business logic by implementing callbacks.

Similar to Java's SimCoordinationSlave class.
"""

import logging
import time
import traceback
from typing import Optional, Dict, Callable
from queue import Queue, Empty
from threading import Thread, Event
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
    OutflowTimeSeriesDataUpdateRequest,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
    SimCoordinationRequest,
    SimCoordinationResponse,
    SimCommandEnvelope,
    get_command_type,
    OutflowTimeSeriesRequest,

    # Command type constants
    SIMCMD_TASK_INIT_REQUEST,
    SIMCMD_TASK_INIT_RESPONSE,
    SIMCMD_TASK_TERMINATE_RESPONSE,
    SIMCMD_TICK_CMD_REQUEST,
    SIMCMD_TASK_TERMINATE_REQUEST,
    SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST,
    SIMCMD_TIME_SERIES_CALCULATION_REQUEST,
    SIMCMD_AGENT_INSTANCE_STATUS_REPORT,
    SIMCMD_OUTFLOW_TIME_SERIES_REQUEST,
    SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST
)
from hydros_agent_sdk.error_codes import ErrorCodes
from hydros_agent_sdk.protocol.models import HydroAgentInstance
from hydros_agent_sdk.runtime import ResponseFactory
import json

logger = logging.getLogger(__name__)

SUPPORTED_SIM_COMMAND_TYPES = {
    "task_init_request",
    "task_init_response",
    "task_terminate_request",
    "task_terminate_response",
    "tick_cmd_request",
    "tick_cmd_response",
    "calculation_request",
    "device_status_change_request",
    "calculation_response",
    "device_status_change_response",
    "device_status_chagne_response",
    "time_series_data_update_request",
    "time_series_data_update_response",
    "outflow_time_series_request",
    "outflow_time_series_response",
    "outflow_time_series_data_update_request",
    "outflow_time_series_data_update_response",
    "report_agent_instance_status",
    "identified_params_report",
    "report_hydro_alert",
}


def _create_mqtt_client(client_id: str) -> mqtt.Client:
    """Create a paho client compatible with both 1.x and 2.x."""
    callback_api_version = getattr(mqtt, "CallbackAPIVersion", None)
    if callback_api_version is not None:
        return mqtt.Client(
            callback_api_version=callback_api_version.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
    return mqtt.Client(
        client_id=client_id,
        protocol=mqtt.MQTTv311,
    )


def _reason_code_value(reason_code) -> int:
    """Normalize paho reason code objects and legacy integer rc values."""
    return getattr(reason_code, "value", reason_code)


class SimCoordinationClient:
    """
    High-level simulation coordination client with callback-based architecture.

    This class encapsulates all common MQTT and message handling logic:
    - MQTT connection and subscription
    - Message parsing and serialization
    - Message filtering (active context, local/remote)
    - Automatic message routing to callbacks
    - Outgoing message queue with retry logic
    - Thread management

    Developers only need to implement SimCoordinationCallback to provide business logic.

    Similar to Java's SimCoordinationSlave class.

    Example:
        ```python
        class MyCallback(SimCoordinationCallback):
        
            def on_sim_task_init(self, request):
                # Your business logic here
                pass

            def on_tick(self, request):
                # Your business logic here
                pass

        # Create and start client
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
        mqtt_password: Optional[str] = None
    ):
        """
        Initialize the coordination client.

        Args:
            broker_url: MQTT broker URL (e.g., "tcp://192.168.1.24")
            broker_port: MQTT broker port (default: 1883)
            topic: MQTT topic to subscribe to
            hydros_cluster_id: Optional cluster ID used to derive the coordination topic
            sim_coordination_callback: SimCoordinationCallback implementation
            state_manager: Optional state manager (created if not provided)
            qos: MQTT QoS level (default: 1)
            max_retry_count: Maximum retry count for sending messages (default: 5)
            base_retry_delay_ms: Base retry delay in milliseconds (default: 1000)
            mqtt_username: Optional MQTT username for authentication (None for no auth)
            mqtt_password: Optional MQTT password for authentication (None for no auth)
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

        # Generate client ID
        self.client_id = f"hydros_node_{int(time.time() * 1000)}"

        # Initialize state manager
        if state_manager is None:
            state_manager = AgentStateManager()
        self.state_manager = state_manager

        # Initialize message filter
        self.message_filter = MessageFilter(self.state_manager)

        # Initialize MQTT client
        self.mqtt_client = _create_mqtt_client(self.client_id)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        # Configure automatic reconnect with exponential backoff
        # min_delay=1s, max_delay=120s (doubles each attempt: 1, 2, 4, 8, ... 120)
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)

        # Set MQTT authentication if credentials provided
        if mqtt_username:
            self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
            logger.info(f"MQTT authentication configured for user: {mqtt_username}")

        # Track intentional disconnect to distinguish from unexpected ones
        self._intentional_disconnect = False

        # Outgoing message queue
        self.out_message_queue: Queue[SimCommand] = Queue()

        # Thread management
        self.running = Event()
        self.queue_thread: Optional[Thread] = None
        self.connected = Event()

        # Register command handlers
        self._register_handlers()

        logger.info(f"SimCoordinationClient initialized: client_id={self.client_id}, topic={self.topic}")

    def _register_handlers(self):
        """Register all command handlers that route to callback methods."""
        self.handlers: Dict[str, Callable[[SimCommand], None]] = {
            SIMCMD_TASK_INIT_REQUEST: self._handle_task_init,
            SIMCMD_TASK_INIT_RESPONSE: self._handle_task_init_response,
            SIMCMD_TICK_CMD_REQUEST: self._handle_tick,
            SIMCMD_TASK_TERMINATE_REQUEST: self._handle_task_terminate,
            SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST: self._handle_time_series_data_update,
            SIMCMD_TIME_SERIES_CALCULATION_REQUEST: self._handle_time_series_calculation,
            SIMCMD_AGENT_INSTANCE_STATUS_REPORT: self._handle_agent_status_report,
            SIMCMD_OUTFLOW_TIME_SERIES_REQUEST: self._handle_outflow_time_series_request,
            SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST: self._handle_outflow_time_series_data_update
        }
        logger.info(f"Registered {len(self.handlers)} command handlers")

    def start(self):
        """
        Start the coordination client.

        This will:
        1. Connect to MQTT broker
        2. Subscribe to the coordination topic
        3. Start the outgoing message queue thread
        """
        if self.running.is_set():
            logger.warning("Client already running")
            return

        logger.info(f"Starting SimCoordinationClient: {self.client_id}")

        # Connect to MQTT broker
        logger.info(f"Connecting to MQTT broker: {self.broker_url}:{self.broker_port}")
        self.mqtt_client.connect(self.broker_url, self.broker_port, keepalive=60)
        self.mqtt_client.loop_start()

        # Wait for connection
        if not self.connected.wait(timeout=10):
            raise RuntimeError("Failed to connect to MQTT broker within 10 seconds")

        # Start queue processing thread
        self.running.set()
        self.queue_thread = Thread(target=self._queue_loop, daemon=True, name="QueueThread")
        self.queue_thread.start()

        logger.info(f"SimCoordinationClient started successfully")

    def stop(self):
        """
        Stop the coordination client.

        This will:
        1. Stop the queue processing thread
        2. Disconnect from MQTT broker
        3. Clean up resources
        """
        if not self.running.is_set():
            logger.warning("Client not running")
            return

        logger.info("Stopping SimCoordinationClient...")

        # Stop queue thread
        self.running.clear()
        if self.queue_thread and self.queue_thread.is_alive():
            self.queue_thread.join(timeout=5)

        # Disconnect MQTT
        self._intentional_disconnect = True
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

        logger.info("SimCoordinationClient stopped")

    def enqueue(self, command: SimCommand):
        """
        Enqueue a command for sending.

        The command will be sent asynchronously by the queue thread.

        Args:
            command: The command to send
        """
        self.out_message_queue.put(command)
        # Use Pydantic's model_dump() to properly serialize nested models
        # logger.info(f"Enqueued command: {command.model_dump_json(indent=None)}")

    def send_command(self, command: SimCommand):
        """
        Send a command immediately (synchronous).

        Args:
            command: The command to send
        """
        self._send_with_retry(command)

    # ========================================================================
    # MQTT Callbacks
    # ========================================================================

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connection callback. Also handles auto-reconnect re-subscription."""
        rc = _reason_code_value(reason_code)
        if rc == 0:
            was_connected = self.connected.is_set()
            if was_connected:
                logger.info(f"Reconnected to MQTT broker: {self.broker_url}:{self.broker_port}")
            else:
                logger.info(f"Connected to MQTT broker: {self.broker_url}:{self.broker_port}")
            # (Re-)subscribe to topic on every connect/reconnect
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
            }
            reason = rc_reasons.get(rc, "unknown")
            logger.error(f"Failed to connect to MQTT broker, return code: {rc} ({reason})")

    def _on_disconnect(self, client, userdata, disconnect_flags=None, reason_code=0, properties=None):
        """MQTT disconnection callback."""
        if properties is None and reason_code == 0 and isinstance(disconnect_flags, int):
            reason_code = disconnect_flags
        rc = _reason_code_value(reason_code)
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
        """MQTT message received callback."""
        try:
            # Parse message
            payload_str = msg.payload.decode("utf-8")
            logger.debug(f"Received message on topic {msg.topic}: {payload_str[:200]}...")

            # Parse JSON
            data = json.loads(payload_str)
            self._log_raw_event_fields(data)
            command_type = get_command_type(data)
            if command_type not in SUPPORTED_SIM_COMMAND_TYPES:
                logger.warning("Ignoring unsupported sim command type: %s", command_type)
                return
            if self._should_ignore_raw_command(data):
                return
            envelope = SimCommandEnvelope(command=data)
            command = envelope.command

            # Apply message filters
            if not self.message_filter.should_process_message(command):
                logger.debug(f"Message filtered out: {command.command_type}, id={command.command_id}")
                return

            # Route to handler
            self._handle_incoming_message(command)

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    def _should_ignore_raw_command(self, data: Dict) -> bool:
        """Ignore coordination messages for agent types not hosted in this process."""
        if not isinstance(data, dict):
            return False

        command_type = data.get("command_type")
        if command_type != SIMCMD_TASK_INIT_RESPONSE:
            return False

        callback = self.sim_coordination_callback
        local_agent_codes = set(getattr(callback, "agent_factories", {}).keys())
        if not local_agent_codes:
            return False

        source_agent = data.get("source_agent_instance")
        if not isinstance(source_agent, dict):
            return False

        source_agent_code = source_agent.get("agent_code")
        if source_agent_code in local_agent_codes:
            return False

        logger.info(
            "Ignoring task_init_response for non-local agent: agent_code=%s, local_agent_codes=%s, command_id=%s",
            source_agent_code,
            sorted(local_agent_codes),
            data.get("command_id"),
        )
        return True

    def _log_raw_event_fields(self, data: Dict) -> None:
        """打印时间序列类消息的原始事件字段，便于排查字段丢失问题。"""
        if not isinstance(data, dict):
            return

        command_type = data.get("command_type")
        event_key = None
        if command_type == SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST:
            event_key = "time_series_data_changed_event"
        elif command_type == SIMCMD_TIME_SERIES_CALCULATION_REQUEST:
            event_key = "hydro_event"

        if not event_key:
            return

        raw_event = data.get(event_key)
        if not isinstance(raw_event, dict):
            logger.info(
                "原始事件字段检查：command_type=%s，event_key=%s，raw_event_type=%s",
                command_type,
                event_key,
                type(raw_event).__name__,
            )
            return

        raw_keys = sorted(raw_event.keys())
        logger.info(
            "原始事件字段检查：command_type=%s，event_key=%s，keys=%s，time_series_url=%s，event_content_url=%s，direct_load_time_series=%s",
            command_type,
            event_key,
            raw_keys,
            raw_event.get("time_series_url"),
            raw_event.get("event_content_url"),
            raw_event.get("direct_load_time_series"),
        )

    # ========================================================================
    # Message Handling
    # ========================================================================

    def _set_logging_context(self, command: SimCommand):
        """
        Set logging context from command for structured logging.

        Extracts context information from the command and sets it in the logging
        context so all subsequent logs will include this information.

        The logging context includes:
        - hydros_cluster_id: From state_manager (loaded from env.properties)
        - hydros_node_id: From state_manager (loaded from env.properties)
        - biz_scene_instance_id: From command's SimulationContext
        - biz_component: Agent ID or component name (e.g., "SIM_COORDINATOR")

        Args:
            command: The command to extract context from
        """
        # Set hydros_cluster_id from state_manager
        cluster_id = self.state_manager.get_cluster_id()
        if cluster_id:
            set_hydros_cluster_id(cluster_id)

        # Set hydros_node_id from state_manager
        node_id = self.state_manager.get_node_id()
        if node_id:
            set_hydros_node_id(node_id)

        # Set biz_scene_instance_id from command's context (SimulationContext)
        if hasattr(command, 'context') and command.context:
            biz_scene_instance_id = command.context.biz_scene_instance_id
            if biz_scene_instance_id:
                set_biz_scene_instance_id(biz_scene_instance_id)

        # Set biz_component from callback's component
        # This will be agent_id in agent context, or component name in infrastructure
        component = self.sim_coordination_callback.get_component()
        if component:
            set_biz_component(component)

    def _handle_incoming_message(self, command: SimCommand):
        """
        Handle an incoming command by routing it to the appropriate handler.

        Automatically sets logging context (task_id, biz_component, node_id) before
        calling the handler, so all logs within the handler will include this context.

        Args:
            command: The command to handle
        """
        # Set logging context from command
        self._set_logging_context(command)

        handler = self.handlers.get(command.command_type)
        if handler:
            try:
                logger.debug(f"Handling command: {command.command_type}, id={command.command_id}")
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
        Send callback return values through the normal outgoing queue.

        This keeps the existing side-effect style callbacks working while also
        supporting the simpler pattern of returning a response from callbacks.
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
        Convert uncaught handler exceptions into failed responses when possible.

        Some request types, especially task init before an agent exists, may not
        have enough local agent context to satisfy the protocol's required
        source_agent_instance field. In that case we log and leave the exception
        as an infrastructure error rather than fabricating an invalid response.
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
        """Find a local agent instance suitable as source_agent_instance."""
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
    # Command Handlers (route to callback)
    # ========================================================================

    def _handle_task_init(self, command: SimCommand):
        """Handle task init request."""
        request = command
        assert isinstance(request, SimTaskInitRequest)
        return self.sim_coordination_callback.on_sim_task_init(request)

    def _handle_task_init_response(self, command: SimCommand):
        """Handle task init response from remote agent."""
        response = command
        assert isinstance(response, SimTaskInitResponse)
        if self.sim_coordination_callback.is_remote_agent(response.source_agent_instance):
            return self.sim_coordination_callback.on_agent_instance_sibling_created(response)
        return None

    def _handle_tick(self, command: SimCommand):
        """Handle tick command."""
        request = command
        assert isinstance(request, TickCmdRequest)
        return self.sim_coordination_callback.on_tick(request)

    def _handle_task_terminate(self, command: SimCommand):
        """Handle task terminate request."""
        request = command
        assert isinstance(request, SimTaskTerminateRequest)
        return self.sim_coordination_callback.on_task_terminate(request)

    def _handle_time_series_data_update(self, command: SimCommand):
        """Handle time series data update."""
        request = command
        assert isinstance(request, TimeSeriesDataUpdateRequest)
        return self.sim_coordination_callback.on_time_series_data_update(request)

    def _handle_outflow_time_series_data_update(self, command: SimCommand):
        """Handle outflow time series data update."""
        request = command
        assert isinstance(request, OutflowTimeSeriesDataUpdateRequest)
        self.sim_coordination_callback.on_outflow_time_series_data_update(request)

    def _handle_time_series_calculation(self, command: SimCommand):
        """Handle time series calculation."""
        request = command
        assert isinstance(request, TimeSeriesCalculationRequest)
        return self.sim_coordination_callback.on_time_series_calculation(request)

    def _handle_agent_status_report(self, command: SimCommand):
        """Handle agent status report from remote agent."""
        report = command
        assert isinstance(report, AgentInstanceStatusReport)
        if self.sim_coordination_callback.is_remote_agent(report.source_agent_instance):
            return self.sim_coordination_callback.on_agent_instance_sibling_status_updated(report)
        return None

    def _handle_outflow_time_series_request(self, command: SimCommand):
        """Handle outflow time series request."""
        request = command
        assert isinstance(request, OutflowTimeSeriesRequest)
        return self.sim_coordination_callback.on_outflow_time_series(request)

    # ========================================================================
    # Outgoing Message Queue
    # ========================================================================

    def _queue_loop(self):
        """
        Main loop for processing outgoing message queue.

        This runs in a separate thread and sends messages with retry logic.
        """
        logger.info("Queue processing thread started")
        while self.running.is_set():
            try:
                # Get next command from queue (with timeout to allow checking running flag)
                command = self.out_message_queue.get(timeout=1)

                # Check if message should be sent
                if self._should_send(command):
                    self._send_with_retry(command)

            except Empty:
                # Timeout, continue loop
                continue
            except Exception as e:
                logger.error(f"Error in queue loop: {e}", exc_info=True)

        logger.info("Queue processing thread stopped")

    def _should_send(self, command: SimCommand) -> bool:
        """
        Check if a command should be sent.

        Similar to Java's needSend() method.

        Args:
            command: The command to check

        Returns:
            True if the command should be sent, False otherwise
        """
        # Don't send requests (only responses and reports)
        if isinstance(command, SimCoordinationRequest):
            return False

        # Send responses only from local agents
        if isinstance(command, SimCoordinationResponse):
            if isinstance(command, SimTaskTerminateResponse):
                node_id = self.state_manager.get_node_id()
                if node_id and command.source_agent_instance.hydros_node_id == node_id:
                    return True
            return self.state_manager.is_local_agent(command.source_agent_instance)

        # Send reports only from local agents
        if isinstance(command, AgentInstanceStatusReport):
            return self.state_manager.is_local_agent(command.source_agent_instance)

        return False

    def _send_with_retry(self, command: SimCommand):
        """
        Send a command with retry logic.

        Similar to Java's sendAsyncWithRetry() method.

        Args:
            command: The command to send
        """
        attempt = 0
        command_id = command.command_id

        while attempt <= self.max_retry_count:
            try:
                # Serialize command
                payload = command.model_dump_json(by_alias=True)
                if command.command_type in {SIMCMD_TASK_INIT_RESPONSE, SIMCMD_TASK_TERMINATE_RESPONSE}:
                    logger.info("Outgoing %s payload: %s", command.command_type, payload)

                # Publish to MQTT
                result = self.mqtt_client.publish(self.topic, payload, qos=self.qos)
                result.wait_for_publish()

                logger.info(f"Command sent: type={command.command_type}, id={command_id}, attempt={attempt}")
                return  # Success

            except Exception as e:
                logger.error(f"Failed to send command: id={command_id}, attempt={attempt}/{self.max_retry_count}: {e}")

                attempt += 1
                if attempt > self.max_retry_count:
                    logger.error(f"Max retry count exceeded for command: id={command_id}")
                    raise

                # Exponential backoff: 2^attempt * base_delay
                delay_ms = self.base_retry_delay_ms * (2 ** attempt)
                logger.info(f"Retrying after {delay_ms}ms... (attempt {attempt}/{self.max_retry_count})")
                time.sleep(delay_ms / 1000.0)
