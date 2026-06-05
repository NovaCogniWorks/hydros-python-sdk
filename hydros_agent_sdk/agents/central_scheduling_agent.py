"""
具备 MPC 优化能力的中央调度智能体。

该模块提供了 CentralSchedulingAgent 类，它扩展了 TickableAgent，
增加了模型预测控制（MPC）优化功能。
"""

import logging
from typing import Optional, List, Dict, Any, Callable, Iterable
from abc import abstractmethod

from hydros_agent_sdk.agent_commands.dispatching import ControlCommandDispatcher
from hydros_agent_sdk.agent_commands.transport import AgentCommandClient, AgentCommandGateway
from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.mpc.client import MpcPlanningClient
from hydros_agent_sdk.mpc.control_command_builder import MpcControlCommandBuilder
from hydros_agent_sdk.mpc.metrics_data_cache import MetricsDataCache
from hydros_agent_sdk.mpc.models import SensorData
from hydros_agent_sdk.mpc.optimization_service import MpcOptimizationService
from hydros_agent_sdk.mpc.reporter import MpcResultReporter
from hydros_agent_sdk.mpc.rolling_runtime import MpcRollingRuntime
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.transport.mqtt_metrics_subscriber import MqttMetricsSubscriber
from hydros_agent_sdk.agents.target_agent_resolver import TargetAgentResolver
from .tickable_agent import TickableAgent
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
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


DEFAULT_METRICS_HISTORY_STEPS = 10


class CentralSchedulingAgent(TickableAgent):
    """
    具备 MPC 优化能力的中央调度智能体。

    该智能体执行模型预测控制（MPC）优化：
    1. 在滚动优化时界（Rolling Horizon）上执行（步长周期的倍数）
    2. 通过 MQTT 订阅接收来自现地设备的实时指标
    3. 处理边界条件更新
    4. 执行 MPC 优化
    5. 通过 agent command 客户端发送智能体间控制指令

    核心特性：
    - 滚动时界优化 (MPC)
    - 通过 MQTT 订阅实时现地指标
    - 边界条件处理
    - 基于优化的控制逻辑
    - 支持智能体间指令交互（未来支持）

    使用示例：
        ```python
        agent = CentralSchedulingAgent(
            sim_coordination_client=client,
            agent_id="CENTRAL_SCHEDULING_001",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Central Scheduling Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01",
        )
        ```

    子类必须实现：
    - on_init(): 初始化智能体并加载优化模型
    - on_optimization(): 执行 MPC 优化逻辑
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
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        初始化中央调度智能体。

        参数:
            sim_coordination_client: 必填的 MQTT 客户端
            agent_id: 唯一的智能体实例 ID
            agent_code: 智能体代码
            agent_type: 智能体类型
            agent_name: 智能体名称
            context: 仿真上下文
            hydros_cluster_id: 集群 ID
            hydros_node_id: 节点 ID
            agent_status: 初始业务状态
            drive_mode: 智能体驱动模式（默认：SIM_TICK_DRIVEN）
            agent_configuration_url: 可选的配置 URL
            **kwargs: 其他关键字参数
        """
        configured_mpc_config_url = kwargs.pop("mpc_config_url", None)
        configured_target_and_constrain_config_url = kwargs.pop(
            "target_and_constrain_config_url", None
        )
        configured_mpc_service_base_url = kwargs.pop("mpc_service_base_url", None)
        configured_mpc_planning_client = kwargs.pop("mpc_planning_client", None)
        configured_mpc_result_reporter = kwargs.pop("mpc_result_reporter", None)
        configured_mpc_sensor_provider = kwargs.pop("mpc_sensor_provider", None)
        configured_object_agent_code_map = kwargs.pop("object_agent_code_map", None)

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

        # MPC 相关配置
        self._configured_mpc_service_base_url = configured_mpc_service_base_url
        self._mpc_sensor_provider: Optional[Callable[..., Iterable[SensorData | Dict[str, Any]]]] = (
            configured_mpc_sensor_provider
        )
        self._mpc_planning_client: Optional[MpcPlanningClient] = configured_mpc_planning_client
        self._mpc_result_reporter: MpcResultReporter = configured_mpc_result_reporter or MpcResultReporter(
            sim_coordination_client=sim_coordination_client
        )
        self._object_agent_code_map: Dict[str, str] = {
            str(object_id): agent_code
            for object_id, agent_code in (configured_object_agent_code_map or {}).items()
        }
        # 智能体指令客户端按需懒加载
        self._agent_command_gateway = AgentCommandGateway(
            sim_coordination_client=sim_coordination_client,
            hydros_cluster_id=hydros_cluster_id,
            state_manager=self.state_manager,
            client_factory=lambda **kwargs: AgentCommandClient(**kwargs),
        )
        self._target_agent_resolver = TargetAgentResolver(
            sim_coordination_client=sim_coordination_client,
            context=context,
            object_agent_code_map_getter=lambda: self._object_agent_code_map,
        )
        self._control_command_builder = MpcControlCommandBuilder(
            source_agent=self,
            get_sibling_agent_instance=self._target_agent_resolver.get_sibling_agent_instance,
            resolve_target_agent_for_object=self._target_agent_resolver.resolve_target_agent_for_object,
        )
        self._control_command_dispatcher = ControlCommandDispatcher(
            send_command=lambda command: self._agent_command_gateway.send_command(command),
            build_station_target_value_request=self._control_command_builder.build_station_target_value_request,
        )

        # 优化模型与拓扑
        self._optimization_model = None
        self._topology = None

        # 现地设备实时指标缓存
        self._metrics_data_cache = MetricsDataCache(max_steps=DEFAULT_METRICS_HISTORY_STEPS)
        self._field_metrics_cache = self._metrics_data_cache.latest_metrics
        self._field_metrics_step_cache = self._metrics_data_cache.metrics_by_step
        self._metrics_subscriber = MqttMetricsSubscriber(
            mqtt_client=sim_coordination_client.mqtt_client,
            metrics_data_cache=self._metrics_data_cache,
        )

        self._mpc_optimization_service = MpcOptimizationService(
            properties=self.properties,
            metrics_data_cache=self._metrics_data_cache,
            configured_mpc_service_base_url=self._configured_mpc_service_base_url,
            mpc_planning_client=self._mpc_planning_client,
            mpc_result_reporter=self._mpc_result_reporter,
            mpc_sensor_provider=self._mpc_sensor_provider,
        )
        self._mpc_rolling_runtime = MpcRollingRuntime(
            context=context,
            properties=self.properties,
            optimize_step=self.on_optimization,
            dispatch_control_commands=self._control_command_dispatcher.dispatch,
            set_current_step=lambda step: setattr(self, "_current_step", step),
            get_current_step=lambda: self._current_step,
            set_agent_status=lambda status: object.__setattr__(self, "agent_status", status),
            configured_mpc_config_url=configured_mpc_config_url,
            configured_target_and_constrain_config_url=configured_target_and_constrain_config_url,
            configured_mpc_service_base_url=self._configured_mpc_service_base_url,
        )

        logger.info(f"CentralSchedulingAgent initialized: {self.agent_id}")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化中央调度智能体。

        子类应该：
        1. 使用 self.load_agent_configuration(request) 加载智能体配置
        2. 加载水网拓扑
        3. 初始化优化模型
        4. 通过 MQTT 订阅现地指标
        5. 在状态管理器中注册
        6. 返回 SimTaskInitResponse

        参数:
            request: 任务初始化请求

        返回:
            任务初始化响应
        """
        pass

    @property
    def agent_command_gateway(self) -> AgentCommandGateway:
        return self._agent_command_gateway

    @property
    def target_agent_resolver(self) -> TargetAgentResolver:
        return self._target_agent_resolver

    @property
    def control_command_builder(self) -> MpcControlCommandBuilder:
        return self._control_command_builder

    @property
    def control_command_dispatcher(self) -> ControlCommandDispatcher:
        return self._control_command_dispatcher

    @property
    def mpc_rolling_runtime(self) -> MpcRollingRuntime:
        return self._mpc_rolling_runtime

    def get_or_create_mpc_planning_client(self) -> Optional[MpcPlanningClient]:
        self._mpc_planning_client = self._mpc_optimization_service.get_or_create_mpc_planning_client()
        return self._mpc_planning_client

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行中央调度步进。

        参数:
            request: 步进指令请求

        返回:
            需要通过 MQTT 发送的 MqttMetrics 对象列表（可选）
        """
        logger.debug(f"Central scheduling step {request.step}")

        try:
            self._mpc_rolling_runtime.on_tick(request.step)

            # 返回可选指标
            return None

        except Exception as e:
            logger.error(f"Error in central scheduling step {request.step}: {e}", exc_info=True)
            return None

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        Handle time series updates and activate Java-compatible rolling MPC.

        In the Java central agent, TimeSeriesDataChangedEvent is the first
        trigger that creates MpcTaskState. Later ticks only continue rolling
        after this activation point.
        """
        self._set_agent_logging_context()
        logger.debug("Received central scheduling time series update: commandId=%s", request.command_id)

        try:
            event = request.time_series_data_changed_event
            if event and event.object_time_series:
                for time_series in event.object_time_series:
                    cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._time_series_cache[cache_key] = time_series
                self.on_boundary_condition_update(event.object_time_series)

            self._mpc_rolling_runtime.handle_time_series_changed(event)

            return TimeSeriesDataUpdateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                broadcast=False,
            )
        except Exception as e:
            logger.error("Error handling central scheduling time series update: %s", e, exc_info=True)
            return TimeSeriesDataUpdateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                broadcast=False,
            )

    def on_optimization(self, step: int) -> Optional[List[Any]]:
        """
        执行 MPC 优化逻辑。

        默认实现会调用独立的 MpcPlanningClient，并通过 MpcResultReporter
        回传 mpc_result_report。子类仍可覆盖此方法以接入自定义优化逻辑。

        参数:
            step: 当前仿真步长

        返回:
            需要发送给边缘智能体的控制指令列表，或 None
        """
        mpc_task_state = self._mpc_rolling_runtime.require_mpc_task_state()
        responses = self._mpc_optimization_service.optimize(
            self,
            mpc_task_state,
            step,
        )
        if not responses:
            return None

        return self.control_command_builder.build_from_mpc_responses(responses)

    def list_mpc_sensor_data(self, mpc_task_state: Optional[MpcTaskState] = None) -> List[SensorData]:
        """按 MPC 服务要求的 SensorDTO 形态返回现地指标。"""
        return self._mpc_optimization_service.list_sensor_data(self, mpc_task_state)

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        处理优化的边界条件更新。

        该方法使用新的边界条件更新优化模型。

        参数:
            time_series_list: 更新后的时间序列数据列表
        """
        logger.info(f"Updating optimization model with {len(time_series_list)} boundary conditions")

        # 使用边界条件更新优化模型
        for time_series in time_series_list:
            logger.debug(
                f"Boundary condition: object={time_series.object_name}, "
                f"metrics={time_series.metrics_code}"
            )
            # TODO：更新优化模型约束

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止中央调度智能体。

        子类应该：
        1. 清理优化模型
        2. 取消订阅 MQTT 主题
        3. 从状态管理器中注销
        4. 返回 SimTaskTerminateResponse

        参数:
            request: 任务终止请求

        返回:
            任务终止响应
        """
        pass

    def _initialize_model_context(self) -> None:
        """初始化任务级水利模型上下文，用于对象归属查找。"""
        if ContextManager.get_context(self.context) is not None:
            return

        hydros_objects_modeling_url = self.properties.get_property("hydros_objects_modeling_url")
        param_keys = self.properties.get_property("param_keys", None)
        if isinstance(param_keys, (list, tuple, set)):
            param_keys = set(param_keys)

        ContextManager.create(
            context=self.context,
            hydros_objects_modeling_url=hydros_objects_modeling_url,
            param_keys=param_keys,
        )
