"""
用于实时水网仿真的数字孪生仿真智能体。

本模块提供 TwinsSimulationAgent 类，在 TickableAgent 基础上增加数字孪生仿真能力。
"""

import logging
from typing import Optional, List

from .tickable_agent import TickableAgent
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    AgentStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


class TwinsSimulationAgent(TickableAgent):
    """
    数字孪生仿真智能体。

    该智能体执行基于数字孪生的水网仿真：
    1. 加载水网拓扑和物理模型
    2. 执行高保真仿真步
    3. 处理实时边界条件更新
    4. 通过 MQTT 输出详细指标数据

    关键特性：
    - 高保真物理建模
    - 实时仿真同步
    - 支持复杂水力计算
    - 边界条件处理
    - 与物理系统进行状态同步

    使用示例：
        ```python
        agent = TwinsSimulationAgent(
            sim_coordination_client=client,
            agent_id="TWINS_SIM_001",
            agent_code="TWINS_SIMULATION_AGENT",
            agent_type="TWINS_SIMULATION_AGENT",
            agent_name="Digital Twins Simulation Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01"
        )
        ```
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
        agent_status: AgentStatus = AgentStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        初始化数字孪生仿真智能体。

        Args:
            sim_coordination_client: 必填 MQTT 客户端
            agent_id: 唯一智能体实例 ID
            agent_code: 智能体编码
            agent_type: 智能体类型
            agent_name: 智能体名称
            context: 仿真上下文
            hydros_cluster_id: 集群 ID
            hydros_node_id: 节点 ID
            agent_status: 初始业务状态
            drive_mode: 智能体驱动模式（默认 SIM_TICK_DRIVEN）
            agent_configuration_url: 可选配置 URL
            **kwargs: 额外关键字参数
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
            agent_status=agent_status,
            drive_mode=drive_mode,
            agent_configuration_url=agent_configuration_url,
            **kwargs
        )

        # 数字孪生模型和状态
        self._twins_model = None
        self._topology = None
        self._simulation_state = {}

        logger.info(f"TwinsSimulationAgent initialized: {self.agent_id}")

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化数字孪生仿真智能体。

        该方法会：
        1. 从 SimTaskInitRequest 加载智能体配置
        2. 加载水网拓扑和物理模型
        3. 初始化仿真状态
        4. 注册到状态管理器

        Args:
            request: 任务初始化请求

        Returns:
            任务初始化响应
        """
        logger.info("="*70)
        logger.info(f"INITIALIZING DIGITAL TWINS SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # 加载智能体配置
            logger.info("Loading agent configuration...")
            self.load_agent_configuration(request)
            logger.info(f"Configuration loaded with {len(self.properties)} properties")

            # 加载水网拓扑
            hydros_objects_modeling_url = self.properties.get_property('hydros_objects_modeling_url')
            if hydros_objects_modeling_url:
                logger.info("Loading water network topology for digital twins...")
                from hydros_agent_sdk.utils import HydroObjectUtilsV2

                # 加载包含全部参数的拓扑，用于高保真仿真
                param_keys = self.properties.get_property(
                    'param_keys',
                    {'max_opening', 'min_opening', 'interpolate_cross_section_count'}
                )
                self._topology = HydroObjectUtilsV2.build_waterway_topology(
                    modeling_yml_uri=hydros_objects_modeling_url,
                    param_keys=param_keys,
                    with_metrics_code=True
                )

                logger.info(f"Loaded topology with {len(self._topology.top_objects)} top-level objects")

                # 初始化数字孪生模型（子类专属）
                self._initialize_twins_model()
            else:
                logger.warning("No hydros_objects_modeling_url configured")

            # 将智能体状态更新为 ACTIVE
            object.__setattr__(self, 'agent_status', AgentStatus.ACTIVE)

            logger.info(f"Digital twins simulation agent initialized: {self.agent_id}")

            response = ResponseFactory.init_succeed(self, request)

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=sim_task_init_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Failed to initialize digital twins simulation agent: {e}", exc_info=True)

            return ResponseFactory.init_failed(self, request)

    def _initialize_twins_model(self):
        """
        初始化数字孪生模型。

        子类可覆盖该方法来初始化各自的数字孪生模型
        （例如水力求解器、状态估计器）。默认实现不执行任何操作。
        """
        logger.info("Initializing digital twins model...")
        # 待办：初始化水力求解器、状态估计器等组件。
        pass

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行数字孪生仿真步。

        Args:
            request: Tick 指令请求

        Returns:
            要通过 MQTT 发送的 MqttMetrics 对象列表
        """
        logger.info(f"Executing digital twins simulation step {request.step}")

        try:
            metrics_list = self._execute_twins_simulation(request.step)
            logger.info(f"Digital twins simulation step {request.step} completed")
            return metrics_list

        except Exception as e:
            logger.error(f"Error in digital twins simulation step {request.step}: {e}", exc_info=True)
            return None

    def _execute_twins_simulation(self, step: int) -> List[MqttMetrics]:
        """
        执行数字孪生仿真逻辑。

        子类应覆盖该方法，实现各自的数字孪生仿真逻辑（例如水力计算）。

        Args:
            step: 当前仿真步

        Returns:
            MqttMetrics 对象列表
        """
        # 默认实现：返回模拟指标
        # 子类应覆盖该方法
        logger.warning("Using default digital twins simulation (mock data)")

        metrics_list = []
        if self._topology:
            for top_obj in self._topology.top_objects[:3]:  # 前 3 个对象
                for child in top_obj.children[:2]:  # 前 2 个子对象
                    if child.metrics:
                        for metrics_code in child.metrics[:1]:  # 第 1 个指标
                            metrics_list.append(create_mock_metrics(
                                source_id=self.agent_code,
                                job_instance_id=self.biz_scene_instance_id,
                                object_id=child.object_id,
                                object_name=child.object_name,
                                step_index=step,
                                metrics_code=metrics_code,
                                value=0.5 + (step % 10) * 0.05
                            ))

        return metrics_list

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        处理数字孪生仿真的边界条件更新。

        该方法用新的边界条件更新仿真状态，用于与物理系统实时同步。

        Args:
            time_series_list: 已更新的时序数据列表
        """
        logger.info(f"Updating digital twins state with {len(time_series_list)} boundary conditions")

        # 使用边界条件更新仿真状态
        for time_series in time_series_list:
            logger.debug(
                f"Boundary condition: object={time_series.object_name}, "
                f"metrics={time_series.metrics_code}"
            )

            # 存入仿真状态
            state_key = f"{time_series.object_id}_{time_series.metrics_code}"
            self._simulation_state[state_key] = time_series

            # 待办：更新水力求解器的边界条件

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止数字孪生仿真智能体。

        该方法会：
        1. 清理数字孪生模型
        2. 从状态管理器注销
        3. 返回 SimTaskTerminateResponse

        Args:
            request: 任务终止请求

        Returns:
            任务终止响应
        """
        logger.info("="*70)
        logger.info(f"TERMINATING DIGITAL TWINS SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # 清理数字孪生模型
            self._twins_model = None
            self._topology = None
            self._simulation_state.clear()

            logger.info(f"Digital twins simulation agent terminated: {self.agent_id}")

            response = ResponseFactory.terminate_succeed(self, request)

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=sim_task_terminate_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Error terminating digital twins simulation agent: {e}", exc_info=True)

            return ResponseFactory.terminate_failed(self, request)
