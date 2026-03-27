"""Outgoing message queue and retry handling for SimCoordinationClient."""

import logging
import time
from queue import Empty

from hydros_agent_sdk.protocol.commands import (
    AgentInstanceStatusReport,
    SimCoordinationRequest,
    SimCoordinationResponse,
)

logger = logging.getLogger(__name__)


class OutboundCommandSender:
    """Encapsulates outgoing queue filtering and MQTT publish retry."""

    def __init__(self, mqtt_client, topic: str, qos: int, state_manager, max_retry_count: int, base_retry_delay_ms: int):
        self.mqtt_client = mqtt_client
        self.topic = topic
        self.qos = qos
        self.state_manager = state_manager
        self.max_retry_count = max_retry_count
        self.base_retry_delay_ms = base_retry_delay_ms

    def queue_loop(self, running_event, out_message_queue) -> None:
        logger.info('Queue processing thread started')
        while running_event.is_set():
            try:
                command = out_message_queue.get(timeout=1)
                if self.should_send(command):
                    self.send_with_retry(command)
            except Empty:
                continue
            except Exception as exc:
                logger.error(f"Error in queue loop: {exc}", exc_info=True)
        logger.info('Queue processing thread stopped')

    def should_send(self, command) -> bool:
        if isinstance(command, SimCoordinationRequest):
            return False

        if isinstance(command, SimCoordinationResponse):
            return self.state_manager.is_local_agent(command.source_agent_instance)

        if isinstance(command, AgentInstanceStatusReport):
            return self.state_manager.is_local_agent(command.source_agent_instance)

        return False

    def send_with_retry(self, command) -> None:
        attempt = 0
        command_id = command.command_id

        while attempt <= self.max_retry_count:
            try:
                payload = command.model_dump_json(by_alias=True)
                result = self.mqtt_client.publish(self.topic, payload, qos=self.qos)
                result.wait_for_publish()
                logger.info(f"Command sent: type={command.command_type}, id={command_id}, attempt={attempt}")
                return
            except Exception as exc:
                logger.error(
                    f"Failed to send command: id={command_id}, attempt={attempt}/{self.max_retry_count}: {exc}"
                )
                attempt += 1
                if attempt > self.max_retry_count:
                    logger.error(f"Max retry count exceeded for command: id={command_id}")
                    raise

                delay_ms = self.base_retry_delay_ms * (2 ** attempt)
                logger.info(f"Retrying after {delay_ms}ms... (attempt {attempt}/{self.max_retry_count})")
                time.sleep(delay_ms / 1000.0)
