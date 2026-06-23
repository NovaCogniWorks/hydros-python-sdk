"""默认 MPC 中央调度智能体基类。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.mpc.client import MpcPlanningClient
from hydros_agent_sdk.mpc.control_command_builder import MpcControlCommandBuilder
from hydros_agent_sdk.mpc.mpc_result_reporter import MpcResultReporter
from hydros_agent_sdk.mpc.optimization_service import MpcOptimizationService
from hydros_agent_sdk.mpc.rolling_runtime import MpcRollingRuntime
from hydros_agent_sdk.protocol.commands import (
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    AgentStatus,
    SimulationContext,
)
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.sensor_data import SensorData
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

logger = logging.getLogger(__name__)


@dataclass
class MpcSchedulingOptions:
    """默认 MPC 中央调度能力的构造选项。"""

    mpc_config_url: Optional[str] = None
    target_and_constrain_config_url: Optional[str] = None
    mpc_service_base_url: Optional[str] = None
    mpc_request_timeout_seconds: Optional[float] = None
    mpc_planning_client: Optional[MpcPlanningClient] = None
    mpc_result_reporter: Optional[MpcResultReporter] = None
    mpc_sensor_provider: Optional[Callable[..., Iterable[SensorData | Dict[str, Any]]]] = None

    @classmethod
    def from_kwargs(cls, kwargs: Dict[str, Any]) -> "MpcSchedulingOptions":
        """从历史 kwargs 中取出 MPC 相关配置，保持旧构造入口兼容。"""
        return cls(
            mpc_config_url=kwargs.pop("mpc_config_url", None),
            target_and_constrain_config_url=kwargs.pop(
                "target_and_constrain_config_url", None
            ),
            mpc_service_base_url=kwargs.pop("mpc_service_base_url", None),
            mpc_request_timeout_seconds=kwargs.pop(
                "mpc_request_timeout_seconds",
                None,
            ),
            mpc_planning_client=kwargs.pop("mpc_planning_client", None),
            mpc_result_reporter=kwargs.pop("mpc_result_reporter", None),
            mpc_sensor_provider=kwargs.pop("mpc_sensor_provider", None),
        )


class MpcCentralSchedulingAgent(CentralSchedulingAgent):
    """
    使用 SDK 默认 MPC 滚动优化路径的中央调度智能体基类。

    该类负责装配 MpcOptimizationService、MpcRollingRuntime，并保留
    Java 中央调度兼容的“时序更新首次激活 MPC rolling loop”语义。
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
        mpc_options = MpcSchedulingOptions.from_kwargs(kwargs)

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

        self._mpc_options = mpc_options
        self._init_mpc_configuration(mpc_options, sim_coordination_client)
        self._init_default_mpc_runtime(context, mpc_options)

        logger.info(f"MpcCentralSchedulingAgent initialized: {self.agent_id}")

    def _create_control_command_builder(self) -> MpcControlCommandBuilder:
        """创建带 MPC response 转换能力的控制指令 builder。"""
        return MpcControlCommandBuilder(
            source_agent=self,
            get_sibling_agent_instance=self._target_agent_resolver.get_sibling_agent_instance,
            resolve_target_agent_for_object=self._target_agent_resolver.resolve_target_agent_for_object,
        )

    def _init_mpc_configuration(
        self,
        mpc_options: MpcSchedulingOptions,
        sim_coordination_client,
    ) -> None:
        """初始化默认 MPC 能力使用的配置字段。"""
        self._configured_mpc_service_base_url = mpc_options.mpc_service_base_url
        self._configured_mpc_request_timeout_seconds = (
            mpc_options.mpc_request_timeout_seconds
        )
        self._mpc_sensor_provider: Optional[Callable[..., Iterable[SensorData | Dict[str, Any]]]] = (
            mpc_options.mpc_sensor_provider
        )
        self._mpc_planning_client: Optional[MpcPlanningClient] = (
            mpc_options.mpc_planning_client
        )
        self._mpc_result_reporter: MpcResultReporter = (
            mpc_options.mpc_result_reporter
            or MpcResultReporter(sim_coordination_client=sim_coordination_client)
        )

    def _init_default_mpc_runtime(
        self,
        context: SimulationContext,
        mpc_options: MpcSchedulingOptions,
    ) -> None:
        """装配默认 MPC 优化服务和滚动运行时。"""
        self._mpc_optimization_service = MpcOptimizationService(
            properties=self.properties,
            metrics_data_cache=self._metrics_data_cache,
            configured_mpc_service_base_url=self._configured_mpc_service_base_url,
            configured_mpc_request_timeout_seconds=self._configured_mpc_request_timeout_seconds,
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
            configured_mpc_config_url=mpc_options.mpc_config_url,
            configured_target_and_constrain_config_url=(
                mpc_options.target_and_constrain_config_url
            ),
            configured_mpc_service_base_url=self._configured_mpc_service_base_url,
        )

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """执行默认 MPC 滚动调度步进。"""
        logger.debug(f"MPC central scheduling step {request.step}")
        try:
            self._mpc_rolling_runtime.on_tick(request.step)
            return None
        except Exception as e:
            logger.error(f"Error in MPC central scheduling step {request.step}: {e}", exc_info=True)
            return None

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        处理时序更新，并激活兼容 Java 侧的滚动 MPC。

        在 Java 中央智能体中，TimeSeriesDataChangedEvent 是创建调度任务状态
        的第一个触发点。后续 tick 只会在该激活点之后继续滚动。
        """
        logger.debug("Received MPC central scheduling time series update: commandId=%s", request.command_id)

        try:
            event = request.time_series_data_changed_event
            if event and event.object_time_series:
                for time_series in event.object_time_series:
                    cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._time_series_cache[cache_key] = time_series
                self.on_boundary_condition_update(event.object_time_series)

            self._mpc_rolling_runtime.handle_time_series_changed(event)

            return ResponseFactory.time_series_data_update_succeed(self, request)
        except Exception as e:
            logger.error("Error handling MPC central scheduling time series update: %s", e, exc_info=True)
            return ResponseFactory.time_series_data_update_failed(self, request)

    def on_optimization(self, step: int) -> Optional[List[Any]]:
        """
        执行默认 MPC 优化逻辑。

        默认实现会调用独立的 MpcPlanningClient，并通过 MpcResultReporter
        回传 mpc_result_report。子类仍可覆盖此方法以接入自定义优化逻辑。
        """
        task_state = self._mpc_rolling_runtime.require_task_state()
        responses = self._mpc_optimization_service.optimize(
            self,
            task_state,
            step,
        )
        if not responses:
            return None

        return self._control_command_builder.build_from_mpc_responses(responses)
