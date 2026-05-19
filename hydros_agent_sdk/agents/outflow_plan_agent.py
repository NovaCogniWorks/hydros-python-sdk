"""
用于事件驱动型外发流量计划的智能体。

该模块提供了 OutflowPlanAgent 类，它扩展了 BaseHydroAgent，
具备事件驱动的外发流量计划能力。
"""

import logging
from typing import Optional, List
from abc import abstractmethod

from .tickable_agent import TickableAgent, MqttMetrics
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    OutflowTimeSeriesRequest,
    OutflowTimeSeriesResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

from hydros_agent_sdk.utils import HydroObjectUtilsV2

logger = logging.getLogger(__name__)


class OutflowPlanAgent(TickableAgent):
    """
    事件驱动型的外发流量计划智能体。

    该智能体根据事件执行外发流量计划逻辑：
    1. 从协调器接收 OutflowTimeSeriesRequest 请求
    2. 执行外发流量计划计算
    3. 生成外发流量计划的 ObjectTimeSeries 结果
    4. 将响应返回给协调器

    核心特性：
    - 事件驱动执行（非步进驱动）
    - 基于水文事件的外发流量计划
    - 输出计划流量的时间序列

    使用示例：
        ```python
        agent = OutflowPlanAgent(
            sim_coordination_client=client,
            agent_id="OUTFLOW_PLAN_001",
            agent_code="OUTFLOW_PLAN_AGENT",
            agent_type="OUTFLOW_PLAN_AGENT",
            agent_name="Outflow Plan Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01",
            drive_mode=AgentDriveMode.EVENT_DRIVEN
        )
        ```

    子类必须实现：
    - on_init(): 初始化智能体并加载配置
    - on_outflow_time_series(): 执行外发流量计划逻辑
    - on_terminate(): 清理资源
    """

    def __init__(
        self,
        sim_coordination_client,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        agent_biz_status: AgentBizStatus = AgentBizStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.EVENT_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        初始化外发流量计划智能体。

        参数:
            sim_coordination_client: 必填的 MQTT 客户端
            agent_id: 唯一的智能体实例 ID
            agent_code: 智能体代码
            agent_type: 智能体类型
            agent_name: 智能体名称
            context: 仿真上下文
            hydros_cluster_id: 集群 ID
            hydros_node_id: 节点 ID
            agent_biz_status: 初始业务状态
            drive_mode: 智能体驱动模式（默认：EVENT_DRIVEN）
            agent_configuration_url: 可选的配置 URL
            **kwargs: 其他关键字参数
        """
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            agent_biz_status=agent_biz_status,
            drive_mode=drive_mode,
            agent_configuration_url=agent_configuration_url,
            **kwargs
        )

        # 外发流量计划状态
        self._plan_config = {}

        self._topology = None

        logger.info(f"OutflowPlanAgent initialized: {self.agent_id}")

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化外发流量计划智能体。

        子类应该：
        1. 使用 self.load_agent_configuration(request) 加载智能体配置
        2. 加载拓扑并初始化计划模型
        3. 在状态管理器中注册
        4. 返回 SimTaskInitResponse

        参数:
            request: 任务初始化请求

        返回:
            任务初始化响应
        """
        logger.info(f"Initializing outflow plan agent: {self.agent_id}")

        # 加载智能体配置
        self.load_agent_configuration(request)

        # 如果配置了 URL，则加载拓扑
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        if topology_url:
            logger.info(f"Loading topology from: {topology_url}")
            self._topology = HydroObjectUtilsV2.build_waterway_topology(topology_url)
            logger.info(f"Topology loaded: {len(self._topology.top_objects)} top objects")

        # 初始化计划模型
        self._initialize_planning_models()

        # 在状态管理器中注册
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        logger.info(f"Outflow plan agent initialized successfully: {self.agent_id}")

        # 将智能体状态更新为 ACTIVE
        object.__setattr__(self, 'agent_biz_status', AgentBizStatus.ACTIVE)

        # 返回响应
        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False
        )

    def _initialize_planning_models(self):
        """初始化外发流量计划模型。"""
        logger.info("Initializing outflow planning models...")

        # 加载计划配置
        planning_config = self.properties.get_property('planning_config', {})

        # 在此处初始化具体的计划模型
        # 例如：优化模型、预报模型等

        logger.info("Planning models initialized")

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行基于本体的仿真步骤。由于该智能体是事件驱动的，通常返回 None。

        参数:
            request: 步进指令请求

        返回:
            要通过 MQTT 发送的 MqttMetrics 对象列表
        """
        return None

    @abstractmethod
    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        处理外发流量时间序列请求。

        子类必须实现此方法以执行外发流量计划逻辑。
        该方法应该：
        1. 从请求中提取事件信息
        2. 执行外发流量计划计算
        3. 生成 ObjectTimeSeries 结果
        4. 将响应发送回协调器

        参数:
            request: 包含水文事件的外发流量时间序列请求
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止外发流量计划智能体。

        子类应该：
        1. 清理计划资源
        2. 在状态管理器中注销
        3. 返回 SimTaskTerminateResponse

        参数:
            request: 任务终止请求

        返回:
            任务终止响应
        """
        pass
