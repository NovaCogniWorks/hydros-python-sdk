"""
用于 agent command 的 MQTT 传输客户端。
"""

from __future__ import annotations

import json
import logging
import time
from threading import Event
from typing import Callable, Optional, Sequence

import paho.mqtt.client as mqtt

from hydros_agent_sdk.protocol.models import CommandStatus
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.topics import HydrosTopics

from hydros_agent_sdk.agent_commands.models import AgentCommand, AgentCommandEnvelope
from hydros_agent_sdk.agent_commands.persistence import AgentCommandLogStore
from hydros_agent_sdk.agent_commands.runtime import AgentCommandRuntime

logger = logging.getLogger(__name__)


class AgentCommandClient:
    """先给第一版最小可用的 agent command 客户端。"""

    def __init__(
        self,
        broker_url: str,
        broker_port: int,
        topic: Optional[str] = None,
        hydros_cluster_id: Optional[str] = None,
        state_manager: Optional[AgentStateManager] = None,
        qos: int = 1,
        max_retry_count: int = 5,
        base_retry_delay_ms: int = 1000,
        mqtt_username: Optional[str] = None,
        mqtt_password: Optional[str] = None,
        handler_registry=None,
        log_store: Optional[AgentCommandLogStore] = None,
        sqlite_log_db_path: Optional[str] = None,
        use_sqlite_log_store: bool = False,
        pending_command_predicate: Optional[Callable[[AgentCommand], bool]] = None,
        pending_retry_delay_ms: int = 50,
        max_workers: int = 8,
    ):
        self.broker_url = broker_url.replace("tcp://", "")
        self.broker_port = broker_port
        if topic:
            self.topic = topic
        elif hydros_cluster_id:
            self.topic = HydrosTopics.get_agent_command_topic(hydros_cluster_id)
        else:
            raise ValueError("topic 和 hydros_cluster_id 不能同时为空")
        self.qos = qos
        self.max_retry_count = max_retry_count
        self.base_retry_delay_ms = base_retry_delay_ms
        self.client_id = f"hydros_agent_cmd_{int(time.time() * 1000)}"

        if state_manager is None:
            state_manager = AgentStateManager()
        self.state_manager = state_manager

        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
        )
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)

        if mqtt_username:
            self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)

        self.runtime = AgentCommandRuntime(
            state_manager=self.state_manager,
            sender=self._send_with_retry,
            handler_registry=handler_registry,
            log_store=log_store,
            sqlite_log_db_path=sqlite_log_db_path,
            use_sqlite_log_store=use_sqlite_log_store,
            pending_command_predicate=pending_command_predicate,
            pending_retry_delay_ms=pending_retry_delay_ms,
            max_workers=max_workers,
        )

        self._connected = Event()
        self._intentional_disconnect = False

    def start(self) -> None:
        self._intentional_disconnect = False
        self.mqtt_client.connect(self.broker_url, self.broker_port, keepalive=60)
        self.mqtt_client.loop_start()
        try:
            if not self._connected.wait(timeout=10):
                raise RuntimeError("AgentCommandClient 连接 MQTT 超时")
            self.runtime.start()
        except Exception:
            self._intentional_disconnect = True
            self.mqtt_client.loop_stop()
            try:
                self.mqtt_client.disconnect()
            except Exception:
                logger.debug("清理 MQTT 连接失败", exc_info=True)
            raise

    def stop(self) -> None:
        self.runtime.stop()
        self._intentional_disconnect = True
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def register_handler(self, handler) -> None:
        self.runtime.register_handler(handler)

    def send_command(self, command: AgentCommand) -> None:
        self.runtime.send_command(command)

    def set_pending_command_predicate(
        self,
        predicate: Optional[Callable[[AgentCommand], bool]],
    ) -> None:
        self.runtime.set_pending_command_predicate(predicate)

    def find_unreported_command_logs(self, limit: int = 100):
        return self.runtime.find_unreported_command_logs(limit=limit)

    def report_unreported_command_logs(self, consumer, limit: int = 100):
        return self.runtime.report_unreported_command_logs(consumer=consumer, limit=limit)

    def find_unacked_command_logs(self, limit: int = 100):
        return self.runtime.find_unacked_command_logs(limit=limit)

    def find_incomplete_command_logs(
        self,
        statuses: Optional[Sequence[CommandStatus]] = None,
        limit: int = 100,
    ):
        return self.runtime.find_incomplete_command_logs(statuses=statuses, limit=limit)

    def replay_incomplete_requests(
        self,
        statuses: Sequence[CommandStatus] = (CommandStatus.INIT,),
        limit: int = 100,
    ):
        return self.runtime.replay_incomplete_requests(statuses=statuses, limit=limit)

    def collect_command_log_snapshot(
        self,
        limit: int = 100,
        incomplete_statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
    ):
        return self.runtime.collect_command_log_snapshot(
            limit=limit,
            incomplete_statuses=incomplete_statuses,
        )

    def collect_command_log_stats(
        self,
        limit: int = 100,
        incomplete_statuses: Sequence[CommandStatus] = (CommandStatus.INIT, CommandStatus.PROCESSING),
    ):
        return self.runtime.collect_command_log_stats(
            limit=limit,
            incomplete_statuses=incomplete_statuses,
        )

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        rc = reason_code.value
        if rc == 0:
            self.mqtt_client.subscribe(self.topic, qos=self.qos)
            self._connected.set()
            logger.info("AgentCommandClient 已连接 MQTT 并订阅 topic=%s", self.topic)
            return
        logger.error("AgentCommandClient 连接 MQTT 失败: rc=%s", rc)

    def _on_disconnect(self, client, userdata, disconnect_flags=None, reason_code=0, properties=None) -> None:
        rc = reason_code.value
        self._connected.clear()
        if rc == 0 or self._intentional_disconnect:
            logger.info("AgentCommandClient 已断开 MQTT")
            return
        logger.warning("AgentCommandClient MQTT 意外断开: rc=%s", rc)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload_str = msg.payload.decode("utf-8")
            payload = json.loads(payload_str)
            envelope = AgentCommandEnvelope(command=payload)
            self.runtime.handle_incoming_command(envelope.command)
        except Exception as exc:
            logger.error("处理 agent command 消息失败: %s", exc, exc_info=True)

    def _send_with_retry(self, command: AgentCommand) -> None:
        attempt = 0
        while attempt <= self.max_retry_count:
            try:
                payload = command.model_dump_json(by_alias=True)
                result = self.mqtt_client.publish(self.topic, payload, qos=self.qos)
                result.wait_for_publish()
                logger.info("Agent command 已发送: type=%s id=%s attempt=%s", command.command_type, command.command_id, attempt)
                return
            except Exception:
                attempt += 1
                logger.error(
                    "发送 agent command 失败: type=%s id=%s attempt=%s/%s",
                    command.command_type,
                    command.command_id,
                    attempt,
                    self.max_retry_count,
                    exc_info=True,
                )
                if attempt > self.max_retry_count:
                    raise
                time.sleep((self.base_retry_delay_ms * (2 ** attempt)) / 1000.0)
