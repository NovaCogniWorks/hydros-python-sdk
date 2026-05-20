"""
Production-oriented central scheduling Agent example.

This example intentionally keeps business logic thin so the SDK default
CentralSchedulingAgent path can handle rolling MPC, MpcResultReport publishing,
and agent-command dispatch.
"""

import logging
import os
import json
from typing import Optional

from hydros_agent_sdk import ErrorCodes, handle_agent_errors, load_env_config
from hydros_agent_sdk.agents import CentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import AgentStatus, CommandStatus

logger = logging.getLogger(__name__)


class ProductionCentralSchedulingAgent(CentralSchedulingAgent):
    """
    Minimal production central Agent implementation.

    It does not override on_optimization(), so the SDK base class will execute
    the Java-equivalent rolling MPC path.
    """

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initializing production central scheduling agent: %s", self.agent_id)

        try:
            self.load_agent_configuration(request)
            self._load_object_agent_code_map()
            self._subscribe_configured_field_metrics()

            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)
            self._start_agent_command_client()

            object.__setattr__(self, "agent_status", AgentStatus.ACTIVE)

            return SimTaskInitResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                created_agent_instances=[self],
                managed_top_objects={},
                broadcast=False,
            )
        except Exception:
            self._shutdown_agent_command_client()
            raise

    def _subscribe_configured_field_metrics(self) -> None:
        metrics_topic = self._get_metrics_topic()
        if not metrics_topic:
            logger.info("No metrics topic configured; MPC will rely on injected/provider sensor data")
            return

        task_id = self.context.biz_scene_instance_id
        full_topic = f"{metrics_topic.rstrip('/')}/{task_id}"
        logger.info("Subscribing central field metrics topic: %s", full_topic)
        self.subscribe_to_field_metrics(full_topic)

    def _load_object_agent_code_map(self) -> None:
        raw_mapping = self.properties.get_property("object_agent_code_map", None)
        if not raw_mapping:
            return

        if isinstance(raw_mapping, dict):
            mapping = raw_mapping
        else:
            mapping = json.loads(str(raw_mapping))

        self._object_agent_code_map = {
            str(object_id): str(agent_code)
            for object_id, agent_code in mapping.items()
        }
        logger.info("Loaded object-agent mapping entries: %s", len(self._object_agent_code_map))

    def _get_metrics_topic(self) -> Optional[str]:
        metrics_topic = self._get_string_property("metrics_topic", None)
        if not metrics_topic:
            try:
                metrics_topic = load_env_config().get("metrics_topic")
            except Exception:
                metrics_topic = None

        if not metrics_topic:
            return None

        cluster_id = self.cluster_id or os.getenv("HYDROS_CLUSTER_ID", "")
        return metrics_topic.replace("{hydros_cluster_id}", cluster_id)

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("Terminating production central scheduling agent: %s", self.agent_id)

        self._shutdown_agent_command_client()
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)
        object.__setattr__(self, "agent_status", AgentStatus.TERMINATED)

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )
