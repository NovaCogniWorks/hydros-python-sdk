"""Agent command adapter over the shared coordination transport."""

from __future__ import annotations

import json
import logging
import time
from typing import Callable, Optional, TYPE_CHECKING

from hydros_agent_sdk.protocol.agent_commands.base import AgentCommand
from hydros_agent_sdk.topics import HydrosTopics
from hydros_agent_sdk.transport.base import Transport

from .codec import AgentCommandDecoder

if TYPE_CHECKING:
    from hydros_agent_sdk.agent_commands.runtime import AgentCommandRuntime


logger = logging.getLogger(__name__)


class AgentCommandClient:
    """Decode and publish agent commands through a shared ``Transport``."""

    def __init__(
        self,
        transport: Transport,
        topic: Optional[str] = None,
        hydros_cluster_id: Optional[str] = None,
        qos: int = 1,
        max_retry_count: int = 5,
        base_retry_delay_ms: int = 1000,
    ) -> None:
        if topic:
            self.topic = topic
        elif hydros_cluster_id:
            self.topic = HydrosTopics.get_agent_command_topic(hydros_cluster_id)
        else:
            raise ValueError("topic 和 hydros_cluster_id 不能同时为空")

        self.transport = transport
        self.qos = qos
        self.max_retry_count = max_retry_count
        self.base_retry_delay_ms = base_retry_delay_ms
        self._runtime: Optional["AgentCommandRuntime"] = None
        self._decoder = AgentCommandDecoder()
        self.transport.subscribe(self.topic, self._handle_transport_payload, qos=self.qos)

    @property
    def runtime(self) -> "AgentCommandRuntime":
        if self._runtime is None:
            raise RuntimeError("AgentCommandRuntime is not bound")
        return self._runtime

    def bind_runtime(self, runtime: "AgentCommandRuntime") -> None:
        if self._runtime is not None:
            raise RuntimeError("AgentCommandRuntime is already bound")
        self._runtime = runtime

    def start(self) -> None:
        self.runtime.start()

    def stop(self) -> None:
        self.runtime.stop()

    def register_handler(self, handler) -> None:
        self.runtime.register_handler(handler)

    def send_command(self, command: AgentCommand) -> None:
        self.runtime.send_command(command)

    def set_pending_command_predicate(
        self,
        predicate: Optional[Callable[[AgentCommand], bool]],
    ) -> None:
        self.runtime.set_pending_command_predicate(predicate)

    def publish_command(self, command: AgentCommand) -> None:
        """Serialize and publish one agent command through the shared transport."""
        attempt = 0
        while attempt <= self.max_retry_count:
            try:
                self.transport.publish(
                    self.topic,
                    command.model_dump_json(by_alias=True),
                    qos=self.qos,
                )
                return
            except Exception:
                attempt += 1
                logger.error(
                    "Failed to publish agent command: type=%s id=%s attempt=%s/%s",
                    command.command_type,
                    command.command_id,
                    attempt,
                    self.max_retry_count,
                    exc_info=True,
                )
                if attempt > self.max_retry_count:
                    raise
                time.sleep((self.base_retry_delay_ms * (2 ** attempt)) / 1000.0)

    def _handle_transport_payload(self, topic: str, payload_str: str) -> None:
        try:
            payload = json.loads(payload_str)
            self.runtime.handle_incoming_command(self._decoder.decode(payload))
        except Exception as exc:
            logger.error(
                "Failed to process agent command payload on %s: %s",
                topic,
                exc,
                exc_info=True,
            )
