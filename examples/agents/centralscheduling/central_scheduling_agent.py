"""
面向生产的中央调度智能体示例。

本示例刻意保持业务逻辑轻量，让 SDK 默认 MpcCentralSchedulingAgent 路径负责
滚动 MPC、MpcPredictionResultReport 发布和智能体指令分派。
"""

import logging
import json
from typing import Optional

from hydros_agent_sdk import ErrorCodes, handle_agent_errors, load_runtime_env_settings
from hydros_agent_sdk.agents.mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import AgentStatus, CommandStatus

logger = logging.getLogger(__name__)


class ProductionCentralSchedulingAgent(MpcCentralSchedulingAgent):
    """
    最小化的生产中央智能体实现。

    它不覆盖 on_optimization()，因此 MPC 基类会执行与 Java 等价的滚动 MPC 路径。
    """

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initializing production central scheduling agent: %s", self.agent_id)

        try:
            self.load_agent_configuration(request)
            self._load_object_agent_code_map()
            self._subscribe_configured_field_metrics()

            self._agent_command_gateway.start()

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
            self._agent_command_gateway.shutdown()
            raise

    def _subscribe_configured_field_metrics(self) -> None:
        metrics_topic = self._get_metrics_topic()
        if not metrics_topic:
            logger.info("No metrics topic configured; MPC will rely on injected/provider sensor data")
            return

        task_id = self.context.biz_scene_instance_id
        full_topic = f"{metrics_topic.rstrip('/')}/{task_id}"
        logger.info("Subscribing central field metrics topic: %s", full_topic)
        self._metrics_subscriber.subscribe(full_topic)

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
        settings = load_runtime_env_settings()
        metrics_topic = self._get_string_property("metrics_topic", settings.metrics_topic)
        if not metrics_topic:
            return None

        cluster_id = self.cluster_id or settings.hydros_cluster_id or ""
        return settings.render_topic(metrics_topic, cluster_id=cluster_id)

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("Terminating production central scheduling agent: %s", self.agent_id)

        self._agent_command_gateway.shutdown()
        object.__setattr__(self, "agent_status", AgentStatus.TERMINATED)

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )
