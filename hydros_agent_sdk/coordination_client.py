"""
Simulation coordination client with callback-based architecture.

This module provides a high-level client that encapsulates all common MQTT logic,
allowing developers to focus on business logic by implementing callbacks.

Similar to Java's SimCoordinationSlave class.
"""

import logging
import time
from typing import Optional, Dict, Callable
from queue import Queue, Empty
from threading import Thread, Event
import paho.mqtt.client as mqtt

from hydros_agent_sdk.callback import SimCoordinationCallback
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.message_filter import MessageFilter
from hydros_agent_sdk.protocol.commands import (
    SimCommand,
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
    SimCoordinationRequest,
    SimCoordinationResponse,
    SimCommandEnvelope,
    # Command type constants
    SIMCMD_TASK_INIT_REQUEST,
    SIMCMD_TASK_INIT_RESPONSE,
    SIMCMD_TICK_CMD_REQUEST,
    SIMCMD_TASK_TERMINATE_REQUEST,
    SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST,
    SIMCMD_TIME_SERIES_CALCULATION_REQUEST,
    SIMCMD_AGENT_INSTANCE_STATUS_REPORT,
)
import json

logger = logging.getLogger(__name__)


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
            def get_component(self):
                return "MY_AGENT"

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
        topic: str,
        callback: SimCoordinationCallback,
        client_id: Optional[str] = None,
        state_manager: Optional[AgentStateManager] = None,
        qos: int = 1,
        max_retry_count: int = 5,
        base_retry_delay_ms: int = 1000
    ):
        """
        Initialize the coordination client.

        Args:
            broker_url: MQTT broker URL (e.g., "tcp://192.168.1.24")
            broker_port: MQTT broker port (default: 1883)
            topic: MQTT topic to subscribe to
            callback: SimCoordinationCallback implementation
            client_id: Optional MQTT client ID (auto-generated if not provided)
            state_manager: Optional state manager (created if not provided)
            qos: MQTT QoS level (default: 1)
            max_retry_count: Maximum retry count for sending messages (default: 5)
            base_retry_delay_ms: Base retry delay in milliseconds (default: 1000)
        """
        self.broker_url = broker_url.replace("tcp://", "")
        self.broker_port = broker_port
        self.topic = topic
        self.callback = callback
        self.qos = qos
        self.max_retry_count = max_retry_count
        self.base_retry_delay_ms = base_retry_delay_ms

        # Generate client ID if not provided
        if client_id is None:
            component = callback.get_component()
            client_id = f"hydros_{component}_{int(time.time() * 1000)}"
        self.client_id = client_id

        # Initialize state manager
        if state_manager is None:
            state_manager = AgentStateManager()
        self.state_manager = state_manager

        # Initialize message filter
        self.message_filter = MessageFilter(self.state_manager)

        # Initialize MQTT client
        self.mqtt_client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

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
        logger.info(f"Enqueued command: {command}")

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

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback."""
        if rc == 0:
            logger.info(f"Connected to MQTT broker: {self.broker_url}:{self.broker_port}")
            # Subscribe to topic
            self.mqtt_client.subscribe(self.topic, qos=self.qos)
            logger.info(f"Subscribed to topic: {self.topic}")
            self.connected.set()
        else:
            logger.error(f"Failed to connect to MQTT broker, return code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback."""
        logger.info(f"Disconnected from MQTT broker, return code: {rc}")
        self.connected.clear()

    def _on_message(self, client, userdata, msg):
        """MQTT message received callback."""
        try:
            # Parse message
            payload_str = msg.payload.decode("utf-8")
            logger.debug(f"Received message on topic {msg.topic}: {payload_str[:200]}...")

            # Parse JSON
            data = json.loads(payload_str)
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

    # ========================================================================
    # Message Handling
    # ========================================================================

    def _handle_incoming_message(self, command: SimCommand):
        """
        Handle an incoming command by routing it to the appropriate handler.

        Args:
            command: The command to handle
        """
        handler = self.handlers.get(command.command_type)
        if handler:
            try:
                logger.debug(f"Handling command: {command.command_type}, id={command.command_id}")
                handler(command)
            except Exception as e:
                logger.error(f"Error handling command {command.command_type}: {e}", exc_info=True)
        else:
            logger.warning(f"No handler registered for command type: {command.command_type}")

    # ========================================================================
    # Command Handlers (route to callback)
    # ========================================================================

    def _handle_task_init(self, command: SimCommand):
        """Handle task init request."""
        request = command
        assert isinstance(request, SimTaskInitRequest)
        self.callback.on_sim_task_init(request)

    def _handle_task_init_response(self, command: SimCommand):
        """Handle task init response from remote agent."""
        response = command
        assert isinstance(response, SimTaskInitResponse)
        if self.callback.is_remote_agent(response.source_agent_instance):
            self.callback.on_agent_instance_sibling_created(response)

    def _handle_tick(self, command: SimCommand):
        """Handle tick command."""
        request = command
        assert isinstance(request, TickCmdRequest)
        self.callback.on_tick(request)

    def _handle_task_terminate(self, command: SimCommand):
        """Handle task terminate request."""
        request = command
        assert isinstance(request, SimTaskTerminateRequest)
        self.callback.on_task_terminate(request)

    def _handle_time_series_data_update(self, command: SimCommand):
        """Handle time series data update."""
        request = command
        assert isinstance(request, TimeSeriesDataUpdateRequest)
        self.callback.on_time_series_data_update(request)

    def _handle_time_series_calculation(self, command: SimCommand):
        """Handle time series calculation."""
        request = command
        assert isinstance(request, TimeSeriesCalculationRequest)
        self.callback.on_time_series_calculation(request)

    def _handle_agent_status_report(self, command: SimCommand):
        """Handle agent status report from remote agent."""
        report = command
        assert isinstance(report, AgentInstanceStatusReport)
        if self.callback.is_remote_agent(report.source_agent_instance):
            self.callback.on_agent_instance_sibling_status_updated(report)

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
