"""
中央调度智能体示例。

本模块展示如何基于 MpcCentralSchedulingAgent 接入电站 HydroSim 算法。
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

CURRENT_DIR = Path(__file__).resolve().parent
HYDROSIM_DIR = CURRENT_DIR.parent / "mpc"
DATA_DIR = CURRENT_DIR.parent / "data"
if str(HYDROSIM_DIR) not in sys.path:
    sys.path.insert(0, str(HYDROSIM_DIR))

from hydrosim_api import HydroSimulationApi
from hydros_agent_sdk import (
    load_env_config,
    ErrorCodes,
    handle_agent_errors,
    DeviceValueTypeEnum,
    HydroObjectType,
)
from hydros_agent_sdk.agents.mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentStatus,
)
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

logger = logging.getLogger(__name__)


class PumpCentralSchedulingAgent(MpcCentralSchedulingAgent):
    """
    水电站中央调度智能体。

    该实现复用 MpcCentralSchedulingAgent 的滚动调度能力，并通过
    HydroSimulationApi 的 initialize/get_station_power_planning_series/execute_step
    链路返回每步设备级仿真结果。
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
        **kwargs,
    ):
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            **kwargs,
        )
        self._hydrosim_api = HydroSimulationApi()
        self._hydrosim_initialized = False
        self._hydrosim_power_plan_loaded = False
        logger.info("中央调度智能体实例已创建: %s", agent_id)

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("正在初始化智能体: %s", self.agent_id)

        try:
            self.load_agent_configuration(request)
            self._initialize_optimization_model()
            self._initialize_hydrosim_session()
            self._ensure_hydrosim_power_plan_loaded()

            env_config = load_env_config()
            base_metrics_topic = env_config.get("metrics_topic")
            if base_metrics_topic:
                cluster_id = env_config.get("hydros_cluster_id", "hydros-k3s-testing")
                base_metrics_topic = base_metrics_topic.replace("{hydros_cluster_id}", cluster_id)
                task_id = self.context.biz_scene_instance_id
                full_metrics_topic = f"{base_metrics_topic.rstrip('/')}/{task_id}"
                logger.info("订阅渲染后的现地数据主题: %s", full_metrics_topic)
                self._metrics_subscriber.subscribe(full_metrics_topic)

            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)
            self._agent_command_gateway.start()

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
            self._agent_command_gateway.shutdown()
            raise

    def _initialize_optimization_model(self):
        logger.info("正在加载 MPC 优化模型...")
        self._optimization_model = {"status": "ready"}
        logger.info("优化模型已就绪")

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行每步仿真，并返回算法真实生成的设备级结果：
        - 各水轮机：`power`、`water_flow`
        - 各闸门：`water_flow`、`gate_opening`
        """
        super().on_tick_simulation(request)
        self._ensure_hydrosim_initialized()
        self._ensure_hydrosim_power_plan_loaded()

        step_result = self._hydrosim_api.execute_step(step_index=request.step)
        metrics_list = self._build_metrics_from_step_result(step_result)
        logger.info("step=%s HydroSim execute_step 返回设备指标 %s 条", request.step, len(metrics_list))
        return metrics_list

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        logger.info("--- 第 %s 步：开始执行 MPC 滚动优化 ---", step)
        logger.info("求解器正在运行中...")
        logger.info("优化完成，开始下发控制指令")
        return [
            {
                "target_agent_code": "PUMP_AGENT_001",
                "target_command_type": DeviceValueTypeEnum.OUTPUT_POWER.code,
                "target_value": 85.5,
                "object_id": 1021,
                "object_type": HydroObjectType.TURBINE,
            },
            {
                "target_agent_code": "GATE_AGENT_002",
                "target_command_type": DeviceValueTypeEnum.GATE_OPENING.code,
                "target_value": 1.2,
                "object_id": 1041,
                "object_type": HydroObjectType.GATE,
            },
        ]

    def _build_metrics_from_step_result(self, step_result: Dict[str, Any]) -> List[MqttMetrics]:
        metrics_list: List[MqttMetrics] = []
        for item in step_result.get("device_step_outputs") or []:
            metrics_list.append(
                MqttMetrics(
                    source_id=self.agent_code,
                    job_instance_id=self.biz_scene_instance_id,
                    object_id=int(item["object_id"]),
                    object_name=str(item["object_name"]),
                    step_index=int(item["step"]),
                    source_timestamp_ms=int(time.time() * 1000),
                    metrics_code=str(item["metrics_code"]),
                    value=float(item["value"]),
                )
            )
        return metrics_list

    def _initialize_hydrosim_session(self) -> None:
        init_result = self._hydrosim_api.initialize(
            time_series_file=self._get_hydrosim_property(
                "hydrosim_time_series_file",
                str(DATA_DIR / "time_series_power_planning.json"),
            ),
            mpc_config_file=self._get_hydrosim_property(
                "hydrosim_mpc_config_file",
                str(DATA_DIR / "mpc_config.yaml"),
            ),
            initial_states_file=self._get_hydrosim_property(
                "hydrosim_initial_states_file",
                str(DATA_DIR / "initial_states.yaml"),
            ),
            constraints_file=self._get_hydrosim_property(
                "hydrosim_constraints_file",
                str(DATA_DIR / "constrains_targets.yaml"),
            ),
        )
        self._hydrosim_initialized = True
        logger.info("HydroSim initialized for scheduling, session=%s", init_result["session"]["session_id"])

    def _ensure_hydrosim_initialized(self) -> None:
        if not self._hydrosim_initialized:
            self._initialize_hydrosim_session()

    def _ensure_hydrosim_power_plan_loaded(self) -> None:
        if self._hydrosim_power_plan_loaded:
            return
        result = self._hydrosim_api.get_station_power_planning_series(
            self._get_hydrosim_property(
                "hydrosim_power_planning_file",
                str(DATA_DIR / "time_series_power_planning.json"),
            )
        )
        self._hydrosim_power_plan_loaded = True
        logger.info(
            "HydroSim power planning loaded, stations=%s",
            len(result.get("station_power_series", [])),
        )

    def _get_hydrosim_property(self, key: str, default: str) -> str:
        value = self.properties.get_property(key, default)
        return str(Path(value).resolve())

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        logger.info("--- 收到时间序列数据更新：%s ---", request.command_id)
        event = request.time_series_data_changed_event
        for obj_ts in event.object_time_series:
            logger.info("对象 %s 的指标 %s 已更新", obj_ts.object_name, obj_ts.metrics_code)
            if obj_ts.time_series:
                first_val = obj_ts.time_series[0]
                logger.debug("首个数据点: Step=%s, Value=%s", first_val.step, first_val.value)

        return TimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest) -> OutflowTimeSeriesDataUpdateResponse:
        logger.info("--- 收到出流量时间序列数据更新：%s ---", request.command_id)
        event = request.outflow_time_series_data_changed_event
        if event and event.object_time_series:
            for obj_ts in event.object_time_series:
                if obj_ts.time_series:
                    first_val = obj_ts.time_series[0]
                    logger.debug("首个数据点: Step=%s, Value=%s", first_val.step, first_val.value)

        return OutflowTimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("正在停止中央调度智能体: %s", self.agent_id)
        self._agent_command_gateway.shutdown()
        self._optimization_model = None

        if self._hydrosim_initialized:
            try:
                self._hydrosim_api.cancel()
            except Exception:
                logger.warning("Failed to cancel HydroSim session during terminate.", exc_info=True)
        self._hydrosim_initialized = False
        self._hydrosim_power_plan_loaded = False

        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )
