"""
多智能体协调支持。

本模块提供 MultiAgentCallback，用于在单个进程中处理多个智能体类型。
"""

import logging
from typing import Dict, List, Optional, Any

from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesRequest,
)
from hydros_agent_sdk.protocol.models import AgentInstanceStatus, HydroAgent
from hydros_agent_sdk.runtime.agent_instance_status_support import AgentInstanceStatusSupport
from hydros_agent_sdk.runtime.agent_logging_context import AgentLoggingContextSetter
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.agent_constants import (
    CENTRAL_SCHEDULING_AGENT_TYPE,
    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
)

logger = logging.getLogger(__name__)


class MultiAgentCallback(SimCoordinationCallback):
    """
    在单个进程中管理多个智能体类型的多智能体回调。

    该回调会按以下方式处理 SimTaskInitRequest：
    1. 检查 agent_list 以决定需要实例化哪些智能体
    2. 创建全部匹配的智能体实例
    3. 返回一个包含全部已创建实例的 SimTaskInitResponse

    这是多智能体协调场景的正确实现：一个 SimTaskInitRequest 可以触发
    多个智能体实例化，但只应返回一个 SimTaskInitResponse。

    示例：
        callback = MultiAgentCallback(node_id="LOCAL")
        callback.register_agent_factory("TWINS_SIMULATION_AGENT", twins_factory)
        callback.register_agent_factory("ONTOLOGY_SIMULATION_AGENT", ontology_factory)
    """

    def __init__(self, node_id: str = "LOCAL"):
        """
        初始化多智能体回调。

        Args:
            node_id: 当前智能体宿主节点标识
        """
        self.node_id = node_id
        self.agent_factories: Dict[str, Any] = {}  # {agent_code: 工厂}
        self.agent_factory_types: Dict[str, str] = {}  # {agent_code: agent_type}
        self.agents: Dict[str, Dict[str, Any]] = {}  # {context_id: {agent_code: 智能体}}
        self._client: Optional[Any] = None
        self._status_support: Optional[AgentInstanceStatusSupport] = None
        self._pending_status_reports: List[Any] = []
        self._logging_context_setter = AgentLoggingContextSetter()

        logger.info(f"MultiAgentCallback created for node: {node_id}")

    def register_agent_factory(self, agent_code: str, factory: Any, agent_type: Optional[str] = None):
        """
        为指定 agent_code 注册智能体工厂。

        Args:
            agent_code: 智能体编码（例如 "TWINS_SIMULATION_AGENT"）
            factory: 智能体工厂实例（HydroAgentFactory）
            agent_type: 可选智能体类型。未提供时会尽量从工厂配置推断。
        """
        self.agent_factories[agent_code] = factory
        self.agent_factory_types[agent_code] = agent_type or self._infer_factory_agent_type(agent_code, factory)
        logger.info(f"Registered agent factory: {agent_code}")

    def register_system_default_central_scheduling_agent(self, env_config: Optional[Dict[str, str]] = None):
        """注册系统默认中央调度智能体，已注册时不覆盖。"""
        if SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE in self.agent_factories:
            return

        from hydros_agent_sdk.factory import SystemCentralSchedulingAgentFactory

        self.register_agent_factory(
            SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
            SystemCentralSchedulingAgentFactory(env_config=env_config),
            agent_type=CENTRAL_SCHEDULING_AGENT_TYPE,
        )

    def _infer_factory_agent_type(self, agent_code: str, factory: Any) -> str:
        """尽量从 factory 配置里拿 agent_type，拿不到就退回 agent_code。"""
        for attr_name in ("agent_type", "_agent_type"):
            agent_type = getattr(factory, attr_name, None)
            if agent_type:
                return str(agent_type)

        config_file = getattr(factory, "config_file", None)
        load_config = getattr(factory, "_load_config", None)
        if config_file and callable(load_config):
            try:
                config = load_config(config_file)
                agent_type = config.get("agent_type")
                if agent_type:
                    return str(agent_type)
            except Exception:
                logger.debug("Could not infer agent_type for factory %s", agent_code, exc_info=True)

        return agent_code

    def _is_central_scheduling_agent_def(self, agent_def: Any) -> bool:
        agent_code = getattr(agent_def, "agent_code", None)
        agent_type = getattr(agent_def, "agent_type", None)
        return (
            agent_type == CENTRAL_SCHEDULING_AGENT_TYPE
            or agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
        )

    def _is_central_scheduling_factory(self, agent_code: str, agent_type: Optional[str]) -> bool:
        return (
            agent_type == CENTRAL_SCHEDULING_AGENT_TYPE
            or agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
            or agent_code.startswith(f"{SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE}_")
        )

    def _has_custom_central_scheduling_factory(self) -> bool:
        for agent_code, agent_type in self.agent_factory_types.items():
            if agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE:
                continue
            if self._is_central_scheduling_factory(agent_code, agent_type):
                return True
        return False

    def _resolve_agent_factory(self, agent_def: Any):
        """解析 task init 中某个 agent 应该使用的 factory。"""
        agent_code = agent_def.agent_code

        factory = self.agent_factories.get(agent_code)
        if factory is not None:
            return agent_code, factory

        if not self._is_central_scheduling_agent_def(agent_def):
            return agent_code, None

        system_factory = self.agent_factories.get(SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE)
        if system_factory is None:
            return agent_code, None

        if self._has_custom_central_scheduling_factory():
            logger.debug(
                "Central scheduling custom route requires exact agent_code: requested=%s",
                agent_code,
            )
            return agent_code, None

        return SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE, system_factory

    def set_client(self, client: Any):
        """设置协调客户端引用。"""
        self._client = client
        self._status_support = AgentInstanceStatusSupport(
            report_sink=self._record_status_report,
        )
        logger.info("Coordination client reference set")

    def _record_status_report(self, report) -> None:
        self._pending_status_reports.append(report)

    def consume_pending_status_reports(self):
        reports = list(self._pending_status_reports)
        self._pending_status_reports.clear()
        return reports

    def get_component(self) -> str:
        """
        获取组件名称。

        对于多智能体回调，这里返回一个通用名称，因为它会处理多个智能体类型。
        实际 agent_code 过滤会在 on_sim_task_init 中基于 agent_list 完成。
        """
        return "MULTI_AGENT_COORDINATOR"

    def is_remote_agent(self, agent_instance: Any) -> bool:
        """检查智能体是否为远端智能体。"""
        if self._client:
            return self._client.state_manager.is_remote_agent(agent_instance)
        return False

    def _execute_with_status(
        self,
        agent,
        action,
        phase: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        def wrapped_action():
            self._logging_context_setter.set_for_agent(agent)
            return action()

        if self._status_support is None:
            return wrapped_action()

        return self._status_support.execute_with_status(
            agent,
            wrapped_action,
            phase=phase,
            metadata=metadata,
        )

    def _transition_status(
        self,
        agent,
        status: AgentInstanceStatus,
        phase: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if self._status_support is None:
            return None

        try:
            return self._status_support.transition_status(
                agent,
                status,
                phase=phase,
                metadata=metadata,
            )
        except Exception:
            logger.warning(
                "Failed to transition agent instance status: agentCode=%s, status=%s, phase=%s",
                getattr(agent, "agent_code", None),
                status,
                phase,
                exc_info=True,
            )
            return None

    def on_sim_task_init(self, request: SimTaskInitRequest):
        """
        处理多智能体任务初始化。

        该方法会：
        1. 遍历 request.agent_list
        2. 对每个已注册工厂的 agent_code 创建实例
        3. 收集全部已创建的智能体实例
        4. 返回一个包含全部实例的 SimTaskInitResponse
        """
        context_id = request.context.biz_scene_instance_id

        if self._client is None:
            raise RuntimeError("Coordination client not set")

        logger.debug("Task configuration URL: %s", request.biz_scene_configuration_url)
        logger.info(f"Processing SimTaskInitRequest for task: {context_id}")
        logger.info(f"  Requested agents: {[a.agent_code for a in request.agent_list]}")

        try:
            ContextManager.create_from_init_request(request)
        except Exception:
            logger.warning(
                "Failed to initialize hydro model context from scenario config: %s",
                request.biz_scene_configuration_url,
                exc_info=True,
            )

        # 跟踪本任务中创建的智能体
        created_agents = []
        context_agents = {}
        routed_agent_codes = set()

        # 逐个处理 agent_list 中的智能体
        for agent_def in request.agent_list:
            agent_code = agent_def.agent_code

            # 检查是否存在该 agent_code 的工厂，或是否为系统默认中央调度智能体。
            routed_agent_code, factory = self._resolve_agent_factory(agent_def)

            if factory is None:
                logger.debug(f"  No factory registered for {agent_code}, skipping")
                continue

            if routed_agent_code in routed_agent_codes:
                logger.debug(f"  Agent route already handled for {routed_agent_code}, skipping duplicate")
                continue
            routed_agent_codes.add(routed_agent_code)

            logger.info(f"  Creating agent: {routed_agent_code} (requested: {agent_code})")

            try:
                # 创建智能体实例
                agent = factory.create_agent(
                    sim_coordination_client=self._client,
                    context=request.context
                )
                should_sync_identity = routed_agent_code == agent_code
                if should_sync_identity:
                    self._sync_agent_definition_from_request(agent, agent_def)

                # 初始化智能体
                self._logging_context_setter.set_for_agent(agent)
                response = agent.on_init(request)
                created_agent_code = getattr(agent, "agent_code", routed_agent_code)

                # 收集已创建的智能体实例
                if response and hasattr(response, 'source_agent_instance'):
                    if should_sync_identity:
                        self._sync_init_response_agent_definition(response, agent_def)
                    created_agents.append(response.source_agent_instance)
                    self._transition_status(
                        response.source_agent_instance,
                        AgentInstanceStatus.WAITING,
                        phase="TASK_INITIALIZED",
                        metadata={
                            "command_id": request.command_id,
                            "agent_code": created_agent_code,
                            "requested_agent_code": agent_code,
                            "biz_scene_instance_id": context_id,
                        },
                    )

                # 存储智能体
                context_agents[created_agent_code] = agent

                logger.info(f"  ✓ Agent created and initialized: {created_agent_code}")

            except Exception as e:
                logger.error(f"  ✗ Failed to create agent {routed_agent_code}: {e}", exc_info=True)
                # 继续处理其他智能体

        # 存储该上下文下的智能体
        if context_agents:
            self.agents[context_id] = context_agents

        # 返回包含全部已创建实例的单个响应
        if created_agents:
            # 使用第一个已创建智能体作为 source_agent_instance
            # 协议限制：理想情况下应支持多个 source_agent_instance
            first_agent = created_agents[0]

            response = ResponseFactory.init_succeed(
                first_agent,
                request,
                created_agent_instances=created_agents,
            )

            logger.info(f"SimTaskInitResponse created with {len(created_agents)} agent(s)")
            return response
        else:
            logger.warning(f"No agents created for task {context_id}")
            return None

    @staticmethod
    def _sync_agent_definition_from_request(agent: Any, agent_def: HydroAgent) -> None:
        """保持运行时路由/配置一致，但不覆盖本地显示名称。"""
        if getattr(agent_def, "agent_type", None):
            object.__setattr__(agent, "agent_type", agent_def.agent_type)
        if getattr(agent_def, "agent_configuration_url", None):
            object.__setattr__(
                agent,
                "agent_configuration_url",
                agent_def.agent_configuration_url,
            )

    @classmethod
    def _sync_init_response_agent_definition(
        cls,
        response: SimTaskInitResponse,
        agent_def: HydroAgent,
    ) -> None:
        """保持返回的智能体实例与协调器请求一致。"""
        cls._sync_agent_definition_from_request(response.source_agent_instance, agent_def)
        for agent_instance in response.created_agent_instances or []:
            if agent_instance.agent_code == agent_def.agent_code:
                cls._sync_agent_definition_from_request(agent_instance, agent_def)

    def on_tick(self, request: TickCmdRequest):
        """处理上下文中全部智能体的 tick 指令。"""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # 将 tick 转发给该上下文中的全部智能体
        responses = []
        for agent_code, agent in context_agents.items():
            if not self._supports_tick_command(agent):
                logger.debug("Skipping tick for agent without tick capability: %s", agent_code)
                continue
            try:
                response = self._execute_with_status(
                    agent,
                    lambda agent=agent: agent.on_tick(request),
                    phase="TICK",
                    metadata={
                        "command_id": request.command_id,
                        "step": request.step,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                    },
                )
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Error in tick for {agent_code}: {e}", exc_info=True)
        return responses

    @staticmethod
    def _supports_tick_command(agent: Any) -> bool:
        supports_tick_command = getattr(agent, "supports_tick_command", None)
        if supports_tick_command is None:
            return True
        return bool(supports_tick_command())

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """处理上下文中全部智能体的任务终止。"""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # 终止该上下文中的全部智能体
        responses = []
        for agent_code, agent in context_agents.items():
            try:
                self._transition_status(
                    agent,
                    AgentInstanceStatus.RUNNING,
                    phase="TASK_TERMINATE_STARTED",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "reason": request.reason,
                    },
                )
                self._logging_context_setter.set_for_agent(agent)
                response = agent.on_terminate(request)
                if response:
                    responses.append(response)
                terminal_status = (
                    AgentInstanceStatus.CANCELED
                    if request.reason and "cancel" in request.reason.lower()
                    else AgentInstanceStatus.COMPLETED
                )
                self._transition_status(
                    agent,
                    terminal_status,
                    phase="TASK_TERMINATED",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "reason": request.reason,
                    },
                )
                logger.info(f"Agent terminated: {agent_code}")
            except Exception as e:
                self._transition_status(
                    agent,
                    AgentInstanceStatus.FAILED,
                    phase="TASK_TERMINATE_FAILED",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "reason": request.reason,
                        "error_message": str(e),
                    },
                )
                logger.error(f"Error terminating {agent_code}: {e}", exc_info=True)

        # 从跟踪结构中移除智能体
        del self.agents[context_id]
        super().on_task_terminate(request)
        logger.info(f"All agents terminated for context: {context_id}")
        return responses

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        """处理上下文中全部智能体的时间序列数据更新。"""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # 将更新转发给该上下文中的全部智能体
        responses = []
        for agent_code, agent in context_agents.items():
            try:
                event = request.time_series_data_changed_event
                response = self._execute_with_status(
                    agent,
                    lambda agent=agent: agent.on_time_series_data_update(request),
                    phase="TIME_SERIES_DATA_UPDATE",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "auto_schedule_at_step": getattr(event, "auto_schedule_at_step", None),
                        "hydro_event_type": getattr(event, "hydro_event_type", None),
                        "hydro_event_source_type": getattr(event, "hydro_event_source_type", None),
                    },
                )
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Error in time series update for {agent_code}: {e}", exc_info=True)
        return responses

    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest):
        """处理上下文中全部智能体的出流时间序列数据更新。"""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # 将更新转发给该上下文中的全部智能体
        responses = []
        for agent_code, agent in context_agents.items():
            try:
                event = request.outflow_time_series_data_changed_event
                response = self._execute_with_status(
                    agent,
                    lambda agent=agent: agent.on_outflow_time_series_data_update(request),
                    phase="OUTFLOW_TIME_SERIES_DATA_UPDATE",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "auto_schedule_at_step": getattr(event, "auto_schedule_at_step", None),
                        "hydro_event_type": getattr(event, "hydro_event_type", None),
                        "hydro_event_source_type": getattr(event, "hydro_event_source_type", None),
                    },
                )
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Error in outflow time series update for {agent_code}: {e}", exc_info=True)
        return responses

    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        处理目标智能体的出流时间序列请求。

        与会广播给全部智能体的 on_tick 或 on_time_series_data_update 不同，
        该方法只把请求路由给请求中指定的目标智能体。
        """
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # 从请求中提取目标 agent code
        target_agent_code = request.target_agent_instance.agent_code

        # 查找目标智能体
        target_agent = context_agents.get(target_agent_code)

        if not target_agent:
            logger.warning(
                f"Target agent '{target_agent_code}' not found in context {context_id}. "
                f"Available agents: {list(context_agents.keys())}"
            )
            return None

        # 仅将请求转发给目标智能体
        try:
            logger.debug(f"Routing outflow time series request to agent: {target_agent_code}")
            response = self._execute_with_status(
                target_agent,
                lambda: target_agent.on_outflow_time_series(request),
                phase="OUTFLOW_TIME_SERIES",
                metadata={
                    "command_id": request.command_id,
                    "agent_code": target_agent_code,
                    "biz_scene_instance_id": context_id,
                    "target_agent_id": request.target_agent_instance.agent_id,
                    "target_agent_code": request.target_agent_instance.agent_code,
                },
            )
            return response
        except Exception as e:
            logger.error(
                f"Error in outflow time series for {target_agent_code}: {e}",
                exc_info=True
            )
            return None
