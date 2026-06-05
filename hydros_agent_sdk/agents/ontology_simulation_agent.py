"""
用于本体驱动水网仿真的本体仿真智能体。

本模块提供 OntologySimulationAgent 类，在 TickableAgent 基础上增加本体仿真能力。
"""

import logging
from typing import Optional, List

from .tickable_agent import TickableAgent
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


class OntologySimulationAgent(TickableAgent):
    """
    基于本体的仿真智能体。

    该智能体执行基于本体的水网仿真：
    1. 从本体模型加载水网拓扑
    2. 基于本体规则执行仿真步
    3. 处理边界条件更新
    4. 通过 MQTT 输出指标数据

    关键特性：
    - 基于本体的建模和仿真
    - 基于规则的仿真逻辑
    - 支持复杂水网拓扑
    - 边界条件处理

    使用示例：
        ```python
        agent = OntologySimulationAgent(
            sim_coordination_client=client,
            agent_id="ONTOLOGY_SIM_001",
            agent_code="ONTOLOGY_SIMULATION_AGENT",
            agent_type="ONTOLOGY_SIMULATION_AGENT",
            agent_name="Ontology Simulation Agent",
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
        初始化本体仿真智能体。

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

        # 本体模型和拓扑
        self._ontology_model = None
        self._topology = None

        logger.info(f"OntologySimulationAgent initialized: {self.agent_id}")

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化本体仿真智能体。

        该方法会：
        1. 从 SimTaskInitRequest 加载智能体配置
        2. 从本体模型加载水网拓扑
        3. 初始化仿真状态
        4. 注册到状态管理器

        Args:
            request: 任务初始化请求

        Returns:
            任务初始化响应
        """
        logger.info("="*70)
        logger.info(f"INITIALIZING ONTOLOGY SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # 加载智能体配置
            logger.info("Loading agent configuration...")
            self.load_agent_configuration(request)
            logger.info(f"Configuration loaded with {len(self.properties)} properties")

            # 从本体模型加载水网拓扑
            hydros_objects_modeling_url = self.properties.get_property('hydros_objects_modeling_url')
            if hydros_objects_modeling_url:
                logger.info("Loading water network topology from ontology model...")
                from hydros_agent_sdk.utils import HydroObjectUtilsV2

                # 加载包含指定参数的拓扑
                param_keys = self.properties.get_property('param_keys', {'max_opening', 'min_opening'})
                self._topology = HydroObjectUtilsV2.build_waterway_topology(
                    modeling_yml_uri=hydros_objects_modeling_url,
                    param_keys=param_keys,
                    with_metrics_code=True
                )

                logger.info(f"Loaded topology with {len(self._topology.top_objects)} top-level objects")

                # 初始化本体模型（子类专属）
                self._initialize_ontology_model()
            else:
                logger.warning("No hydros_objects_modeling_url configured")

            # 将智能体状态更新为 ACTIVE
            object.__setattr__(self, 'agent_status', AgentStatus.ACTIVE)

            # 注册到状态管理器
            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)

            logger.info(f"Ontology simulation agent initialized: {self.agent_id}")

            # 创建响应
            response = SimTaskInitResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                created_agent_instances=[self],
                managed_top_objects={},
                broadcast=False
            )

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=sim_task_init_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Failed to initialize ontology simulation agent: {e}", exc_info=True)

            # 返回失败响应
            return SimTaskInitResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                created_agent_instances=[],
                managed_top_objects={},
                broadcast=False
            )

    def _initialize_ontology_model(self):
        """
        初始化本体模型。

        子类可覆盖该方法来初始化各自的本体模型。默认实现不执行任何操作。
        """
        logger.info("Initializing ontology model...")
        # 待办：加载本体规则、约束等内容。
        pass

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行基于本体的仿真步。

        Args:
            request: Tick 指令请求

        Returns:
            要通过 MQTT 发送的 MqttMetrics 对象列表
        """
        logger.info(f"Executing ontology simulation step {request.step}")

        try:
            metrics_list = self._execute_ontology_simulation(request.step)
            logger.info(f"Ontology simulation step {request.step} completed")
            return metrics_list

        except Exception as e:
            logger.error(f"Error in ontology simulation step {request.step}: {e}", exc_info=True)
            return None

    def _execute_ontology_simulation(self, step: int) -> List[MqttMetrics]:
        """
        执行基于本体的仿真逻辑。

        子类应覆盖该方法，实现各自的本体仿真逻辑。

        Args:
            step: 当前仿真步

        Returns:
            MqttMetrics 对象列表
        """
        # 默认实现：返回空指标
        # 子类应覆盖该方法
        logger.warning("Using default ontology simulation (no-op)")
        return []

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        处理本体仿真的边界条件更新。

        该方法会用新的边界条件更新本体模型。

        Args:
            time_series_list: 已更新的时序数据列表
        """
        logger.info(f"Updating ontology model with {len(time_series_list)} boundary conditions")

        # 使用边界条件更新本体模型
        for time_series in time_series_list:
            logger.debug(
                f"Boundary condition: object={time_series.object_name}, "
                f"metrics={time_series.metrics_code}"
            )
            # 待办：更新本体模型状态

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止本体仿真智能体。

        该方法会：
        1. 清理本体模型
        2. 从状态管理器注销
        3. 返回 SimTaskTerminateResponse

        Args:
            request: 任务终止请求

        Returns:
            任务终止响应
        """
        logger.info("="*70)
        logger.info(f"TERMINATING ONTOLOGY SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # 清理本体模型
            self._ontology_model = None
            self._topology = None

            # 从状态管理器注销
            self.state_manager.terminate_task(self.context)
            self.state_manager.remove_local_agent(self)

            logger.info(f"Ontology simulation agent terminated: {self.agent_id}")

            # 创建响应
            response = SimTaskTerminateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                broadcast=False
            )

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=sim_task_terminate_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Error terminating ontology simulation agent: {e}", exc_info=True)

            # 返回失败响应
            return SimTaskTerminateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                broadcast=False
            )
