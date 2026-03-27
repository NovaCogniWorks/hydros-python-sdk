"""MQTT connection lifecycle management for SimCoordinationClient."""

import logging
from threading import Event

logger = logging.getLogger(__name__)


class MqttConnectionManager:
    """Owns MQTT loop start/stop and connection waiting behavior."""

    def __init__(self, mqtt_client, broker_host: str, broker_port: int, connected_event: Event):
        self.mqtt_client = mqtt_client
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.connected_event = connected_event
        self._intentional_disconnect = False

    @property
    def intentional_disconnect(self) -> bool:
        return self._intentional_disconnect

    def start(self, timeout: int = 10) -> None:
        logger.info(f"Connecting to MQTT broker: {self.broker_host}:{self.broker_port}")
        self.mqtt_client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.mqtt_client.loop_start()
        if not self.connected_event.wait(timeout=timeout):
            raise RuntimeError(f"Failed to connect to MQTT broker within {timeout} seconds")

    def stop(self) -> None:
        self._intentional_disconnect = True
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
