"""MQTT transport for coordination commands."""

from __future__ import annotations

import logging
import socket
from threading import Event
from typing import Optional

import paho.mqtt.client as mqtt

from .base import MessageHandler


logger = logging.getLogger(__name__)


class MqttCoordinationTransport:
    """Own Paho lifecycle, one coordination subscription and MQTT publishing."""

    def __init__(
        self,
        broker_url: str,
        broker_port: int,
        client_id: str,
        topic: str,
        handler: MessageHandler,
        qos: int = 1,
        mqtt_username: Optional[str] = None,
        mqtt_password: Optional[str] = None,
    ) -> None:
        self.broker_url = broker_url.replace("tcp://", "")
        self.broker_port = broker_port
        self.client_id = client_id
        self.topic = topic
        self.handler = handler
        self.qos = qos
        self.connected = Event()
        self._intentional_disconnect = False
        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)
        if mqtt_username:
            self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)

    def start(self) -> None:
        self._intentional_disconnect = False
        try:
            self.mqtt_client.connect(self.broker_url, self.broker_port, keepalive=60)
            self.mqtt_client.loop_start()
        except (OSError, socket.gaierror) as error:
            raise RuntimeError(self.connection_failure_message(error)) from error
        if not self.connected.wait(timeout=10):
            self.stop()
            raise RuntimeError(self.connection_failure_message("connection acknowledgement timed out after 10 seconds"))

    def stop(self) -> None:
        self._intentional_disconnect = True
        try:
            self.mqtt_client.loop_stop()
        finally:
            self.mqtt_client.disconnect()

    def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        result = self.mqtt_client.publish(topic, payload, qos=qos)
        result.wait_for_publish()

    def connection_failure_message(self, cause) -> str:
        return (
            f"Failed to connect to MQTT broker {self.broker_url}:{self.broker_port} "
            f"for topic {self.topic}: {cause}. Check env.properties, DNS and network reachability."
        )

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code.value != 0:
            logger.error("Failed to connect to MQTT broker: rc=%s", reason_code.value)
            return
        self.mqtt_client.subscribe(self.topic, qos=self.qos)
        self.connected.set()
        logger.info("Coordination MQTT connected and subscribed: topic=%s", self.topic)

    def _on_disconnect(self, _client, _userdata, _disconnect_flags=None, reason_code=0, _properties=None) -> None:
        self.connected.clear()
        if reason_code.value == 0 or self._intentional_disconnect:
            logger.info("Coordination MQTT disconnected cleanly")
        else:
            logger.warning("Coordination MQTT disconnected unexpectedly: rc=%s", reason_code.value)

    def _on_message(self, _client, _userdata, message) -> None:
        self.handler(message.topic, message.payload.decode("utf-8"))
