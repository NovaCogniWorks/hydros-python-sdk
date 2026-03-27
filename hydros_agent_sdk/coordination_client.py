"""
Simulation coordination client with callback-based architecture.

This module provides a high-level client that encapsulates all common MQTT logic,
allowing developers to focus on business logic by implementing callbacks.

Similar to Java's SimCoordinationSlave class.
"""

import json
import logging
import time
from queue import Queue
from threading import Event, Thread
from typing import Optional

import paho.mqtt.client as mqtt

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_runtime import (
    CommandRouter,
    LoggingContextBinder,
    MqttConnectionManager,
    OutboundCommandSender,
)
from hydros_agent_sdk.message_filter import MessageFilter
from hydros_agent_sdk.protocol.commands import (
    AgentInstanceStatusReport,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesRequest,
    SIMCMD_AGENT_INSTANCE_STATUS_REPORT,
    SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST,
    SIMCMD_OUTFLOW_TIME_SERIES_REQUEST,
    SIMCMD_TASK_INIT_REQUEST,
    SIMCMD_TASK_INIT_RESPONSE,
    SIMCMD_TASK_TERMINATE_REQUEST,
    SIMCMD_TICK_CMD_REQUEST,
    SIMCMD_TIME_SERIES_CALCULATION_REQUEST,
    SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST,
    SimCommand,
    SimCommandEnvelope,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    TickCmdRequest,
    TimeSeriesCalculationRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.state_manager import AgentStateManager

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
    """

    def __init__(
        self,
        broker_url: str,
        broker_port: int,
        topic: str,
        sim_coordination_callback: SimCoordinationCallback,
        state_manager: Optional[AgentStateManager] = None,
        qos: int = 1,
        max_retry_count: int = 5,
        base_retry_delay_ms: int = 1000,
        mqtt_username: Optional[str] = None,
        mqtt_password: Optional[str] = None,
    ):
        self.broker_url = broker_url.replace('tcp://', '')
        self.broker_port = broker_port
        self.topic = topic
        self.sim_coordination_callback = sim_coordination_callback
        self.qos = qos
        self.max_retry_count = max_retry_count
        self.base_retry_delay_ms = base_retry_delay_ms

        self.client_id = f"hydros_node_{int(time.time() * 1000)}"

        if state_manager is None:
            state_manager = AgentStateManager()
        self.state_manager = state_manager
        self.message_filter = MessageFilter(self.state_manager)

        self.mqtt_client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)

        if mqtt_username:
            self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
            logger.info(f"MQTT authentication configured for user: {mqtt_username}")

        self.out_message_queue: Queue[SimCommand] = Queue()
        self.running = Event()
        self.queue_thread: Optional[Thread] = None
        self.connected = Event()

        self.command_router = CommandRouter()
        self.logging_context_binder = LoggingContextBinder()
        self.connection_manager = MqttConnectionManager(
            mqtt_client=self.mqtt_client,
            broker_host=self.broker_url,
            broker_port=self.broker_port,
            connected_event=self.connected,
        )
        self.outbound_sender = OutboundCommandSender(
            mqtt_client=self.mqtt_client,
            topic=self.topic,
            qos=self.qos,
            state_manager=self.state_manager,
            max_retry_count=self.max_retry_count,
            base_retry_delay_ms=self.base_retry_delay_ms,
        )

        self._register_handlers()
        logger.info(f"SimCoordinationClient initialized: client_id={self.client_id}, topic={self.topic}")

    def _register_handlers(self):
        self.command_router.register_many({
            SIMCMD_TASK_INIT_REQUEST: self._handle_task_init,
            SIMCMD_TASK_INIT_RESPONSE: self._handle_task_init_response,
            SIMCMD_TICK_CMD_REQUEST: self._handle_tick,
            SIMCMD_TASK_TERMINATE_REQUEST: self._handle_task_terminate,
            SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST: self._handle_time_series_data_update,
            SIMCMD_TIME_SERIES_CALCULATION_REQUEST: self._handle_time_series_calculation,
            SIMCMD_AGENT_INSTANCE_STATUS_REPORT: self._handle_agent_status_report,
            SIMCMD_OUTFLOW_TIME_SERIES_REQUEST: self._handle_outflow_time_series_request,
            SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST: self._handle_outflow_time_series_data_update,
        })
        logger.info(f"Registered {len(self.command_router.handlers)} command handlers")

    def start(self):
        if self.running.is_set():
            logger.warning('Client already running')
            return

        logger.info(f"Starting SimCoordinationClient: {self.client_id}")
        self.connection_manager.start(timeout=10)

        self.running.set()
        self.queue_thread = Thread(target=self._queue_loop, daemon=True, name='QueueThread')
        self.queue_thread.start()
        logger.info('SimCoordinationClient started successfully')

    def stop(self):
        if not self.running.is_set():
            logger.warning('Client not running')
            return

        logger.info('Stopping SimCoordinationClient...')
        self.running.clear()
        if self.queue_thread and self.queue_thread.is_alive():
            self.queue_thread.join(timeout=5)

        self.connection_manager.stop()
        logger.info('SimCoordinationClient stopped')

    def enqueue(self, command: SimCommand):
        self.out_message_queue.put(command)
        logger.info(f"Enqueued command: {command.model_dump_json(indent=None)}")

    def send_command(self, command: SimCommand):
        self.outbound_sender.send_with_retry(command)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            was_connected = self.connected.is_set()
            if was_connected:
                logger.info(f"Reconnected to MQTT broker: {self.broker_url}:{self.broker_port}")
            else:
                logger.info(f"Connected to MQTT broker: {self.broker_url}:{self.broker_port}")
            self.mqtt_client.subscribe(self.topic, qos=self.qos)
            logger.info(f"Subscribed to topic: {self.topic}")
            self.connected.set()
        else:
            rc_reasons = {
                1: 'incorrect protocol version',
                2: 'invalid client identifier',
                3: 'server unavailable',
                4: 'bad username or password',
                5: 'not authorized',
            }
            reason = rc_reasons.get(rc, 'unknown')
            logger.error(f"Failed to connect to MQTT broker, return code: {rc} ({reason})")

    def _on_disconnect(self, client, userdata, rc):
        self.connected.clear()
        if rc == 0 or self.connection_manager.intentional_disconnect:
            logger.info('Disconnected from MQTT broker (clean)')
        else:
            rc_reasons = {
                1: 'unexpected disconnect',
                7: 'connection lost (keepalive timeout or broker idle disconnect)',
            }
            reason = rc_reasons.get(rc, f'unexpected, code={rc}')
            logger.warning(f"Disconnected from MQTT broker: {reason}. Auto-reconnecting...")

    def _on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode('utf-8')
            logger.debug(f"Received message on topic {msg.topic}: {payload_str[:200]}...")
            data = json.loads(payload_str)
            envelope = SimCommandEnvelope(command=data)
            command = envelope.command

            if not self.message_filter.should_process_message(command):
                logger.debug(f"Message filtered out: {command.command_type}, id={command.command_id}")
                return

            self._handle_incoming_message(command)
        except Exception as exc:
            logger.error(f"Error processing message: {exc}", exc_info=True)

    def _set_logging_context(self, command: SimCommand):
        self.logging_context_binder.bind(
            command=command,
            state_manager=self.state_manager,
            callback=self.sim_coordination_callback,
        )

    def _handle_incoming_message(self, command: SimCommand):
        self._set_logging_context(command)
        try:
            self.command_router.route(command)
        except Exception as exc:
            logger.error(f"Error handling command {command.command_type}: {exc}", exc_info=True)

    def _handle_task_init(self, command: SimCommand):
        request = command
        assert isinstance(request, SimTaskInitRequest)
        self.sim_coordination_callback.on_sim_task_init(request)

    def _handle_task_init_response(self, command: SimCommand):
        response = command
        assert isinstance(response, SimTaskInitResponse)
        if self.sim_coordination_callback.is_remote_agent(response.source_agent_instance):
            self.sim_coordination_callback.on_agent_instance_sibling_created(response)

    def _handle_tick(self, command: SimCommand):
        request = command
        assert isinstance(request, TickCmdRequest)
        self.sim_coordination_callback.on_tick(request)

    def _handle_task_terminate(self, command: SimCommand):
        request = command
        assert isinstance(request, SimTaskTerminateRequest)
        self.sim_coordination_callback.on_task_terminate(request)

    def _handle_time_series_data_update(self, command: SimCommand):
        request = command
        assert isinstance(request, TimeSeriesDataUpdateRequest)
        self.sim_coordination_callback.on_time_series_data_update(request)

    def _handle_outflow_time_series_data_update(self, command: SimCommand):
        request = command
        assert isinstance(request, OutflowTimeSeriesDataUpdateRequest)
        self.sim_coordination_callback.on_outflow_time_series_data_update(request)

    def _handle_time_series_calculation(self, command: SimCommand):
        request = command
        assert isinstance(request, TimeSeriesCalculationRequest)
        self.sim_coordination_callback.on_time_series_calculation(request)

    def _handle_agent_status_report(self, command: SimCommand):
        report = command
        assert isinstance(report, AgentInstanceStatusReport)
        if self.sim_coordination_callback.is_remote_agent(report.source_agent_instance):
            self.sim_coordination_callback.on_agent_instance_sibling_status_updated(report)

    def _handle_outflow_time_series_request(self, command: SimCommand):
        request = command
        assert isinstance(request, OutflowTimeSeriesRequest)
        self.sim_coordination_callback.on_outflow_time_series(request)

    def _queue_loop(self):
        self.outbound_sender.queue_loop(
            running_event=self.running,
            out_message_queue=self.out_message_queue,
        )

    def _should_send(self, command: SimCommand) -> bool:
        return self.outbound_sender.should_send(command)

    def _send_with_retry(self, command: SimCommand):
        self.outbound_sender.send_with_retry(command)
