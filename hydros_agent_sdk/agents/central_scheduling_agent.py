"""
中央调度智能体通用基类。

CentralSchedulingAgent 提供不默认装配 MPC 的中央调度通用能力。
"""

import logging
from typing import Optional, List, Dict
from abc import abstractmethod

from hydros_agent_sdk.agent_commands.dispatching import ControlCommandDispatcher
from hydros_agent_sdk.agent_commands.target_value_builder import StationTargetValueCommandBuilder
from hydros_agent_sdk.agent_commands.transport import AgentCommandClient, AgentCommandGateway
from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache
from hydros_agent_sdk.runtime.env_settings import load_runtime_env_settings
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.transport.mqtt_metrics_subscriber import MqttMetricsSubscriber
from hydros_agent_sdk.agents.target_agent_resolver import TargetAgentResolver
from hydros_agent_sdk.utils.property_parse_utils import PropertyParseUtils
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
    AgentStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


DEFAULT_METRICS_HISTORY_STEPS = 10


class CentralSchedulingAgent(TickableAgent):
    """
    中央调度智能体兼容基类。

    该基类只负责中央调度 Agent 的通用协作能力：
    1. 通过 MQTT 订阅接收来自现地设备的实时指标
    2. 处理边界条件更新
    3. 通过 agent command 客户端发送智能体间控制指令
    4. 持有算法可选使用的模型、拓扑和指标缓存

    默认 MPC 滚动优化路径由 MpcCentralSchedulingAgent 承载。

    核心特性：
    - 通过 MQTT 订阅实时现地指标
    - 边界条件处理
    - 支持智能体间指令交互

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

        self._init_command_dispatching(
            sim_coordination_client=sim_coordination_client,
            hydros_cluster_id=hydros_cluster_id,
            context=context,
            object_agent_code_map=configured_object_agent_code_map,
        )
        self._init_model_state()
        self._init_field_metrics(sim_coordination_client)

        logger.info(f"CentralSchedulingAgent initialized: {self.agent_id}")

    def _init_command_dispatching(
        self,
        sim_coordination_client,
        hydros_cluster_id: str,
        context: SimulationContext,
        object_agent_code_map: Optional[Dict[str, str]],
    ) -> None:
        """装配中央调度下发智能体指令所需的协作对象。"""
        self._object_agent_code_map: Dict[str, str] = {
            str(object_id): agent_code
            for object_id, agent_code in (object_agent_code_map or {}).items()
        }
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
        self._control_command_builder = self._create_control_command_builder()
        self._control_command_dispatcher = ControlCommandDispatcher(
            send_command=lambda command: self._agent_command_gateway.send_command(command),
            build_station_target_value_request=self._control_command_builder.build_station_target_value_request,
        )

    def _create_control_command_builder(self) -> StationTargetValueCommandBuilder:
        """创建中央调度控制指令 builder，子类可覆盖以扩展转换能力。"""
        return StationTargetValueCommandBuilder(
            source_agent=self,
            get_sibling_agent_instance=self._target_agent_resolver.get_sibling_agent_instance,
            resolve_target_agent_for_object=self._target_agent_resolver.resolve_target_agent_for_object,
        )

    def _init_model_state(self) -> None:
        """初始化中央调度算法可复用的模型和拓扑占位。"""
        self._optimization_model = None
        self._topology = None

    def _init_field_metrics(self, sim_coordination_client) -> None:
        """初始化现地设备实时指标缓存和 MQTT 订阅适配器。"""
        self._metrics_data_cache = FieldMetricsCache(max_steps=DEFAULT_METRICS_HISTORY_STEPS)
        self._field_metrics_cache = self._metrics_data_cache.latest_metrics
        self._field_metrics_step_cache = self._metrics_data_cache.metrics_by_step
        self._metrics_subscriber = MqttMetricsSubscriber(
            mqtt_client=sim_coordination_client.mqtt_client,
            metrics_data_cache=self._metrics_data_cache,
        )

    def subscribe_field_metrics(self, metrics_topic: Optional[str] = None) -> Optional[str]:
        """订阅当前任务的现地指标 topic，并返回实际订阅的完整 topic。"""
        settings = load_runtime_env_settings()
        base_topic = metrics_topic or PropertyParseUtils.get_string(
            self.properties,
            "metrics_topic",
            settings.metrics_topic,
        )
        if not base_topic:
            logger.info("No field metrics topic configured for central scheduling agent: %s", self.agent_id)
            return None

        cluster_id = self.cluster_id or settings.hydros_cluster_id or ""
        rendered_topic = settings.render_topic(str(base_topic), cluster_id=cluster_id)
        if not rendered_topic:
            logger.info("No rendered field metrics topic for central scheduling agent: %s", self.agent_id)
            return None

        task_id = self.context.biz_scene_instance_id
        full_topic = f"{rendered_topic.rstrip('/')}/{task_id}"
        if self._metrics_subscriber.subscription_topic == full_topic:
            logger.info("Field metrics topic already subscribed for central scheduling agent: %s", full_topic)
            return full_topic

        logger.info("Subscribing central field metrics topic: %s", full_topic)
        self._metrics_subscriber.subscribe(full_topic)
        return full_topic

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

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行中央调度步进。

        参数:
            request: 步进指令请求

        返回:
            需要通过 MQTT 发送的 MqttMetrics 对象列表（可选）
        """
        logger.debug(f"Central scheduling step {request.step}")
        return None

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        处理时序更新并刷新中央调度的边界条件缓存。
        """
        logger.debug("Received central scheduling time series update: commandId=%s", request.command_id)

        try:
            event = request.time_series_data_changed_event
            if event and event.object_time_series:
                for time_series in event.object_time_series:
                    cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._time_series_cache[cache_key] = time_series
                self.on_boundary_condition_update(event.object_time_series)

            return ResponseFactory.time_series_data_update_succeed(self, request)
        except Exception as e:
            logger.error("Error handling central scheduling time series update: %s", e, exc_info=True)
            return ResponseFactory.time_series_data_update_failed(self, request)

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
            # 待办：更新优化模型约束

    def get_metrics_topic(self) -> str:
        """
        Get the MQTT topic for sending metrics data.

        Returns:
            MQTT topic string for central scheduling metrics
        """
        return f"/hydros/simulation/jobs/{self.biz_scene_instance_id}/centralscheduling/objects"

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
