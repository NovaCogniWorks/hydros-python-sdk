"""
Hydros 智能体基础实现。

本模块提供继承自 HydroAgentInstance 的 BaseHydroAgent 类，
并增加处理仿真生命周期的行为方法。
"""

import logging
from typing import Optional, TYPE_CHECKING
from abc import ABC, abstractmethod
from pydantic import ConfigDict

from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    AgentInstanceStatus,
    HydroAgentInstance,
    SimulationContext,
    AgentDriveMode,
)
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
    TimeSeriesCalculationRequest,
    OutflowTimeSeriesRequest,
)
from hydros_agent_sdk.protocol.models import CommandStatus
from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.agent_constants import (
    CENTRAL_SCHEDULING_AGENT_TYPE,
    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
)

# 仅用于类型检查，避免运行时循环导入
if TYPE_CHECKING:
    from hydros_agent_sdk.coordination_client import SimCoordinationClient
    from hydros_agent_sdk.state_manager import AgentStateManager

logger = logging.getLogger(__name__)


class BaseHydroAgent(HydroAgentInstance, ABC):
    """
    采用改进继承设计的 Hydro 智能体基类。

    继承层级：
        HydroBaseModel (Pydantic base)
            ↓
        HydroAgent（智能体定义）
            - agent_code, agent_type, agent_name, agent_configuration_url
            ↓
        HydroAgentInstance（运行中实例）
            - agent_id, biz_scene_instance_id, hydros_cluster_id, hydros_node_id
            - context, agent_status, drive_mode
            ↓
        BaseHydroAgent（行为基类）
            - 增加生命周期方法：on_init(), on_tick(), on_terminate()
            - 增加非 Pydantic 属性：sim_coordination_client, state_manager, properties

    关键特性：
    1. 继承 HydroAgentInstance 以复用全部智能体实例属性
    2. 不重复定义属性，全部从父类继承
    3. 构造函数要求传入非空 sim_coordination_client
    4. 生命周期清晰：任务初始化时创建，任务终止时销毁
    5. 每个智能体实例对应一个仿真任务
    6. properties：用于灵活配置的 AgentProperties 字典

    非 Pydantic 属性（动态设置，不参与序列化）：
    - sim_coordination_client: 协调客户端实例
    - state_manager: 状态管理器引用
    - properties: 带类型化访问方法的 AgentProperties 字典

    Attributes:
        sim_coordination_client: 用于发送指令的 MQTT 协调客户端
        state_manager: 用于跟踪活跃上下文的智能体状态管理器
        properties: 带类型化访问方法的 AgentProperties 字典
    """

    # 配置 Pydantic 允许非模型属性使用额外字段
    model_config = ConfigDict(extra='allow', arbitrary_types_allowed=True)

    # 动态设置属性的类型提示（通过 object.__setattr__ 设置）
    # 仅用于 IDE 支持，不是 Pydantic 字段
    if TYPE_CHECKING:
        sim_coordination_client: 'SimCoordinationClient'
        state_manager: 'AgentStateManager'
        properties: AgentProperties

    def __init__(
        self,
        sim_coordination_client,  # 移除类型提示以避免循环导入
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        agent_status: AgentStatus = AgentStatus.INIT,
        agent_instance_status: AgentInstanceStatus = AgentInstanceStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        初始化智能体实例。

        Args:
            sim_coordination_client: 必填 MQTT 客户端（非空）
            agent_id: 唯一智能体实例 ID
            agent_code: 智能体编码（例如 "TWINS_SIMULATION_AGENT"）
            agent_type: 智能体类型（例如 "TWINS_SIMULATION_AGENT"）
            agent_name: 智能体名称（例如 "Twins Simulation Agent"）
            context: 当前智能体的仿真上下文
            hydros_cluster_id: 当前智能体运行所在集群 ID
            hydros_node_id: 当前智能体运行所在节点 ID
            agent_status: 初始容器状态（默认 INIT）
            agent_instance_status: 初始实例生命周期状态（默认 INIT）
            drive_mode: 智能体驱动模式（默认 SIM_TICK_DRIVEN）
            agent_configuration_url: 可选智能体配置 URL，未提供时从 SimTaskInitRequest 加载
            **kwargs: 传给 HydroAgentInstance 的额外关键字参数
        """
        # 必填参数校验
        if sim_coordination_client is None:
            raise ValueError("sim_coordination_client is required")
        if context is None:
            raise ValueError("context is required")

        # 使用全部必填字段初始化父类 HydroAgentInstance
        super().__init__(
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            agent_configuration_url=agent_configuration_url or "",
            biz_scene_instance_id=context.biz_scene_instance_id,
            cluster_id=hydros_cluster_id,
            node_id=hydros_node_id,
            context=context,
            agent_status=agent_status,
            agent_instance_status=agent_instance_status,
            drive_mode=drive_mode,
            **kwargs
        )

        # 存储非 Pydantic 属性（不会序列化）
        # 由于 model_config extra='allow'，这些属性会作为额外字段保存
        object.__setattr__(self, 'sim_coordination_client', sim_coordination_client)
        object.__setattr__(self, 'state_manager', sim_coordination_client.state_manager)
        object.__setattr__(self, 'properties', AgentProperties())

        # 注意：日志上下文（task_id、biz_component）会由 SimCoordinationClient
        # 在处理指令时自动设置，因此回调中的全部日志都会包含正确的上下文信息。
        logger.info(f"Created agent instance: {self.agent_id}")
        logger.info(f"  - Agent Code: {self.agent_code}")
        logger.info(f"  - Agent Name: {self.agent_name}")
        logger.info(f"  - Agent Type: {self.agent_type}")
        logger.info(f"  - Context: {self.biz_scene_instance_id}")
        logger.info(f"  - Status: {self.agent_status}")
        logger.info(f"  - Instance Status: {self.agent_instance_status}")
        logger.info(f"  - Drive Mode: {self.drive_mode}")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化智能体并创建 HydroAgentInstance。

        任务初始化时调用。

        Args:
            request: 任务初始化请求

        Returns:
            任务初始化响应
        """
        pass

    def _set_agent_logging_context(self):
        """
        为当前智能体实例设置日志上下文。

        应在每个智能体方法（on_init、on_tick 等）开头调用，确保智能体
        业务逻辑日志包含正确的 agent_id。
        """
        from hydros_agent_sdk.logging_config import set_biz_component, set_biz_scene_instance_id

        # 为智能体业务逻辑把 biz_component 设置为 agent_id
        if self.agent_id:
            set_biz_component(self.agent_id)

        # 从 context 设置 biz_scene_instance_id
        if self.context and self.context.biz_scene_instance_id:
            set_biz_scene_instance_id(self.context.biz_scene_instance_id)

    def supports_tick_command(self) -> bool:
        """返回该智能体是否参与仿真 tick 分派。"""
        return False

    @abstractmethod
    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        处理仿真 tick。

        每个仿真步都会调用。

        Args:
            request: Tick 指令请求

        Returns:
            Tick 指令响应
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止智能体并清理资源。

        任务终止时调用。

        Args:
            request: 任务终止请求

        Returns:
            任务终止响应
        """
        pass

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        处理时序数据更新。

        默认实现。可按需覆盖。

        Args:
            request: 时序数据更新请求

        Returns:
            时序数据更新响应
        """
        logger.info(f"Time series data update: {request.command_id}")

        return TimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,  # self 已经是 HydroAgentInstance
            broadcast=False
        )

    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest) -> OutflowTimeSeriesDataUpdateResponse:
        """
        处理外发流量时序数据更新。

        默认实现调用标准时序更新逻辑。

        Args:
            request: 外发流量时序数据更新请求

        Returns:
            外发流量时序数据更新响应
        """
        logger.info(f"Outflow time series data update: {request.command_id}")
        return OutflowTimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,  # self 已经是 HydroAgentInstance
            broadcast=False
        )

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        处理时序计算。

        默认实现。可按需覆盖。

        Args:
            request: 时序计算请求
        """
        logger.info(f"Time series calculation: {request.command_id}")

    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        处理外发流量时序请求。

        默认实现。可按需覆盖。

        Args:
            request: 外发流量时序请求
        """
        logger.info(f"Outflow time series request: {request.command_id}")

    def send_response(self, response):
        """
        通过协调客户端发送响应。

        Args:
            response: 要发送的响应
        """
        self.sim_coordination_client.enqueue(response)

    @property
    def runtime_context(self):
        """
        面向新智能体代码的轻量运行时门面。

        现有智能体可以继续直接使用 sim_coordination_client、state_manager
        和 properties。较新的代码可以依赖这个更窄的上下文，便于逐步将
        运行时关注点和业务逻辑拆开。
        """
        from hydros_agent_sdk.runtime import AgentContext

        return AgentContext(
            client=self.sim_coordination_client,
            state_manager=self.state_manager,
            agent=self,
        )

    def load_agent_configuration(self, request: SimTaskInitRequest) -> None:
        """
        从 SimTaskInitRequest 加载智能体配置。

        该方法会：
        1. 从 request.agent_list 中匹配当前 agent_code，并提取 agent_configuration_url
        2. 从 URL 加载 YAML 配置
        3. 校验 YAML 中的 agent_code 是否匹配当前智能体的 agent_code 或 agent_type，
           这样专用 agent_code 可以共享同一类类型化配置
        4. 将 YAML 中的属性写入 self.properties

        Args:
            request: 包含 agent_list 和配置 URL 的 SimTaskInitRequest

        Raises:
            ValueError: 配置中的 agent_code 不匹配时抛出
            Exception: 配置加载失败时抛出

        注意：
            如果 agent_list 中没有找到当前智能体，本方法会跳过加载并静默返回，
            因为 SimTaskInitRequest 可能只初始化部分智能体。
        """
        from hydros_agent_sdk.agent_config import AgentConfigLoader

        # 在 agent_list 中按 agent_code 精确查找匹配智能体
        matching_agent = None
        for agent in request.agent_list:
            if agent.agent_code == self.agent_code:
                matching_agent = agent
                break

        # 系统默认中央调度智能体可以承接唯一一个中央调度定义的配置。
        if matching_agent is None and self._is_system_default_central_scheduling_agent():
            central_agents = [
                agent
                for agent in request.agent_list
                if getattr(agent, "agent_type", None) == CENTRAL_SCHEDULING_AGENT_TYPE
            ]
            if len(central_agents) == 1:
                matching_agent = central_agents[0]
                logger.info(
                    "Using system default %s to load configuration "
                    "for requested central agent '%s'",
                    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
                    matching_agent.agent_code,
                )

        if matching_agent is None:
            logger.info(
                f"Agent '{self.agent_code}' not found in SimTaskInitRequest.agent_list, "
                f"skipping configuration loading (this is normal if only initializing a subset of agents)"
            )
            return

        if not matching_agent.agent_configuration_url:
            logger.warning(f"No agent_configuration_url provided for agent '{self.agent_code}'")
            return

        agent_config_url = matching_agent.agent_configuration_url
        logger.info(f"Loading agent configuration from: {agent_config_url}")

        try:
            # 从 URL 加载配置
            agent_config = AgentConfigLoader.from_url(agent_config_url)

            # 校验 agent_code 是否匹配。部分部署会共享通用 agent_type 配置，
            # 同时使用专门的运行时 agent_code。
            allowed_agent_codes = {self.agent_code, self.agent_type}
            if getattr(matching_agent, 'agent_code', None):
                allowed_agent_codes.add(matching_agent.agent_code)
            if getattr(matching_agent, 'agent_type', None):
                allowed_agent_codes.add(matching_agent.agent_type)

            if agent_config.agent_code not in allowed_agent_codes:
                raise ValueError(
                    f"Agent code mismatch: expected one of {sorted(allowed_agent_codes)}, "
                    f"but YAML contains '{agent_config.agent_code}'. "
                    f"Please check the agent_configuration_url: {agent_config_url}"
                )

            logger.info(
                f"Agent configuration validated successfully for '{self.agent_code}' "
                f"(YAML agent_code: '{agent_config.agent_code}')"
            )

            # 从 YAML 设置属性
            if agent_config.properties:
                # 将 Pydantic 模型转换为 dict 并更新 AgentProperties
                properties_dict = agent_config.properties.model_dump(exclude_none=True)
                self.properties.update(properties_dict)

            for component in agent_config.components or []:
                if not component.enabled or not component.properties:
                    continue
                component_properties = component.properties.model_dump(exclude_none=True)
                self.properties.update(component_properties)

            logger.info(f"Loaded {len(self.properties)} properties from configuration")
            logger.debug(f"Properties: {list(self.properties.keys())}")

            # 更新 agent_configuration_url
            object.__setattr__(self, 'agent_configuration_url', agent_config_url)

        except Exception as e:
            logger.error(f"Failed to load agent configuration from {agent_config_url}: {e}")
            raise

    def _is_system_default_central_scheduling_agent(self) -> bool:
        return (
            self.agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
            and self.agent_type == CENTRAL_SCHEDULING_AGENT_TYPE
        )
