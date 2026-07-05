"""
面向 tick 驱动仿真智能体的可调度智能体基类。

本模块提供 TickableAgent 基类，在 BaseHydroAgent 基础上增加
tick 驱动仿真能力和时序数据更新处理。
"""

import logging
from abc import abstractmethod
from typing import Optional, List

from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.error_codes import ErrorCodes
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.runtime.time_series_cache import TimeSeriesCache
from hydros_agent_sdk.transport.mqtt_metrics_publisher import MqttMetricsPublisher
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics
from hydros_agent_sdk.protocol.commands import (
    TickCmdRequest,
    TickCmdResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    AgentStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


class TickableAgent(BaseHydroAgent):
    """
    tick 驱动仿真智能体的基类。

    该类为以下类型的智能体提供通用能力：
    1. 响应 TickCmdRequest 并执行仿真步
    2. 处理时序数据更新（边界条件）
    3. 通过 MQTT 输出指标数据

    子类：
    - OntologySimulationAgent: Ontology-based simulation
    - TwinsSimulationAgent: Digital twins simulation
    - CentralSchedulingAgent: Central scheduling base
    - MpcCentralSchedulingAgent: Central scheduling with MPC optimization

    关键特性：
    - tick 驱动执行（响应 TickCmdRequest）
    - 时序数据更新处理（边界条件）
    - MQTT 指标输出支持
    - 通用生命周期管理（init、tick、terminate）

    子类必须实现：
    - on_init(): 初始化智能体并加载配置
    - on_tick_simulation(): 执行仿真步逻辑
    - on_terminate(): 清理资源

    子类可覆盖：
    - on_time_series_data_update(): 处理边界条件更新
    - on_boundary_condition_update(): 响应缓存后的边界条件变化
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
        初始化可调度智能体。

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

        # 当前仿真步
        self._current_step: int = 0

        self.time_series_cache = TimeSeriesCache()
        self._time_series_cache = self.time_series_cache.store
        self.metrics_publisher = MqttMetricsPublisher.from_coordination_client(
            sim_coordination_client,
            biz_scene_instance_id=context.biz_scene_instance_id,
            cluster_id=hydros_cluster_id,
            edge_node_code=hydros_node_id,
        )

        logger.info(f"TickableAgent initialized: {self.agent_id}")

    def supports_tick_command(self) -> bool:
        """返回该智能体是否参与仿真 tick 分派。"""
        return True

    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        处理仿真 tick。

        该方法会：
        1. 设置智能体日志上下文
        2. 更新当前步
        3. 调用 on_tick_simulation() 执行子类专属逻辑
        4. 通过 MQTT 发送指标数据
        5. 返回 TickCmdResponse

        Args:
            request: Tick 指令请求

        Returns:
            Tick 指令响应
        """
        self._current_step = request.step

        logger.info(f"Processing tick: step={request.step}, commandId={request.command_id}")

        try:
            # 执行仿真步（子类专属逻辑）
            metrics_list = self.on_tick_simulation(request)

            # 通过 MQTT 发送指标数据
            if metrics_list:
                self.metrics_publisher.publish_batch(metrics_list)
                logger.info(f"Sent {len(metrics_list)} metrics for step {request.step}")

            response = ResponseFactory.tick_succeed(self, request)

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=tick_cmd_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Error processing tick {request.step}: {e}", exc_info=True)

            return ResponseFactory.tick_failed(
                self,
                request,
                error_code=ErrorCodes.AGENT_TICK_FAILURE.code,
                error_message=ErrorCodes.AGENT_TICK_FAILURE.format_message(
                    self.agent_code,
                    f"{type(e).__name__}: {e}",
                ),
            )

    @abstractmethod
    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行仿真步逻辑。

        子类在这里实现各自的仿真逻辑。

        Args:
            request: Tick 指令请求

        Returns:
            要通过 MQTT 发送的 MqttMetrics 对象列表，或 None
        """
        pass

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        处理时序数据更新（边界条件）。

        该方法会：
        1. 从事件中提取时序数据
        2. 更新内部缓存
        3. 调用 on_boundary_condition_update() 执行子类专属处理
        4. 返回 TimeSeriesDataUpdateResponse

        子类可覆盖 on_boundary_condition_update() 来处理边界条件变化。

        Args:
            request: 时序数据更新请求

        Returns:
            时序数据更新响应
        """
        logger.info(f"Received time series data update: commandId={request.command_id}")

        try:
            # 从事件中提取时间序列数据
            event = request.time_series_data_changed_event
            if event and event.object_time_series:
                for time_series in event.object_time_series:
                    self.time_series_cache.update(time_series)

                    logger.info(
                        f"Updated time series: object={time_series.object_name}, "
                        f"metrics={time_series.metrics_code}, "
                        f"values={len(time_series.time_series)}"
                    )

                # 调用子类专属处理器
                self.on_boundary_condition_update(event.object_time_series)

            return ResponseFactory.time_series_data_update_succeed(self, request)

        except Exception as e:
            logger.error(f"Error handling time series data update: {e}", exc_info=True)

            return ResponseFactory.time_series_data_update_failed(self, request)

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        处理边界条件更新。

        子类可覆盖该方法来处理边界条件变化。默认实现不执行任何操作。

        Args:
            time_series_list: 已更新的时序数据列表
        """
        pass

    @property
    def current_step(self) -> int:
        """获取当前仿真步。"""
        return self._current_step
