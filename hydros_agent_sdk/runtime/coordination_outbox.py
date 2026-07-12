"""Coordination command outbound publishing service."""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from hydros_agent_sdk.protocol.commands import (
    AgentInstanceStatusReport,
    EdgeControlExecutionReport,
    MpcExecutionStatusReport,
    MpcPredictionResultReport,
    SimCommand,
    SimCoordinationRequest,
    SimCoordinationResponse,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.state_manager import AgentStateManager


logger = logging.getLogger(__name__)


class CoordinationOutboxPublisher:
    """Decides which coordination commands leave this node and publishes them."""

    def __init__(
        self,
        mqtt_client,
        state_manager: AgentStateManager,
        topic: str,
        qos: int = 1,
        max_retry_count: int = 5,
        base_retry_delay_ms: int = 1000,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.mqtt_client = mqtt_client
        self.state_manager = state_manager
        self.topic = topic
        self.qos = qos
        self.max_retry_count = max_retry_count
        self.base_retry_delay_ms = base_retry_delay_ms
        self.logger = log or logger

    def should_send(self, command: SimCommand) -> bool:
        """Return whether an outbound coordination command should be published."""
        if isinstance(command, SimCoordinationRequest):
            return False

        if isinstance(command, SimCoordinationResponse):
            if isinstance(command, SimTaskTerminateResponse):
                node_id = self.state_manager.get_node_id()
                if node_id and command.source_agent_instance.hydros_node_id == node_id:
                    return True
            return self.state_manager.is_local_agent(command.source_agent_instance)

        if isinstance(command, AgentInstanceStatusReport):
            if self.state_manager.is_local_agent(command.source_agent_instance):
                return True
            node_id = self.state_manager.get_node_id()
            return bool(node_id and command.source_agent_instance.hydros_node_id == node_id)

        if isinstance(
            command,
            (MpcPredictionResultReport, MpcExecutionStatusReport, EdgeControlExecutionReport),
        ):
            return self._is_local_source(command.source_agent_instance)

        return False

    def _is_local_source(self, source_agent_instance) -> bool:
        if self.state_manager.is_local_agent(source_agent_instance):
            return True
        node_id = self.state_manager.get_node_id()
        return bool(node_id and source_agent_instance.hydros_node_id == node_id)

    def send_with_retry(self, command: SimCommand) -> None:
        """Publish a coordination command to MQTT with retry/backoff."""
        attempt = 0
        command_id = command.command_id

        while attempt <= self.max_retry_count:
            try:
                payload = command.model_dump_json(by_alias=True)
                result = self.mqtt_client.publish(self.topic, payload, qos=self.qos)
                result.wait_for_publish()

                if isinstance(command, MpcPredictionResultReport):
                    self.logger.info(
                        "MPC prediction result report sent to coordinator: topic=%s, command_id=%s, "
                        "result_count=%s, detail_count=%s",
                        self.topic,
                        command_id,
                        len(command.mpc_prediction_results or []),
                        self.count_mpc_prediction_result_details(command),
                    )
                return

            except Exception as exc:
                self.logger.error(
                    "Failed to send command: id=%s, attempt=%s/%s: %s",
                    command_id,
                    attempt,
                    self.max_retry_count,
                    exc,
                )

                attempt += 1
                if attempt > self.max_retry_count:
                    self.logger.error("Max retry count exceeded for command: id=%s", command_id)
                    raise

                delay_ms = self.base_retry_delay_ms * (2 ** attempt)
                self.logger.info(
                    "Retrying after %sms... (attempt %s/%s)",
                    delay_ms,
                    attempt,
                    self.max_retry_count,
                )
                time.sleep(delay_ms / 1000.0)

    @classmethod
    def format_command_for_log(cls, command: SimCommand) -> str:
        if isinstance(command, MpcPredictionResultReport):
            summary = {
                "command_type": command.command_type,
                "command_id": command.command_id,
                "biz_scene_instance_id": (
                    command.context.biz_scene_instance_id
                    if command.context is not None
                    else None
                ),
                "result_count": len(command.mpc_prediction_results or []),
                "detail_count": cls.count_mpc_prediction_result_details(command),
            }
            return json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        return command.model_dump_json(indent=None)

    @staticmethod
    def count_mpc_prediction_result_details(command: MpcPredictionResultReport) -> int:
        return sum(len(result.details or []) for result in command.mpc_prediction_results or [])
