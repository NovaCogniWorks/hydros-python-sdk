"""
具备 MPC 优化能力的中央调度智能体。

该模块提供了 CentralSchedulingAgent 类，它扩展了 TickableAgent，
增加了模型预测控制（MPC）优化功能。
"""

import json
import inspect
import logging
from dataclasses import dataclass, field
from threading import RLock
from typing import Optional, List, Dict, Any, Callable, Iterable
from abc import abstractmethod

from hydros_agent_sdk.agent_commands.models import (
    AgentCommand,
    DeviceValueTypeEnum,
    DisturbanceNodeWaterFlowRequest,
    HydroDirectGateOpeningRequest,
    HydroStationTargetValueRequest,
)
from hydros_agent_sdk.agent_commands.transport import AgentCommandClient
from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.mpc.client import MpcPlanningClient
from hydros_agent_sdk.mpc.models import MpcOptimizeResponse, SensorData
from hydros_agent_sdk.mpc.reporter import MpcResultReporter
from hydros_agent_sdk.runtime import load_runtime_env_settings
from hydros_agent_sdk.utils import generate_agent_command_id
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
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentStatus,
    AgentDriveMode,
    HydroAgentInstance,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


@dataclass
class MpcTaskState:
    """Runtime state for one Java-compatible rolling MPC loop."""

    context: SimulationContext
    rolling_interval_steps: int
    start_step: int
    current_step: int = -1
    total_steps: int = 36
    current_loop: int = 1
    mpc_config_url: Optional[str] = None
    target_and_constrain_config_url: Optional[str] = None
    hydro_events: List[TimeSeriesDataChangedEvent] = field(default_factory=list)

    def register_hydro_event(self, event: TimeSeriesDataChangedEvent) -> None:
        self.hydro_events.append(event)

    def active_new_rolling(self, current_step: int) -> bool:
        if self.rolling_interval_steps <= 0:
            return False
        step_delta = current_step - self.start_step
        return (
            step_delta % self.rolling_interval_steps == 0
            and step_delta != 0
            and current_step - self.total_steps != 0
        )


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
            optimization_horizon=10  # 每 10 个 tick 优化一次
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
        optimization_horizon: int = 10,
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
            optimization_horizon: 滚动优化周期（tick 数）
            agent_status: 初始业务状态
            drive_mode: 智能体驱动模式（默认：SIM_TICK_DRIVEN）
            agent_configuration_url: 可选的配置 URL
            **kwargs: 其他关键字参数
        """
        configured_total_steps = kwargs.pop("total_steps", None)
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
        self._optimization_horizon = optimization_horizon
        self._last_optimization_step = 0
        self._configured_total_steps = configured_total_steps
        self._configured_mpc_config_url = configured_mpc_config_url
        self._configured_target_and_constrain_config_url = configured_target_and_constrain_config_url
        self._configured_mpc_service_base_url = configured_mpc_service_base_url
        self._mpc_task_state: Optional[MpcTaskState] = None
        self._time_series_update_lock = RLock()
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

        # 优化模型与拓扑
        self._optimization_model = None
        self._topology = None

        # 现地设备实时指标缓存
        self._field_metrics_cache: Dict[str, Any] = {}
        self._field_metrics_step_cache: Dict[int, Dict[str, Any]] = {}

        # 现地指标订阅主题
        self._metrics_subscription_topic = None

        # agent command 客户端按需懒加载
        self._agent_command_client: Optional[AgentCommandClient] = None
        self._agent_command_client_started = False

        logger.info(f"CentralSchedulingAgent initialized: {self.agent_id}")
        logger.info(f"Optimization horizon: {self._optimization_horizon} ticks")

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

    def send_command(self, command: AgentCommand) -> None:
        """将 agent command 交给专用客户端发送，客户端按需懒加载。"""
        self._start_agent_command_client()
        self._get_or_create_agent_command_client().send_command(command)

    def get_sibling_agent_instance(self, agent_code: str) -> Optional[HydroAgentInstance]:
        """按 agent_code 查找同任务下的兄弟智能体。"""
        callback = getattr(self.sim_coordination_client, "sim_coordination_callback", None)
        if callback is None:
            return None

        getter = getattr(callback, "get_sibling_agent_instance", None)
        if getter is None:
            return None

        biz_scene_instance_id = self.context.biz_scene_instance_id if self.context else None
        return getter(agent_code=agent_code, biz_scene_instance_id=biz_scene_instance_id)

    def _build_station_target_value_request(
        self,
        target_agent_code: str,
        target_command_type: str,
        target_value: Any,
        object_id: int,
        object_type: str,
    ) -> Optional[HydroStationTargetValueRequest]:
        """把内部控制指令转换成站点目标值请求。"""
        target_agent = self.get_sibling_agent_instance(target_agent_code)
        if target_agent is None:
            logger.warning(f"未找到兄弟智能体: {target_agent_code}")
            return None

        try:
            value_type = DeviceValueTypeEnum.from_code(target_command_type)
        except ValueError:
            logger.warning(f"不支持的目标值类型: {target_command_type}")
            return None

        if target_value is None:
            logger.warning(f"控制指令缺少有效目标值: target={target_agent_code}, type={target_command_type}")
            return None

        return HydroStationTargetValueRequest(
            command_id=generate_agent_command_id(),
            context=self.context,
            source=self,
            target=target_agent,
            object_id=object_id,
            object_type=object_type,
            target_value_type=value_type.code,
            target_value=target_value,
            need_ack_reply=True,
        )

    def _get_or_create_agent_command_client(self) -> AgentCommandClient:
        if self._agent_command_client is None:
            self._agent_command_client = AgentCommandClient(
                broker_url=self.sim_coordination_client.broker_url,
                broker_port=self.sim_coordination_client.broker_port,
                hydros_cluster_id=self.hydros_cluster_id,
                state_manager=self.state_manager,
                mqtt_username=getattr(self.sim_coordination_client, "mqtt_username", None),
                mqtt_password=getattr(self.sim_coordination_client, "mqtt_password", None),
            )
        return self._agent_command_client

    def _start_agent_command_client(self) -> None:
        if self._agent_command_client_started:
            return
        self._get_or_create_agent_command_client().start()
        self._agent_command_client_started = True

    def _shutdown_agent_command_client(self) -> None:
        if self._agent_command_client is None:
            return
        if not self._agent_command_client_started:
            return
        self._agent_command_client.stop()
        self._agent_command_client_started = False

    def get_roll_steps(self) -> int:
        """Return the rolling interval, matching Java roll_steps fallback rules."""
        return self._get_int_property("roll_steps", self._optimization_horizon)

    def get_total_steps(self) -> int:
        """Return total task steps used to avoid rolling again at task end."""
        default_total_steps = self._configured_total_steps
        if default_total_steps is None:
            default_total_steps = 36
        return self._get_int_property("total_steps", default_total_steps)

    def get_mpc_config_url(self) -> Optional[str]:
        return self._get_string_property("mpc_config_url", self._configured_mpc_config_url)

    def get_target_and_constrain_config_url(self) -> Optional[str]:
        return self._get_string_property(
            "target_and_constrain_config_url",
            self._configured_target_and_constrain_config_url,
        )

    def get_mpc_service_base_url(self) -> Optional[str]:
        configured_url = self._get_string_property(
            "mpc_service_base_url",
            self._configured_mpc_service_base_url,
        )
        if configured_url:
            return configured_url

        return load_runtime_env_settings().mpc_service_base_url

    def should_auto_start_mpc_on_tick(self) -> bool:
        """Whether ticks may activate MPC before a time-series update arrives."""
        return self._get_bool_property("auto_start_mpc_on_tick", True)

    def get_or_create_mpc_planning_client(self) -> Optional[MpcPlanningClient]:
        if self._mpc_planning_client is not None:
            return self._mpc_planning_client

        base_url = self.get_mpc_service_base_url()
        if not base_url:
            return None
        self._mpc_planning_client = MpcPlanningClient(base_url=base_url)
        return self._mpc_planning_client

    def is_mpc_optimizing_on_the_loop(self) -> bool:
        """Whether the task has already activated its rolling MPC loop."""
        return self._mpc_task_state is not None

    @property
    def mpc_task_state(self) -> Optional[MpcTaskState]:
        return self._mpc_task_state

    def _get_int_property(self, name: str, default: Optional[int]) -> int:
        value = self.properties.get_property(name, default)
        if value is None:
            raise ValueError(f"Missing integer property: {name}")
        return int(value)

    def _get_string_property(self, name: str, default: Optional[str]) -> Optional[str]:
        value = self.properties.get_property(name, default)
        if value is None:
            return None
        return str(value)

    def _get_bool_property(self, name: str, default: bool) -> bool:
        value = self.properties.get_property(name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "on")
        return bool(value)

    def subscribe_to_field_metrics(self, metrics_topic: str):
        """
        订阅 MQTT 主题以获取实时现地指标。

        该方法订阅现地设备发布其实时指标数据的主题。

        参数:
            metrics_topic: 现地指标的 MQTT 主题
        """
        logger.info(f"Subscribing to field metrics topic: {metrics_topic}")

        self._metrics_subscription_topic = metrics_topic

        # 用 paho-mqtt 的主题级回调把消息路由到现地指标处理函数
        self.sim_coordination_client.mqtt_client.message_callback_add(
            metrics_topic,
            lambda client, userdata, msg: self._on_field_metrics_received_wrapper(msg)
        )
        self.sim_coordination_client.mqtt_client.subscribe(metrics_topic)

        logger.info(f"Subscribed to field metrics: {metrics_topic}")

    def _on_field_metrics_received_wrapper(self, msg):
        """先解析 MQTT 消息负载，再进入业务逻辑处理。"""
        try:
            import json
            payload = json.loads(msg.payload.decode("utf-8"))
            self._on_field_metrics_received(msg.topic, payload)
        except Exception as e:
            logger.error(f"Error parsing field metrics payload on {msg.topic}: {e}")

    def _on_field_metrics_received(self, topic: str, payload: Dict[str, Any]):
        """
        通过 MQTT 接收现地指标的回调。

        当接收到现地指标时调用此方法。
        它更新内部缓存以用于优化。

        参数:
            topic: MQTT 主题
            payload: 指标负载
        """
        logger.debug(f"Received field metrics from topic: {topic}")

        try:
            # 解析指标字段
            object_id = payload.get('object_id')
            metrics_code = payload.get('metrics_code')
            value = payload.get('value')
            step_index = payload.get('step_index')
            object_type = payload.get('object_type')
            position_code = payload.get('position_code')
            if position_code != "none":
                logger.debug(
                    "Skipped field metrics because position_code is not none: object_id=%s, "
                    "metrics_code=%s, position_code=%s",
                    object_id,
                    metrics_code,
                    position_code,
                )
                return

            if object_id is not None and metrics_code:
                cache_key = f"{object_id}_{metrics_code}"
                self._field_metrics_cache[cache_key] = {
                    'object_id': object_id,
                    'object_type': object_type,
                    'metrics_code': metrics_code,
                    'position_code': position_code,
                    'value': value,
                    'step_index': step_index,
                }

                if step_index is not None:
                    self._field_metrics_step_cache.setdefault(int(step_index), {})
                    self._field_metrics_step_cache[int(step_index)][cache_key] = {
                        'object_id': object_id,
                        'object_type': object_type,
                        'metrics_code': metrics_code,
                        'position_code': position_code,
                        'value': value,
                        'step_index': int(step_index),
                    }
                    self._trim_field_metrics_step_cache()

                logger.debug(f"Cached field metrics: {cache_key} = {value}")

        except Exception as e:
            logger.error(f"Error processing field metrics: {e}", exc_info=True)

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
            with self._time_series_update_lock:
                self._current_step = request.step
                if not self.is_mpc_optimizing_on_the_loop():
                    if not self.should_auto_start_mpc_on_tick():
                        logger.debug(
                            "MPC rolling loop has not been activated yet and auto-start is disabled: "
                            "bizSceneInstanceId=%s, step=%s",
                            self.context.biz_scene_instance_id,
                            request.step,
                        )
                        return None

                    self._activate_mpc_from_tick(request.step)
                    return None

                mpc_task_state = self._require_mpc_task_state()
                mpc_task_state.current_step = request.step
                mpc_task_state.total_steps = self.get_total_steps()
                should_roll = mpc_task_state.active_new_rolling(request.step)

                logger.debug(
                    "MPC rolling check: bizSceneInstanceId=%s, startStep=%s, "
                    "currentStep=%s, rollStep=%s, shouldRoll=%s",
                    self.context.biz_scene_instance_id,
                    mpc_task_state.start_step,
                    request.step,
                    mpc_task_state.rolling_interval_steps,
                    should_roll,
                )

                if should_roll:
                    self._do_rolling_optimal(mpc_task_state)
                    self._last_optimization_step = request.step

                object.__setattr__(self, "agent_status", AgentStatus.ACTIVE)

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

            self._handle_time_series_changed(event)

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

    def _handle_time_series_changed(self, event: Optional[TimeSeriesDataChangedEvent]) -> None:
        if event is None or not event.object_time_series:
            raise ValueError("time series update event has no object_time_series")

        with self._time_series_update_lock:
            rolling_interval_steps = self.get_roll_steps()
            if rolling_interval_steps <= 0:
                raise ValueError(f"roll_steps must be positive: {rolling_interval_steps}")

            if event.auto_schedule_at_step is not None and event.auto_schedule_at_step > self._current_step:
                self._current_step = event.auto_schedule_at_step

            current_step = self._current_step
            total_steps = self.get_total_steps()

            logger.info(
                "MPC time series event: bizSceneInstanceId=%s, currentStep=%s, "
                "isOnTheLoop=%s, rollingIntervalSteps=%s, eventType=%s, eventSource=%s, timeSeriesCount=%s",
                self.context.biz_scene_instance_id,
                current_step,
                self.is_mpc_optimizing_on_the_loop(),
                rolling_interval_steps,
                event.hydro_event_type,
                event.hydro_event_source_type,
                len(event.object_time_series),
            )

            if not self.is_mpc_optimizing_on_the_loop():
                mpc_config_url = self.get_mpc_config_url()
                target_and_constrain_config_url = self.get_target_and_constrain_config_url()
                logger.debug(
                    "MPC config URLs resolved from agent properties: bizSceneInstanceId=%s, "
                    "mpcConfigUrl=%s, controlConfigUrl=%s",
                    self.context.biz_scene_instance_id,
                    mpc_config_url,
                    target_and_constrain_config_url,
                )
                mpc_task_state = MpcTaskState(
                    context=self.context,
                    rolling_interval_steps=rolling_interval_steps,
                    start_step=current_step,
                    current_step=current_step,
                    total_steps=total_steps,
                    mpc_config_url=mpc_config_url,
                    target_and_constrain_config_url=target_and_constrain_config_url,
                )
                mpc_task_state.register_hydro_event(event)
                self._mpc_task_state = mpc_task_state
                self._do_rolling_optimal(mpc_task_state)
                self._last_optimization_step = current_step
                object.__setattr__(self, "agent_status", AgentStatus.ACTIVE)
                return

            mpc_task_state = self._require_mpc_task_state()
            mpc_task_state.rolling_interval_steps = rolling_interval_steps
            mpc_task_state.current_step = current_step
            mpc_task_state.total_steps = total_steps
            mpc_task_state.register_hydro_event(event)

    def _activate_mpc_from_tick(self, current_step: int) -> None:
        rolling_interval_steps = self.get_roll_steps()
        if rolling_interval_steps <= 0:
            raise ValueError(f"roll_steps must be positive: {rolling_interval_steps}")

        mpc_config_url = self.get_mpc_config_url()
        target_and_constrain_config_url = self.get_target_and_constrain_config_url()
        logger.debug(
            "MPC config URLs resolved from agent properties: bizSceneInstanceId=%s, "
            "mpcConfigUrl=%s, controlConfigUrl=%s",
            self.context.biz_scene_instance_id,
            mpc_config_url,
            target_and_constrain_config_url,
        )

        mpc_task_state = MpcTaskState(
            context=self.context,
            rolling_interval_steps=rolling_interval_steps,
            start_step=current_step,
            current_step=current_step,
            total_steps=self.get_total_steps(),
            mpc_config_url=mpc_config_url,
            target_and_constrain_config_url=target_and_constrain_config_url,
        )
        self._mpc_task_state = mpc_task_state

        logger.info(
            "MPC rolling loop auto-started by tick: bizSceneInstanceId=%s, "
            "startStep=%s, rollStep=%s, totalSteps=%s",
            self.context.biz_scene_instance_id,
            mpc_task_state.start_step,
            mpc_task_state.rolling_interval_steps,
            mpc_task_state.total_steps,
        )
        self._do_rolling_optimal(mpc_task_state)
        self._last_optimization_step = current_step
        object.__setattr__(self, "agent_status", AgentStatus.ACTIVE)

    def _require_mpc_task_state(self) -> MpcTaskState:
        if self._mpc_task_state is None:
            raise RuntimeError("mpc_task_state is not initialized")
        return self._mpc_task_state

    def _do_rolling_optimal(self, mpc_task_state: MpcTaskState) -> Optional[List[Any]]:
        logger.info(
            "Executing MPC optimization: bizSceneInstanceId=%s, step=%s",
            self.context.biz_scene_instance_id,
            mpc_task_state.current_step,
        )
        control_commands = self.on_optimization(mpc_task_state.current_step)
        mpc_task_state.current_loop += 1
        if control_commands:
            self._send_control_commands(control_commands)
        logger.info("MPC optimization completed at step %s", mpc_task_state.current_step)
        return control_commands

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
        mpc_task_state = self._require_mpc_task_state()
        mpc_client = self.get_or_create_mpc_planning_client()
        if mpc_client is None:
            logger.warning(
                "MPC planning client is not configured; skip default optimization at step %s",
                step,
            )
            return None

        sensor_data = self.list_mpc_sensor_data(mpc_task_state)
        logger.debug(
            "MPC sensorData prepared: bizSceneInstanceId=%s, step=%s, sensorDataCount=%s",
            self.context.biz_scene_instance_id,
            step,
            len(sensor_data),
        )
        if not sensor_data:
            logger.warning(
                "MPC sensorData is empty before optimization: bizSceneInstanceId=%s, "
                "step=%s, fieldMetricsCacheSize=%s",
                self.context.biz_scene_instance_id,
                step,
                len(self._field_metrics_cache),
            )

        responses = mpc_client.execute_optimization(
            mpc_task_state,
            sensor_data,
            sensor_provider=lambda: self.list_mpc_sensor_data(mpc_task_state),
        )
        if not responses:
            return None

        self._mpc_result_reporter.publish(self, mpc_task_state, responses)
        return self._build_control_commands_from_mpc_responses(responses)

    def list_mpc_sensor_data(self, mpc_task_state: Optional[MpcTaskState] = None) -> List[SensorData]:
        """Return field metrics in the SensorDTO shape required by the MPC service."""
        if self._mpc_sensor_provider is not None:
            provider = self._mpc_sensor_provider
            try:
                signature = inspect.signature(provider)
                if len(signature.parameters) >= 2:
                    provided = provider(self, mpc_task_state)
                elif len(signature.parameters) == 1:
                    provided = provider(mpc_task_state)
                else:
                    provided = provider()
            except (TypeError, ValueError):
                provided = provider()
            return [
                item if isinstance(item, SensorData) else SensorData.model_validate(item)
                for item in (provided or [])
            ]

        return [
            SensorData.model_validate(value)
            for value in self._field_metrics_cache.values()
        ]

    def _build_control_commands_from_mpc_responses(
        self,
        responses: List[MpcOptimizeResponse],
    ) -> List[AgentCommand]:
        control_commands: List[AgentCommand] = []
        for response in responses:
            if (response.plan_type or "").upper() != "OPTIMAL":
                logger.debug(
                    "Skip MPC response for control command build: plan_type=%s",
                    response.plan_type,
                )
                continue
            if not response.horizon_controls:
                logger.debug(
                    "Skip MPC response for control command build: empty horizon_controls, plan_type=%s",
                    response.plan_type,
                )
                continue
            first_control = response.horizon_controls[0]
            for device_opening in first_control.opening_list or []:
                if device_opening.value is None:
                    logger.debug(
                        "Skip MPC device opening without value: objectId=%s, deviceType=%s",
                        device_opening.object_id,
                        device_opening.device_type,
                    )
                    continue
                target_agent = self.resolve_target_agent_for_object(
                    object_id=device_opening.object_id,
                    device_type=device_opening.device_type,
                )
                if target_agent is None:
                    logger.warning(
                        "Cannot resolve target agent for MPC control: objectId=%s, deviceType=%s",
                        device_opening.object_id,
                        device_opening.device_type,
                    )
                    continue

                if device_opening.device_type == "Gate":
                    control_commands.append(
                        HydroDirectGateOpeningRequest(
                            command_id=generate_agent_command_id(),
                            source=self,
                            target=target_agent,
                            object_id=device_opening.object_id,
                            object_name=device_opening.object_name,
                            object_type=device_opening.device_type,
                            gate_opening=device_opening.value,
                            need_ack_reply=True,
                        )
                    )
                else:
                    control_commands.append(
                        DisturbanceNodeWaterFlowRequest(
                            command_id=generate_agent_command_id(),
                            source=self,
                            target=target_agent,
                            object_id=device_opening.node_id,
                            object_name=device_opening.node_name,
                            object_type=device_opening.device_type,
                            value=device_opening.value,
                            need_ack_reply=True,
                        )
                    )
        logger.info(
            "Built %s control commands from %s MPC responses",
            len(control_commands),
            len(responses or []),
        )
        return control_commands

    def resolve_target_agent_for_object(
        self,
        object_id: Optional[int],
        device_type: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        """Resolve the edge agent that owns the hydro object receiving MPC control."""
        if object_id is None:
            return None

        agent_code = self._resolve_configured_agent_code_for_object(object_id)
        if agent_code:
            target_agent = self.get_sibling_agent_instance(agent_code)
            if target_agent is not None:
                return target_agent
            logger.warning(
                "Configured object-agent mapping resolved agent_code but sibling agent is unavailable: "
                "objectId=%s, deviceType=%s, agentCode=%s",
                object_id,
                device_type,
                agent_code,
            )

        callback = getattr(self.sim_coordination_client, "sim_coordination_callback", None)
        if callback is None:
            return None

        resolver = getattr(callback, "get_agent_by_object_id", None)
        if resolver is None:
            return None

        biz_scene_instance_id = self.context.biz_scene_instance_id if self.context else None
        try:
            return resolver(object_id=object_id, biz_scene_instance_id=biz_scene_instance_id)
        except TypeError:
            return resolver(object_id)

    def _resolve_configured_agent_code_for_object(self, object_id: int) -> Optional[str]:
        """Resolve configured agent code by object id, falling back to parent top object id."""
        agent_code = self._object_agent_code_map.get(str(object_id))
        if agent_code:
            return agent_code

        model_context = ContextManager.get_context(self.context)
        topology = getattr(model_context, "topology", None) if model_context is not None else None
        if topology is None:
            return None

        parent_id = topology.child_to_parent_map.get(int(object_id))
        if parent_id is None:
            return None
        return self._object_agent_code_map.get(str(parent_id))

    def _send_control_commands(self, control_commands: List[Any]):
        """
        向目标智能体发送控制指令。

        这里统一把“控制指令描述”转换成真正的 agent command 并发送，
        这样上层优化逻辑只负责产生命令意图。

        参数:
            control_commands: 控制指令列表
        """
        logger.info(f"Sending {len(control_commands)} control commands to agents")

        for command in control_commands:
            if isinstance(command, AgentCommand):
                self.send_command(command)
                continue

            target_agent_code = command.get('target_agent_code')
            target_command_type = command.get('target_command_type')
            target_value = command.get('target_value')
            object_id = command.get('object_id')
            object_type = command.get('object_type')

            logger.debug(
                f"Control command: target={target_agent_code}, "
                f"type={target_command_type}, value={target_value}, object_id={object_id}"
            )

            if not target_agent_code or not target_command_type:
                logger.warning(f"控制指令缺少必要字段，已跳过: {command}")
                continue

            command_request = self._build_station_target_value_request(
                target_agent_code=target_agent_code,
                target_command_type=target_command_type,
                target_value=target_value,
                object_id=object_id,
                object_type=object_type,
            )
            if command_request is not None:
                self.send_command(command_request)

    def get_field_metrics_value(
        self,
        object_id: int,
        metrics_code: str
    ) -> Optional[float]:
        """
        从缓存中获取现地指标值。

        参数:
            object_id: 对象 ID
            metrics_code: 指标代码

        返回:
            现地指标值，如果未找到则返回 None
        """
        cache_key = f"{object_id}_{metrics_code}"
        metrics_data = self._field_metrics_cache.get(cache_key)

        if metrics_data:
            return metrics_data.get('value')

        return None

    def get_field_metrics_by_step(self, step_index: int) -> Dict[str, Dict[str, Any]]:
        """
        获取指定步长的现地指标缓存。

        参数:
            step_index: 仿真步长

        返回:
            该步长下的指标快照
        """
        return dict(self._field_metrics_step_cache.get(int(step_index), {}))

    def get_field_metrics_history(self) -> Dict[int, Dict[str, Dict[str, Any]]]:
        """
        获取最近缓存的步长指标历史。

        返回:
            按步长分组的指标缓存
        """
        return {step: dict(metrics) for step, metrics in self._field_metrics_step_cache.items()}

    def _trim_field_metrics_step_cache(self) -> None:
        """只保留 optimization_horizon 范围内的步长缓存。"""
        if self._optimization_horizon <= 0:
            self._field_metrics_step_cache.clear()
            return

        step_indexes = sorted(self._field_metrics_step_cache.keys())
        excess_count = len(step_indexes) - self._optimization_horizon
        if excess_count <= 0:
            return

        for step_index in step_indexes[:excess_count]:
            self._field_metrics_step_cache.pop(step_index, None)

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

    @property
    def optimization_horizon(self) -> int:
        """获取优化时界（tick 数）。"""
        return self._optimization_horizon

    @property
    def last_optimization_step(self) -> int:
        """获取最后一次优化步长。"""
        return self._last_optimization_step

    def _initialize_model_context(self) -> None:
        """Initialize task-scoped hydro model context for object owner lookup."""
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
            self._load_object_agent_code_map()
            self._subscribe_configured_field_metrics()

            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)
            self._start_agent_command_client()

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
            self._shutdown_agent_command_client()
            raise

    def _load_object_agent_code_map(self) -> None:
        raw_mapping = self.properties.get_property("object_agent_code_map", None)
        if not raw_mapping:
            return

        if isinstance(raw_mapping, dict):
            mapping = raw_mapping
        else:
            mapping = json.loads(str(raw_mapping))

        self._object_agent_code_map = {
            str(object_id): str(agent_code)
            for object_id, agent_code in mapping.items()
        }
        logger.info("Loaded object-agent mapping entries: %s", len(self._object_agent_code_map))

    def _subscribe_configured_field_metrics(self) -> None:
        metrics_topic = self._get_metrics_topic()
        if not metrics_topic:
            logger.info("No metrics topic configured; MPC will rely on injected/provider sensor data")
            return

        task_id = self.context.biz_scene_instance_id
        full_topic = f"{metrics_topic.rstrip('/')}/{task_id}"
        logger.info("Subscribing system central field metrics topic: %s", full_topic)
        self.subscribe_to_field_metrics(full_topic)

    def _get_metrics_topic(self) -> Optional[str]:
        settings = load_runtime_env_settings()
        metrics_topic = self._get_string_property("metrics_topic", settings.metrics_topic)
        if not metrics_topic:
            return None

        cluster_id = self.cluster_id or settings.hydros_cluster_id or ""
        return settings.render_topic(str(metrics_topic), cluster_id=cluster_id)

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("Terminating system central scheduling agent: %s", self.agent_id)

        self._shutdown_agent_command_client()
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
