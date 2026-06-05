"""
用于事件驱动模型计算的模型计算智能体。

本模块提供 ModelCalculationAgent 类，在 BaseHydroAgent 基础上增加
事件驱动模型计算能力。
"""

import logging
from typing import Optional, List, Dict, Any
from abc import abstractmethod

from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesCalculationRequest,
    TimeSeriesCalculationResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentStatus,
    AgentDriveMode,
    ObjectTimeSeries,
    TimeSeriesValue,
)
from hydros_agent_sdk.protocol.events import HydroEvent

logger = logging.getLogger(__name__)


class ModelCalculationAgent(BaseHydroAgent):
    """
    事件驱动型模型计算智能体。

    该智能体响应事件并执行一次性模型计算：
    1. 接收协调器发送的 TimeSeriesCalculationRequest
    2. 执行复杂模型计算（例如水文模型）
    3. 生成 ObjectTimeSeries 结果
    4. 向协调器返回 TimeSeriesCalculationResponse

    关键特性：
    - 事件驱动执行（非 tick 驱动）
    - 每个请求执行一次计算
    - 支持复杂模型（天气预报、水文模型等）
    - 输出时序结果

    使用示例：
        ```python
        agent = ModelCalculationAgent(
            sim_coordination_client=client,
            agent_id="HYDRO_MODEL_001",
            agent_code="HYDROLOGICAL_MODEL_AGENT",
            agent_type="MODEL_CALCULATION_AGENT",
            agent_name="Hydrological Model Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01",
            drive_mode=AgentDriveMode.EVENT_DRIVEN
        )
        ```

    子类必须实现：
    - on_init(): 初始化智能体并加载模型
    - on_model_calculation(): 执行模型计算逻辑
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
        agent_status: AgentStatus = AgentStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.EVENT_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        初始化模型计算智能体。

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
            drive_mode: 智能体驱动模式（默认 EVENT_DRIVEN）
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

        # 模型状态
        self._model = None
        self._model_config = {}

        logger.info(f"ModelCalculationAgent initialized: {self.agent_id}")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化模型计算智能体。

        子类应完成：
        1. 使用 self.load_agent_configuration(request) 加载智能体配置
        2. 加载并初始化计算模型
        3. 注册到状态管理器
        4. 返回 SimTaskInitResponse

        Args:
            request: 任务初始化请求

        Returns:
            任务初始化响应
        """
        pass

    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        处理 tick 指令（不适用于事件驱动智能体）。

        模型计算智能体是事件驱动的，不响应 tick 指令。该方法会返回失败响应。

        Args:
            request: Tick 指令请求

        Returns:
            状态为 FAILED 的 Tick 指令响应
        """
        logger.warning(
            f"ModelCalculationAgent received TickCmdRequest (not supported). "
            f"This agent is EVENT_DRIVEN and should not receive tick commands."
        )

        return TickCmdResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.FAILED,
            source_agent_instance=self,
            broadcast=False
        )

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        处理时序计算请求。

        该方法会：
        1. 从请求中提取事件信息
        2. 调用 on_model_calculation() 执行子类专属逻辑
        3. 发送带计算结果的 TimeSeriesCalculationResponse

        Args:
            request: 时序计算请求
        """
        logger.info(f"Received TimeSeriesCalculationRequest, commandId={request.command_id}")
        logger.info(f"Event: {request.hydro_event}")

        try:
            # 执行模型计算（子类专属）
            object_time_series_list = self.on_model_calculation(request.hydro_event)

            logger.info(f"Model calculation completed, produced {len(object_time_series_list)} time series")

            # 创建响应
            response = TimeSeriesCalculationResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                object_time_series_list=object_time_series_list,
                broadcast=False
            )

            # 发送响应
            self.send_response(response)

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=calculation_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

        except Exception as e:
            logger.error(f"Error in model calculation: {e}", exc_info=True)

            # 发送失败响应
            response = TimeSeriesCalculationResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                object_time_series_list=[],
                broadcast=False
            )

            self.send_response(response)

    @abstractmethod
    def on_model_calculation(self, hydro_event: HydroEvent) -> List[ObjectTimeSeries]:
        """
        执行模型计算逻辑。

        子类必须实现该方法，以执行各自的模型计算（例如水文模型、天气预报模型）。

        Args:
            hydro_event: 触发计算的事件

        Returns:
            包含计算结果的 ObjectTimeSeries 列表
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止模型计算智能体。

        子类应完成：
        1. 清理模型资源
        2. 从状态管理器注销
        3. 返回 SimTaskTerminateResponse

        Args:
            request: 任务终止请求

        Returns:
            任务终止响应
        """
        pass

    def create_time_series(
        self,
        object_id: int,
        object_name: str,
        object_type: str,
        metrics_code: str,
        time_series_values: List[Dict[str, Any]],
        time_series_name: Optional[str] = None
    ) -> ObjectTimeSeries:
        """
        创建 ObjectTimeSeries 的辅助方法。

        Args:
            object_id: 对象 ID
            object_name: 对象名称
            object_type: 对象类型
            metrics_code: 指标编码
            time_series_values: 时序值列表，每个 dict 应包含 step、time（可选）和 value
            time_series_name: 可选时序名称

        Returns:
            ObjectTimeSeries 实例
        """
        # 转换为 TimeSeriesValue 对象
        ts_values = []
        for ts_dict in time_series_values:
            ts_value = TimeSeriesValue(
                step=ts_dict.get('step'),
                time=ts_dict.get('time'),
                value=ts_dict.get('value')
            )
            ts_values.append(ts_value)

        # 创建 ObjectTimeSeries
        return ObjectTimeSeries(
            time_series_name=time_series_name or f"{object_name}_{metrics_code}",
            object_id=object_id,
            object_type=object_type,
            object_name=object_name,
            metrics_code=metrics_code,
            time_series=ts_values
        )
