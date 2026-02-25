import json
import logging
from typing import Callable, Dict, Any, Type, Optional
import paho.mqtt.client as mqtt
from pydantic import ValidationError

from hydros_agent_sdk.protocol.commands import SimCommandEnvelope, HydroCmd, SimCommand
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.message_filter import MessageFilter

logger = logging.getLogger(__name__)

# Callback type definition: function that takes a HydroCmd (or subclass) and returns nothing or a response
CommandHandler = Callable[[HydroCmd], Any]

class CommandDispatcher:
    def __init__(self, message_filter: Optional[MessageFilter] = None):
        self._handlers: Dict[str, CommandHandler] = {}
        self._message_filter = message_filter

    def register_handler(self, command_type: str, handler: CommandHandler):
        """
        Register a handler function for a specific command type.
        """
        self._handlers[command_type] = handler
        logger.info(f"Registered handler for command type: {command_type}")

    def set_message_filter(self, message_filter: MessageFilter):
        """
        Set the message filter for filtering incoming commands.

        Args:
            message_filter: The MessageFilter instance to use
        """
        self._message_filter = message_filter
        logger.info("Message filter configured for dispatcher")

    def dispatch(self, payload: bytes) -> Any:
        """
        Parse the payload and dispatch to the appropriate handler.

        Implements message filtering logic similar to Java's SimCoordinationSlave.messageArrived():
        1. Parse the command
        2. Apply message filters (isActiveToTaskSimCommand, isReceived)
        3. Dispatch to handler if filters pass
        """
        try:
            # decode bytes to string
            payload_str = payload.decode("utf-8")
            logger.debug(f"Received payload: {payload_str[:200]}...")  # Log first 200 chars

            # Parse JSON
            data = json.loads(payload_str)

            # Use Pydantic to parse into the correct object type using the Discriminated Union
            envelope = SimCommandEnvelope(command=data)
            command_obj = envelope.command

            # Apply message filter if configured
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

        # Initialize state manager if not provided
        if state_manager is None:
            state_manager = AgentStateManager()
        self.state_manager = state_manager

        # Initialize dispatcher if not provided
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
        Connect to the MQTT broker.

        Args:
            broker_url: MQTT broker URL (e.g., "tcp://192.168.1.24")
            port: MQTT broker port (default: 1883)
            keepalive: Keepalive interval in seconds (default: 60)
            username: Optional MQTT username for authentication (None for no auth)
            password: Optional MQTT password for authentication (None for no auth)
        """
        logger.info(f"Connecting to MQTT broker at {broker_url}:{port}")
        # Parse broker_url to handle tcp:// prefix if present
        host = broker_url.replace("tcp://", "")

        # Set authentication if credentials provided
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
        Subscribe to a topic.
        """
        logger.info(f"Subscribing to topic: {topic}")
        self.client.subscribe(topic)

    def publish_command(self, topic: str, command: HydroCmd):
        """
        Serialize and publish a command/response object to a topic.
        """
        try:
            # model_dump_json for pydantic v2
            payload = command.model_dump_json(by_alias=True)
            logger.info(f"Publishing to {topic}: {payload}")
            self.client.publish(topic, payload)
        except Exception as e:
            logger.error(f"Failed to publish command: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        _ = client, userdata, flags  # Mark as intentionally unused
        if rc == 0:
            logger.info("Connected to MQTT broker successfully")
            self._connected = True
        else:
            logger.error(f"Failed to connect to MQTT broker, return code: {rc}")

    def _on_message(self, client, userdata, msg):
        _ = client, userdata  # Mark as intentionally unused
        logger.debug(f"Received message on topic {msg.topic}")
        # Dispatch the message to the registered handlers
        response = self.dispatcher.dispatch(msg.payload)
        
        # NOTE: If we need to send the response back, the handler or this method needs know the reply topic.
        # For now, we assume the handler handles any necessary response logic or returns a response object
        # that we might want to publish. 
        # The requirements mentioned "return response via MQTT". 
        # Typically the request would have a 'reply-to' field or we publish to a convention-based topic.
        # Since the interface didn't specify, I will leave the publishing of the response to the caller/handler 
        # or extend this if the return value is a HydroCmd.
        
        if isinstance(response, HydroCmd):
            # Optimistically try to publish response to a default topic? 
            # Or assume the caller handles it. 
            # In Distributed RPC, usually we need a reply topic.
            # Assuming the Stub/Business logic handles the reply publishing for now, 
            # or we can add a 'reply_topic' arg to dispatch.
            pass
