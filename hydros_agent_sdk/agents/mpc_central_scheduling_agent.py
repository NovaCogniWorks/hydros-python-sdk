"""默认 MPC 中央调度智能体基类。"""

from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.mpc.client import MpcPlanningClient
from hydros_agent_sdk.mpc.control_command_builder import MpcControlCommandBuilder
from hydros_agent_sdk.mpc.control_dispatch_tracker import (
    MpcControlDispatchRecord,
    MpcControlDispatchTracker,
)
from hydros_agent_sdk.mpc.mpc_prediction_result_reporter import MpcPredictionResultReporter
from hydros_agent_sdk.mpc.optimization_service import MpcOptimizationService
from hydros_agent_sdk.mpc.rolling_runtime import MpcRollingRuntime
from hydros_agent_sdk.protocol.agent_commands import (
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.protocol.commands import (
    MpcExecutionStatusReport,
    EdgeControlExecutionReport,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
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
from hydros_agent_sdk.utils import generate_coordination_command_id

logger = logging.getLogger(__name__)


@dataclass
class MpcSchedulingOptions:
    """默认 MPC 中央调度能力的构造选项。"""

    mpc_config_url: Optional[str] = None
    target_and_constrain_config_url: Optional[str] = None
    mpc_service_base_url: Optional[str] = None
    mpc_request_timeout_seconds: Optional[float] = None
    mpc_control_execution_timeout_seconds: float = 120.0
    mpc_planning_client: Optional[MpcPlanningClient] = None
    mpc_prediction_result_reporter: Optional[MpcPredictionResultReporter] = None
    mpc_sensor_provider: Optional[Callable[..., Iterable[SensorData | Dict[str, Any]]]] = None

    @classmethod
    def from_kwargs(cls, kwargs: Dict[str, Any]) -> "MpcSchedulingOptions":
        """从 Agent 构造参数中提取 MPC 配置。"""
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
            mpc_control_execution_timeout_seconds=kwargs.pop(
                "mpc_control_execution_timeout_seconds",
                120.0,
            ),
            mpc_planning_client=kwargs.pop("mpc_planning_client", None),
            mpc_prediction_result_reporter=kwargs.pop("mpc_prediction_result_reporter", None),
            mpc_sensor_provider=kwargs.pop("mpc_sensor_provider", None),
        )


class MpcCentralSchedulingAgent(CentralSchedulingAgent):
    """
    使用 SDK 默认 MPC 滚动优化路径的中央调度智能体基类。

    该类负责装配 MpcOptimizationService、MpcRollingRuntime，并实现
    与 Java central 一致的时序激活、滚动优化和控制终态语义。
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
        self._mpc_dispatch_tracker = MpcControlDispatchTracker()
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
        self._mpc_prediction_result_reporter: MpcPredictionResultReporter = (
            mpc_options.mpc_prediction_result_reporter
            or MpcPredictionResultReporter(sim_coordination_client=sim_coordination_client)
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
            mpc_prediction_result_reporter=self._mpc_prediction_result_reporter,
            mpc_sensor_provider=self._mpc_sensor_provider,
        )
        self._mpc_rolling_runtime = MpcRollingRuntime(
            context=context,
            properties=self.properties,
            optimize_step=self.on_optimization,
            dispatch_control_commands=self._dispatch_and_await_control_commands,
            build_control_commands=self._control_command_builder.build_from_control_plan,
            set_current_step=lambda step: setattr(self, "_current_step", step),
            get_current_step=lambda: self._current_step,
            set_agent_status=lambda status: object.__setattr__(self, "agent_status", status),
            configured_mpc_config_url=mpc_options.mpc_config_url,
            configured_target_and_constrain_config_url=(
                mpc_options.target_and_constrain_config_url
            ),
            configured_mpc_service_base_url=self._configured_mpc_service_base_url,
        )
        self._agent_command_gateway.add_response_listener(self._handle_agent_command_response)

    def _dispatch_and_await_control_commands(
        self,
        commands: List[Any],
        horizon_step: int,
    ) -> None:
        task_state = self._mpc_rolling_runtime.require_task_state()
        plan = task_state.latest_control_plan
        if plan is None:
            raise RuntimeError("MPC control execution plan is not initialized")
        records: List[MpcControlDispatchRecord] = []
        for command in commands:
            if not isinstance(command, HydroStationTargetValueRequest):
                continue
            record = self._mpc_dispatch_tracker.register(
                command=command,
                biz_scene_instance_id=self.context.biz_scene_instance_id,
                optimize_step=plan.optimize_step,
                horizon_step=horizon_step,
            )
            records.append(record)
            self._publish_mpc_execution_status(
                record,
                execution_status="DISPATCHED",
            )

        try:
            self._control_command_dispatcher.dispatch(commands)
        except Exception as error:
            for record in self._mpc_dispatch_tracker.mark_dispatch_failed(records, error):
                self._publish_mpc_execution_status(
                    record,
                    execution_status="FAILED",
                    executed_at=datetime.now().isoformat(),
                    error_code=record.error_code,
                    error_message=record.error_message,
                )

        self._mpc_dispatch_tracker.await_all(
            records,
            self._mpc_options.mpc_control_execution_timeout_seconds,
        )

    def _handle_agent_command_response(self, response) -> None:
        if not isinstance(response, HydroStationTargetValueResponse):
            return
        transition = self._mpc_dispatch_tracker.handle_response(response)
        if transition is None:
            return
        record, execution_status = transition
        self._publish_mpc_execution_status(
            record,
            execution_status=execution_status,
            error_code=response.error_code,
            error_message=response.error_message,
            executed_at=datetime.now().isoformat(),
        )

    def on_station_control_execution(self, report: EdgeControlExecutionReport) -> None:
        transition = self._mpc_dispatch_tracker.handle_execution_report(report)
        if transition is None:
            return
        record, execution_status = transition
        self._publish_mpc_execution_status(
            record,
            execution_status=execution_status,
            error_code=report.error_code,
            error_message=report.error_message,
            executed_at=report.finished_time or datetime.now().isoformat(),
        )

    def _publish_mpc_execution_status(
        self,
        dispatch: MpcControlDispatchRecord,
        execution_status: str,
        dispatched_at: Optional[str] = None,
        executed_at: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        enqueue = getattr(self.sim_coordination_client, "enqueue", None)
        if not callable(enqueue):
            logger.warning(
                "Skip MPC execution status report because the coordination outbox is unavailable: command=%s",
                dispatch.command.command_id,
            )
            return
        enqueue(
            MpcExecutionStatusReport(
                command_id=generate_coordination_command_id(),
                context=self.context,
                broadcast=True,
                source_agent_instance=self,
                optimize_step=dispatch.optimize_step,
                horizon_step=dispatch.horizon_step,
                biz_idem_key=dispatch.biz_idem_key,
                node_id=dispatch.node_id,
                object_id=dispatch.command.object_id,
                object_type=dispatch.command.object_type,
                target_value_type=dispatch.command.target_value_type,
                target_value=dispatch.command.target_value,
                execution_command_id=dispatch.command.command_id,
                dispatch_key=dispatch.dispatch_key,
                execution_status=execution_status,
                dispatched_at=dispatched_at or dispatch.dispatched_at,
                executed_at=executed_at,
                execution_error_code=error_code,
                execution_error_message=error_message,
            )
        )

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """执行默认 MPC 滚动调度步进。"""
        logger.debug(f"MPC central scheduling step {request.step}")
        self._mpc_rolling_runtime.on_tick(request.step)
        return None

    def _close_mpc_runtime(self) -> None:
        """释放当前 task 的 MPC 状态和控制执行关联。"""
        context_id = self.context.biz_scene_instance_id
        self.discard_control_execution_waiters()
        self._mpc_dispatch_tracker.discard_by_biz_scene_instance_id(context_id)
        self._mpc_rolling_runtime.close()

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """停止指令资源并释放当前 task 的 MPC runtime。"""
        logger.info("Terminating MPC central scheduling agent: %s", self.agent_id)
        try:
            self._agent_command_gateway.shutdown()
        finally:
            self._close_mpc_runtime()
        object.__setattr__(self, "agent_status", AgentStatus.TERMINATED)
        return ResponseFactory.terminate_succeed(self, request)

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        处理时序更新，并激活滚动 MPC。

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

        默认实现会调用独立的 MpcPlanningClient，并通过 MpcPredictionResultReporter
        回传 mpc_prediction_result_report。子类仍可覆盖此方法以接入自定义优化逻辑。
        """
        task_state = self._mpc_rolling_runtime.require_task_state()
        return self._mpc_optimization_service.optimize(
            self,
            task_state,
            step,
        )
