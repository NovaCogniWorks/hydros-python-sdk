"""
System default central scheduling agent implementation.
"""

import json
import logging

from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import AgentStatus, CommandStatus
from hydros_agent_sdk.runtime.env_settings import load_runtime_env_settings
from hydros_agent_sdk.utils.property_parse_utils import PropertyParseUtils

logger = logging.getLogger(__name__)


class SystemCentralSchedulingAgent(CentralSchedulingAgent):
    """
    系统默认中央调度智能体。

    该类固定服务于系统默认 agent_code：CENTRAL_SCHEDULING_AGENT。
    它复用 CentralSchedulingAgent 的默认 MPC 路径，初始化时只做通用配置加载、
    现地指标订阅和状态注册；如果业务需要自定义调度逻辑，仍然可以继续通过
    独立的 agent_code 注册自定义 CentralSchedulingAgent 子类。
    """

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initializing system central scheduling agent: %s", self.agent_id)

        try:
            self.load_agent_configuration(request)
            self._initialize_model_context()

            raw_mapping = self.properties.get_property("object_agent_code_map", None)
            if raw_mapping:
                if isinstance(raw_mapping, dict):
                    mapping = raw_mapping
                else:
                    mapping = json.loads(str(raw_mapping))
                self._object_agent_code_map = {
                    str(object_id): str(agent_code)
                    for object_id, agent_code in mapping.items()
                }
                logger.info("Loaded object-agent mapping entries: %s", len(self._object_agent_code_map))

            settings = load_runtime_env_settings()
            metrics_topic = PropertyParseUtils.get_string(
                self.properties,
                "metrics_topic",
                settings.metrics_topic,
            )
            if metrics_topic:
                cluster_id = self.cluster_id or settings.hydros_cluster_id or ""
                rendered_topic = settings.render_topic(str(metrics_topic), cluster_id=cluster_id)
                task_id = self.context.biz_scene_instance_id
                full_topic = f"{rendered_topic.rstrip('/')}/{task_id}"
                logger.info("Subscribing system central field metrics topic: %s", full_topic)
                self._metrics_subscriber.subscribe(full_topic)
            else:
                logger.info("No metrics topic configured; MPC will rely on injected/provider sensor data")

            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)
            self.agent_command_gateway.start()

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
            self.agent_command_gateway.shutdown()
            raise

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("Terminating system central scheduling agent: %s", self.agent_id)

        self.agent_command_gateway.shutdown()
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
