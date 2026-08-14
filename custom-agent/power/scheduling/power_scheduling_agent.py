"""
电站 HydroSim 集成的集中调度智能体示例。
"""

import logging
import sys
import tempfile
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

CURRENT_DIR = Path(__file__).resolve().parent
HYDROSIM_DIR = CURRENT_DIR.parent / "mpc"
DATA_DIR = CURRENT_DIR.parent / "data"
RUNTIME_DIR = CURRENT_DIR.parent / ".runtime" / "scheduling"
if str(HYDROSIM_DIR) not in sys.path:
    sys.path.insert(0, str(HYDROSIM_DIR))

from hydrosim_api import HydroSimulationApi
from hydros_agent_sdk import (
    ErrorCodes,
    handle_agent_errors,
)
from hydros_agent_sdk.utils import HydroObjectType
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.mpc.models import DeviceResult, HorizonStep, PredictedResult, ValueItem
from hydros_agent_sdk.mpc.mpc_prediction_result_reporter import MpcPredictionResultReporter
from hydros_agent_sdk.mpc.mpc_result_factory import MpcResultFactory
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.mpc.task_state_lifecycle import MpcTaskStateLifecycle
from hydros_agent_sdk.protocol.commands import (
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.models import AgentStatus, CommandStatus, SimulationContext
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

logger = logging.getLogger(__name__)

POWER_SCHEDULING_RUNTIME_REVISION = "2026-08-04-station-out-flow-control-v10"
POWER_STATION_TURBINE = "POWER_STATION_TURBINE"
POWER_STATION_GATE = "POWER_STATION_GATE"
MPC_STATION_FLOW_COMMAND_TYPE = DeviceValueTypeEnum.WATER_FLOW.code
STATION_DIVERSION_FLOW_SERIES_KEY = "diversion_flow_time_series"


class HydroSimInputFileResolver:
    """解析 HydroSim 输入文件来源，并按需下载远程配置到本地运行目录。"""

    def __init__(self, properties, runtime_dir: Path):
        self._properties = properties
        self._runtime_dir = runtime_dir

    def resolve(
        self,
        url_property_names: List[str],
        path_property_names: List[str],
        default_path: str,
        local_filename: str,
    ) -> str:
        source = self._get_first_configured_value(url_property_names + path_property_names)
        if not source:
            return str(Path(default_path).resolve())
        if self._is_remote_url(source):
            return self._download_to_runtime_dir(source, local_filename)
        configured_path = Path(source).expanduser()
        if configured_path.is_file():
            return str(configured_path.resolve())

        fallback_path = Path(default_path).expanduser()
        if fallback_path.is_file():
            logger.warning(
                "Configured HydroSim input path is unavailable; using bundled fallback: configured=%s, fallback=%s",
                source,
                fallback_path,
            )
            return str(fallback_path.resolve())
        return str(configured_path.resolve())

    def _get_first_configured_value(self, property_names: List[str]) -> Optional[str]:
        for property_name in property_names:
            value = self._properties.get_property(property_name, None)
            if value:
                return str(value).strip()
        return None

    @staticmethod
    def _is_remote_url(value: str) -> bool:
        return value.startswith("http://") or value.startswith("https://")

    def _download_to_runtime_dir(self, source_url: str, local_filename: str) -> str:
        parsed = urlparse(source_url)
        encoded_url = urlunparse(parsed._replace(path=quote(parsed.path, safe="/:@!$&'()*+,;=")))
        request = Request(encoded_url, headers={"User-Agent": "HydrosPythonSdk/1.0"})
        target_path = self._runtime_dir / local_filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(request, timeout=30) as response:
            target_path.write_bytes(response.read())
        logger.info("Downloaded HydroSim input file from %s to %s", source_url, target_path)
        return str(target_path.resolve())


class PowerCentralSchedulingAgent(CentralSchedulingAgent):
    """
    电站 HydroSim 集中调度智能体。

    该智能体沿用 SDK 的集中调度框架，但只会在每个 ``roll_steps`` 滚动周期
    开始时刷新一次调度窗口。窗口刷新后会发布新的时域结果数据，而每个
    tick 仍会执行当前 HydroSim 步并返回该步指标。
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
        configured_mpc_config_url = kwargs.pop("mpc_config_url", None)
        configured_target_and_constrain_config_url = kwargs.pop(
            "target_and_constrain_config_url",
            None,
        )
        mpc_prediction_result_reporter = kwargs.pop(
            "mpc_prediction_result_reporter",
            None,
        )
        # 这些参数原本由 SDK 默认 MPC runtime 消费。迁移后继续接收它们以保持
        # 构造兼容，但电站 Agent 显式拥有自己的 HydroSim 优化链路。
        kwargs.pop("mpc_service_base_url", None)
        kwargs.pop("mpc_request_timeout_seconds", None)
        kwargs.pop("mpc_control_execution_timeout_seconds", None)
        kwargs.pop("mpc_planning_client", None)
        kwargs.pop("mpc_sensor_provider", None)
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
        object.__setattr__(self, "_configured_mpc_config_url", configured_mpc_config_url)
        object.__setattr__(
            self,
            "_configured_target_and_constrain_config_url",
            configured_target_and_constrain_config_url,
        )
        self._mpc_result_reporter = (
            mpc_prediction_result_reporter
            or MpcPredictionResultReporter(sim_coordination_client=sim_coordination_client)
        )
        self._hydrosim_api = HydroSimulationApi()
        self._hydrosim_initialized = False
        self._hydrosim_power_plan_loaded = False
        self._rolling_window_start_step: Optional[int] = None
        self._rolling_window_end_step: Optional[int] = None
        self._rolling_window_dataset: List[HorizonStep] = []
        self._pending_boundary_control_commands: List[Dict[str, Any]] = []
        self._pending_boundary_control_target_step: Optional[int] = None
        self._dispatched_control_target_steps: set[int] = set()
        self._runtime_lock = RLock()
        self._mpc_task_state_lifecycle = MpcTaskStateLifecycle(
            context=context,
            get_current_step=lambda: self._current_step,
            get_rolling_interval_steps=self._resolve_roll_steps,
            get_max_steps=self._resolve_max_steps,
            get_algorithm_config_url=lambda: self._configured_mpc_config_url,
            get_control_config_url=(
                lambda: self._configured_target_and_constrain_config_url
            ),
        )
        self._hydrosim_runtime_dir = RUNTIME_DIR
        self._hydrosim_runtime_dir.mkdir(parents=True, exist_ok=True)
        self._hydrosim_input_resolver = HydroSimInputFileResolver(
            properties=self.properties,
            runtime_dir=self._hydrosim_runtime_dir,
        )
        logger.info(
            "Power central scheduling agent created: %s, runtime_revision=%s",
            agent_id,
            POWER_SCHEDULING_RUNTIME_REVISION,
        )

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initializing power scheduling agent: %s", self.agent_id)

        try:
            self.load_agent_configuration(request)
            self._initialize_optimization_model()
            self._initialize_hydrosim_session()
            # Power planning conversion may take several minutes. The task-init
            # request is broadcast at cluster scope, so finish lightweight
            # registration first and load the plan under the runtime lock on the
            # first Tick/event. This lets the coordinator establish the accepted
            # agentId before a stale SDK can claim the same agentCode.
            logger.info(
                "HydroSim power planning load deferred until first Tick/event: runtime_revision=%s",
                POWER_SCHEDULING_RUNTIME_REVISION,
            )

            self.subscribe_field_metrics()
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

    def _initialize_optimization_model(self) -> None:
        self._optimization_model = {"status": "ready"}

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        with self._runtime_lock:
            self._ensure_hydrosim_initialized()
            self._ensure_hydrosim_power_plan_loaded()
            task_state = self._ensure_mpc_task_state(request.step)

            if self._pending_boundary_control_commands:
                target_step = self._pending_boundary_control_target_step
                if self._can_dispatch_control_for_target_step(request.step, target_step):
                    pending_commands = self._pending_boundary_control_commands
                    self._pending_boundary_control_commands = []
                    self._pending_boundary_control_target_step = None
                    if target_step is None or not self._has_dispatched_control_target_step(target_step):
                        self.dispatch_control_commands_and_await_execution(pending_commands)
                        self._mark_control_target_step_dispatched(target_step)
                else:
                    logger.info(
                        "Deferring pending boundary control commands until target step: currentStep=%s, targetStep=%s, commandCount=%s",
                        request.step,
                        target_step,
                        len(self._pending_boundary_control_commands),
                    )

            control_target_step = self._resolve_next_control_target_step(request.step, task_state)
            if control_target_step is not None:
                logger.info(
                    "Refreshing rolling scheduling window at step=%s for controlTargetStep=%s",
                    request.step,
                    control_target_step,
                )
                commands = self.on_optimization(control_target_step)
                if commands and not self._has_dispatched_control_target_step(control_target_step):
                    self.dispatch_control_commands_and_await_execution(commands)
                    self._mark_control_target_step_dispatched(control_target_step)
                self._refresh_rolling_window_dataset(control_target_step, task_state)
            elif self._should_refresh_rolling_window_report(request.step, task_state):
                logger.info("Refreshing rolling scheduling report at step=%s", request.step)
                self._refresh_rolling_window_dataset(request.step, task_state)

            step_result = self._hydrosim_api.execute_step(step_index=request.step)
            metrics_list = self._build_metrics_from_step_result(step_result)
            return metrics_list

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        session = getattr(self._hydrosim_api, "_session", None)
        if session is None:
            logger.warning("Skip optimization at step=%s because HydroSim session is unavailable.", step)
            return []

        return self._build_station_turbine_out_flow_commands(session, step)

    def _build_station_turbine_out_flow_commands(self, session: Any, step: int) -> List[Dict[str, Any]]:
        station_out_flows: Dict[int, float] = {}
        for device in getattr(session, "latest_device_output_series", []) or []:
            if (
                str(device.get("object_type")) != HydroObjectType.TURBINE.value
                or str(device.get("metrics_code")) != DeviceValueTypeEnum.WATER_FLOW.code
                or device.get("node_id") is None
            ):
                continue
            row = self._get_series_row_for_step(device.get("time_series", []), step)
            if row is None:
                continue
            station_id = int(device["node_id"])
            station_out_flows[station_id] = station_out_flows.get(station_id, 0.0) + float(row["value"])

        commands_by_agent: Dict[str, List[Dict[str, Any]]] = {}
        for station_id, out_flow in station_out_flows.items():
            target_agent = self._target_agent_resolver.resolve_target_agent_for_object(
                object_id=station_id,
                device_type=HydroObjectType.POWER_STATION.value,
            )
            if target_agent is None:
                logger.warning(
                    "Skip station turbine out-flow control because target agent is unavailable: stationId=%s, step=%s",
                    station_id,
                    step,
                )
                continue
            commands_by_agent.setdefault(target_agent.agent_code, []).append(
                {
                    "target_agent_code": target_agent.agent_code,
                    "target_command_type": DeviceValueTypeEnum.WATER_FLOW.code,
                    "target_value": out_flow,
                    "object_id": station_id,
                    "object_type": HydroObjectType.POWER_STATION.value,
                    "main_step_index": step,
                }
            )

        commands: List[Dict[str, Any]] = []
        for target_agent_code, grouped_commands in commands_by_agent.items():
            group_id = (
                f"POWER_STATION_OUT_FLOW:{self.context.biz_scene_instance_id}:"
                f"{step}:{target_agent_code}:{uuid.uuid4()}"
            )
            for command in grouped_commands:
                command["group_id"] = group_id
                command["group_size"] = len(grouped_commands)
                commands.append(command)
        return commands

    def _ensure_mpc_task_state(self, step: int) -> MpcTaskState:
        return self._mpc_task_state_lifecycle.ensure_task_state(step)

    def _activate_mpc_task_state_from_event(self, event: Any, step: Optional[int] = None) -> MpcTaskState:
        existing_task_state = self._peek_mpc_task_state()
        current_step = step
        if existing_task_state is not None and int(existing_task_state.current_step) >= 0:
            current_step = max(int(existing_task_state.current_step), int(step) if step is not None else 0)
        event_step = getattr(event, "auto_schedule_at_step", None)
        if event_step is not None and int(event_step) >= 0:
            current_step = max(int(event_step), int(current_step) if current_step is not None else 0)
        if current_step is None:
            current_step = 0

        task_state = self._ensure_mpc_task_state(current_step)
        if event is not None:
            task_state.register_hydro_event(event)
        return task_state

    def _peek_mpc_task_state(self) -> Optional[MpcTaskState]:
        return self._mpc_task_state_lifecycle.task_state

    def _resolve_roll_steps(self) -> int:
        value = self.properties.get_property("roll_steps", None)
        if value is None:
            return 1
        return max(int(value), 1)

    def _resolve_max_steps(self) -> int:
        session = getattr(self._hydrosim_api, "_session", None)
        if session is None:
            return 0
        step_runtime = getattr(session, "step_runtime", None)
        runtime_steps = getattr(step_runtime, "steps", None)
        if runtime_steps is not None:
            return len(runtime_steps)
        return max([len(item.get("time_series", [])) for item in getattr(session, "latest_station_power_series", [])] or [0])

    def _resolve_window_range(
        self,
        step: int,
        task_state: MpcTaskState,
        window_start_override: Optional[int] = None,
    ) -> Tuple[int, int]:
        roll_steps = max(int(task_state.rolling_interval_steps), 1)
        start_step = int(task_state.start_step)
        max_steps = int(task_state.max_steps)
        if window_start_override is not None:
            window_start = int(window_start_override)
        elif step < start_step:
            window_start = start_step
        else:
            window_index = (step - start_step) // roll_steps
            window_start = start_step + (window_index * roll_steps)
        window_end = window_start + roll_steps - 1
        if max_steps > 0:
            window_end = min(window_end, max_steps - 1)
        return window_start, window_end

    def _should_refresh_rolling_window(self, step: int, task_state: MpcTaskState) -> bool:
        if not self._rolling_window_dataset:
            return True
        return (
            task_state.should_start_new_rolling(step)
            and self._rolling_window_start_step != step
        )

    def _should_refresh_rolling_window_report(self, step: int, task_state: MpcTaskState) -> bool:
        return self._should_refresh_rolling_window(step, task_state)

    def _resolve_next_control_target_step(self, step: int, task_state: MpcTaskState) -> Optional[int]:
        if not self._rolling_window_dataset:
            return int(step)
        target_step = int(step) + 1
        if self._is_control_target_step(target_step, task_state):
            return target_step
        return None

    def _is_control_target_step(self, target_step: int, task_state: MpcTaskState) -> bool:
        if int(task_state.max_steps) > 0 and int(target_step) >= int(task_state.max_steps):
            return False
        return task_state.should_start_new_rolling(int(target_step))

    def _can_dispatch_control_for_target_step(
        self,
        current_step: int,
        target_step: Optional[int],
    ) -> bool:
        if target_step is None:
            return True
        return int(current_step) >= self._edge_entry_step_for_control_target(int(target_step))

    def _edge_entry_step_for_control_target(self, target_step: int) -> int:
        return max(0, int(target_step) - 1)

    def _has_dispatched_control_target_step(self, target_step: Optional[int]) -> bool:
        return target_step is not None and int(target_step) in self._dispatched_control_target_steps

    def _mark_control_target_step_dispatched(self, target_step: Optional[int]) -> None:
        if target_step is not None:
            self._dispatched_control_target_steps.add(int(target_step))

    def _refresh_rolling_window_dataset(
        self,
        step: int,
        task_state: MpcTaskState,
        window_start_override: Optional[int] = None,
    ) -> None:
        window_start, window_end = self._resolve_window_range(
            step,
            task_state,
            window_start_override=window_start_override,
        )
        horizon_steps = self._build_window_horizon_steps(window_start, window_end)
        if not horizon_steps:
            logger.warning(
                "Skip empty MPC rolling report: triggerStep=%s, window=%s-%s, maxSteps=%s",
                step,
                window_start,
                window_end,
                task_state.max_steps,
            )
        self._rolling_window_start_step = window_start
        self._rolling_window_end_step = window_end
        self._rolling_window_dataset = horizon_steps
        self._publish_rolling_window_report(step, task_state, horizon_steps)

    def _publish_rolling_window_report(
        self,
        step: int,
        task_state: MpcTaskState,
        horizon_steps: List[HorizonStep],
    ) -> None:
        if not horizon_steps:
            return

        self._mpc_result_reporter.publish_customize_report(
            source_agent_instance=self,
            mpc_task_state=task_state,
            horizon_step=horizon_steps,
            plan_type="optimal",
        )

    def _build_window_horizon_steps(self, window_start: int, window_end: int) -> List[HorizonStep]:
        session = getattr(self._hydrosim_api, "_session", None)
        if session is None:
            return []

        device_series = getattr(session, "latest_device_output_series", []) or []
        station_series = getattr(session, "latest_station_power_series", []) or []
        horizon_steps: List[HorizonStep] = []
        for relative_step, absolute_step in enumerate(range(window_start, window_end + 1), start=1):
            control_object_list = []
            for device in device_series:
                if not self._is_reportable_window_control_metric(device):
                    continue
                device_row = self._get_series_row_for_step(device.get("time_series", []), absolute_step)
                if device_row is None:
                    continue
                control_object_list.append(
                    MpcResultFactory.build_control_object_result(
                        object_id=int(device["object_id"]),
                        object_name=device.get("object_name"),
                        object_type=self._resolve_window_report_object_type(str(device["object_type"])),
                        target_value_list=[
                            ValueItem(
                                value_type=str(device["metrics_code"]),
                                value=float(device_row["value"]),
                            )
                        ],
                    )
                )

            predicted_result_list = self._build_station_predicted_results(
                device_series=device_series,
                station_series=station_series,
                step=absolute_step,
            )

            if not control_object_list and not predicted_result_list:
                continue
            horizon_steps.append(
                HorizonStep(
                    horizon_step=relative_step,
                    control_object_list=control_object_list,
                    predicted_result_list=predicted_result_list,
                )
            )
        return horizon_steps

    def _build_station_predicted_results(
        self,
        device_series: List[Dict[str, Any]],
        station_series: List[Dict[str, Any]],
        step: int,
    ) -> List[PredictedResult]:
        station_ids: List[int] = []
        station_names: Dict[int, str] = {}
        for station in station_series:
            node_id = station.get("node_id")
            if node_id is None:
                continue
            station_id = int(node_id)
            if station_id not in station_ids:
                station_ids.append(station_id)
            station_names[station_id] = str(station.get("station") or station.get("object_name") or f"Station-{station_id}")

        for device in device_series:
            node_id = device.get("node_id")
            if node_id is None:
                continue
            station_id = int(node_id)
            if station_id not in station_ids:
                station_ids.append(station_id)

        session = getattr(self._hydrosim_api, "_session", None)
        step_runtime = getattr(session, "step_runtime", None)
        merged_event = getattr(step_runtime, "merged_event", {}) or {}
        for item in merged_event.get("object_time_series", []) or []:
            if item.get("object_type") != HydroObjectType.STATION.value:
                continue
            object_ids = item.get("object_ids") or []
            if item.get("object_id") is not None:
                object_ids = list(object_ids) + [item["object_id"]]
            for object_id in object_ids:
                station_id = int(object_id)
                if station_id not in station_ids:
                    station_ids.append(station_id)
                station_names.setdefault(
                    station_id,
                    str(item.get("object_name") or f"Station-{station_id}"),
                )
        for station_id in (getattr(step_runtime, "target_stage_by_node", {}) or {}).keys():
            normalized_station_id = int(station_id)
            if normalized_station_id not in station_ids:
                station_ids.append(normalized_station_id)
            station_names.setdefault(normalized_station_id, f"Station-{normalized_station_id}")

        predicted_results = []
        for station_id in station_ids:
            station_name = station_names.get(station_id, f"Station-{station_id}")
            front_water_level = self._resolve_station_front_water_level(station_id=station_id, step=step)
            final_target_water_level = self._resolve_station_target_water_level(station_id=station_id, step=step)
            back_water_level = self._resolve_station_back_water_level(
                station_ids=station_ids,
                station_id=station_id,
                step=step,
            )
            station_out_flow = self._sum_device_metric_for_station_step(
                device_series=device_series,
                station_id=station_id,
                object_type=HydroObjectType.TURBINE.value,
                metrics_code=DeviceValueTypeEnum.WATER_FLOW.code,
                step=step,
            )
            station_diversion_flow = self._sum_device_metric_for_station_step(
                device_series=device_series,
                station_id=station_id,
                object_type=HydroObjectType.GATE.value,
                metrics_code=DeviceValueTypeEnum.WATER_FLOW.code,
                step=step,
            )
            station_diversion_flow = self._resolve_station_diversion_flow(
                station_series=station_series,
                station_id=station_id,
                step=step,
                gate_flow=station_diversion_flow,
            )
            station_efficiency = self._sum_device_metric_for_station_step(
                device_series=device_series,
                station_id=station_id,
                object_type=HydroObjectType.TURBINE.value,
                metrics_code=DeviceValueTypeEnum.OUTPUT_POWER.code,
                step=step,
            )
            turbine_device_results = self._build_station_device_results(
                device_series, station_id, step, HydroObjectType.TURBINE.value
            )
            gate_device_results = self._build_station_device_results(
                device_series, station_id, step, HydroObjectType.GATE.value
            )
            if station_out_flow is not None or station_efficiency is not None or turbine_device_results:
                predicted_results.append(
                    MpcResultFactory.build_predicted_result(
                        object_id=station_id,
                        object_type=POWER_STATION_TURBINE,
                        object_name=station_name,
                        target_value=self._value_item(MPC_STATION_FLOW_COMMAND_TYPE, station_out_flow),
                        predicted_value_list=self._build_station_prediction_values(
                            front_water_level=front_water_level,
                            final_target_water_level=final_target_water_level,
                            back_water_level=back_water_level,
                            out_flow=station_out_flow,
                            diversion_flow=None,
                            efficiency=station_efficiency,
                        ),
                        device_result_list=turbine_device_results,
                    )
                )

            if station_diversion_flow is not None or gate_device_results:
                predicted_results.append(
                    MpcResultFactory.build_predicted_result(
                        object_id=station_id,
                        object_type=POWER_STATION_GATE,
                        object_name=station_name,
                        target_value=self._value_item(MPC_STATION_FLOW_COMMAND_TYPE, station_diversion_flow),
                        predicted_value_list=self._build_station_prediction_values(
                            front_water_level=front_water_level,
                            final_target_water_level=final_target_water_level,
                            back_water_level=back_water_level,
                            out_flow=None,
                            diversion_flow=station_diversion_flow,
                            efficiency=None,
                        ),
                        device_result_list=gate_device_results,
                    )
                )
        return predicted_results

    def _resolve_station_diversion_flow(
        self,
        station_series: List[Dict[str, Any]],
        station_id: int,
        step: int,
        gate_flow: Optional[float],
    ) -> Optional[float]:
        for station in station_series:
            if int(station.get("node_id", -1)) != int(station_id):
                continue
            row = self._get_series_row_for_step(
                station.get(STATION_DIVERSION_FLOW_SERIES_KEY, []),
                step,
            )
            if row is not None:
                return float(row["value"])
        return gate_flow

    def _build_station_device_results(
        self,
        device_series: List[Dict[str, Any]],
        station_id: int,
        step: int,
        object_type: str,
    ) -> List[DeviceResult]:
        results: List[DeviceResult] = []
        for device in device_series:
            if device.get("node_id") is None or int(device["node_id"]) != station_id:
                continue
            if str(device.get("object_type", "")).lower() != object_type.lower():
                continue
            row = self._get_series_row_for_step(device.get("time_series", []), step)
            if row is None:
                continue
            results.append(
                DeviceResult(
                    object_type=self._resolve_window_report_object_type(object_type),
                    object_id=int(device["object_id"]),
                    object_name=device.get("object_name"),
                    value_list=[
                        ValueItem(
                            value_type=str(device["metrics_code"]),
                            value=float(row["value"]),
                        )
                    ],
                )
            )
        return results

    @staticmethod
    def _value_item(value_type: str, value: Optional[float]) -> Optional[ValueItem]:
        if value is None:
            return None
        return ValueItem(value_type=value_type, value=float(value))

    @classmethod
    def _build_station_prediction_values(
        cls,
        *,
        front_water_level: Optional[float],
        final_target_water_level: Optional[float],
        back_water_level: Optional[float],
        out_flow: Optional[float],
        diversion_flow: Optional[float],
        efficiency: Optional[float],
    ) -> List[ValueItem]:
        values = (
            ("front_water_level", front_water_level),
            ("final_target_water_level", final_target_water_level),
            ("back_water_level", back_water_level),
            ("out_flow", out_flow),
            ("diversion_flow", diversion_flow),
            ("efficiency", efficiency),
        )
        return [
            ValueItem(value_type=value_type, value=float(value))
            for value_type, value in values
            if value is not None
        ]

    def _sum_device_metric_for_station_step(
        self,
        device_series: List[Dict[str, Any]],
        station_id: int,
        object_type: str,
        metrics_code: str,
        step: int,
    ) -> Optional[float]:
        total = 0.0
        found = False
        for device in device_series:
            if int(device.get("node_id", -1)) != int(station_id):
                continue
            if str(device.get("object_type")) != object_type:
                continue
            if str(device.get("metrics_code")) != metrics_code:
                continue
            device_row = self._get_series_row_for_step(device.get("time_series", []), step)
            if device_row is None:
                continue
            total += float(device_row["value"])
            found = True
        if not found:
            return None
        return total

    def _resolve_station_front_water_level(self, station_id: int, step: int) -> Optional[float]:
        session = getattr(self._hydrosim_api, "_session", None)
        step_runtime = getattr(session, "step_runtime", None)
        merged_event = getattr(step_runtime, "merged_event", {}) or {}
        for item in merged_event.get("object_time_series", []) or []:
            if item.get("object_type") != HydroObjectType.STATION.value:
                continue
            if item.get("metrics_code") != DeviceValueTypeEnum.WATER_LEVEL.code:
                continue
            object_ids = item.get("object_ids") or []
            if item.get("object_id") is not None:
                object_ids = list(object_ids) + [item["object_id"]]
            if int(station_id) not in [int(object_id) for object_id in object_ids]:
                continue
            row = self._get_series_row_for_step(item.get("time_series", []), step)
            if row is not None:
                return float(row["value"])
        return self._resolve_station_target_water_level(station_id=station_id, step=step)

    def _resolve_station_target_water_level(self, station_id: int, step: int) -> Optional[float]:
        session = getattr(self._hydrosim_api, "_session", None)
        step_runtime = getattr(session, "step_runtime", None)
        target_stage_by_node = getattr(step_runtime, "target_stage_by_node", {}) or {}
        values = target_stage_by_node.get(int(station_id))
        if values is None:
            return None
        if 0 <= int(step) < len(values):
            return float(values[int(step)])
        return None

    def _resolve_station_back_water_level(
        self,
        station_ids: List[int],
        station_id: int,
        step: int,
    ) -> Optional[float]:
        ordered_station_ids = sorted({int(item) for item in station_ids})
        if int(station_id) not in ordered_station_ids:
            return None
        station_index = ordered_station_ids.index(int(station_id))
        if station_index + 1 >= len(ordered_station_ids):
            return None
        downstream_station_id = ordered_station_ids[station_index + 1]
        return self._resolve_station_front_water_level(station_id=downstream_station_id, step=step)

    def _is_reportable_control_metric(self, device: Dict[str, Any]) -> bool:
        object_type = str(device.get("object_type"))
        metrics_code = str(device.get("metrics_code"))
        return (
            object_type == HydroObjectType.TURBINE.value
            and metrics_code == DeviceValueTypeEnum.OUTPUT_POWER.code
        ) or (
            object_type == HydroObjectType.GATE.value
            and metrics_code == DeviceValueTypeEnum.GATE_OPENING.code
        )

    def _is_reportable_window_control_metric(self, device: Dict[str, Any]) -> bool:
        return self._is_reportable_control_metric(device)

    def _resolve_window_report_object_type(self, object_type: str) -> str:
        if object_type == HydroObjectType.TURBINE.value:
            return POWER_STATION_TURBINE
        if object_type == HydroObjectType.GATE.value:
            return POWER_STATION_GATE
        return object_type

    def _get_series_row_for_step(self, time_series: List[Dict[str, Any]], step: int) -> Optional[Dict[str, Any]]:
        for row in time_series:
            if int(row.get("step", -1)) == int(step):
                return row
        if 0 <= step < len(time_series):
            return time_series[step]
        return None

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
            time_series_file=self._resolve_hydrosim_input_file(
                url_property_names=["hydrosim_time_series_url"],
                path_property_names=["hydrosim_time_series_file"],
                default_path=str(DATA_DIR / "time_series_power_planning.json"),
                local_filename="time_series_power_planning.json",
            ),
            mpc_config_file=self._resolve_hydrosim_input_file(
                url_property_names=["mpc_config_url", "hydrosim_mpc_config_url"],
                path_property_names=["hydrosim_mpc_config_file"],
                default_path=str(DATA_DIR / "mpc_config.yaml"),
                local_filename="mpc_config.yaml",
            ),
            initial_states_file=self._resolve_hydrosim_input_file(
                url_property_names=["init_state_config_url", "hydrosim_initial_states_url"],
                path_property_names=["hydrosim_initial_states_file"],
                default_path=str(DATA_DIR / "initial_states.yaml"),
                local_filename="initial_states.yaml",
            ),
            constraints_file=self._resolve_hydrosim_input_file(
                url_property_names=["target_and_constrain_config_url", "hydrosim_constraints_url"],
                path_property_names=["hydrosim_constraints_file"],
                default_path=str(DATA_DIR / "constrains_targets.yaml"),
                local_filename="constrains_targets.yaml",
            ),
        )
        self._hydrosim_initialized = True
        logger.info("HydroSim scheduling session initialized: session=%s", init_result["session"]["session_id"])

    def _ensure_hydrosim_initialized(self) -> None:
        if not self._hydrosim_initialized:
            self._initialize_hydrosim_session()

    def _ensure_hydrosim_power_plan_loaded(self) -> None:
        if self._hydrosim_power_plan_loaded:
            return
        started_at = time.monotonic()
        planning_file, cleanup_path = self._resolve_power_planning_file_for_load()
        logger.info(
            "HydroSim power planning load started: file=%s, runtime_revision=%s",
            planning_file,
            POWER_SCHEDULING_RUNTIME_REVISION,
        )
        try:
            try:
                result = self._hydrosim_api.get_station_power_planning_series(planning_file)
            except ValueError:
                logger.info(
                    "Power planning file has no Station/output_power series; trying inflow-driven planning: %s",
                    planning_file,
                )
                result = self._hydrosim_api.get_station_power_planning_series_from_inflow(planning_file)
        finally:
            if cleanup_path is not None and cleanup_path.exists():
                cleanup_path.unlink(missing_ok=True)
        self._hydrosim_power_plan_loaded = True
        logger.info(
            "HydroSim power planning loaded: stations=%s, elapsed_seconds=%.3f",
            len(result.get("station_power_series", [])),
            time.monotonic() - started_at,
        )

    def _resolve_hydrosim_input_file(
        self,
        url_property_names: List[str],
        path_property_names: List[str],
        default_path: str,
        local_filename: str,
    ) -> str:
        return self._hydrosim_input_resolver.resolve(
            url_property_names=url_property_names,
            path_property_names=path_property_names,
            default_path=default_path,
            local_filename=local_filename,
        )

    def _resolve_power_planning_file_for_load(self) -> Tuple[str, Optional[Path]]:
        planning_url = self.properties.get_property("objects_time_series_url", None)
        if planning_url:
            temp_file = tempfile.NamedTemporaryFile(
                prefix="hydrosim_power_plan_",
                suffix=".json",
                delete=False,
            )
            temp_path = Path(temp_file.name)
            temp_file.close()
            parsed = urlparse(str(planning_url))
            encoded_url = urlunparse(parsed._replace(path=quote(parsed.path, safe="/:@!$&'()*+,;=")))
            request = Request(encoded_url, headers={"User-Agent": "HydrosPythonSdk/1.0"})
            with urlopen(request, timeout=30) as response:
                temp_path.write_bytes(response.read())
            logger.info("Downloaded HydroSim power planning file from %s to %s", planning_url, temp_path)
            return str(temp_path.resolve()), temp_path

        planning_file = self._resolve_hydrosim_input_file(
            url_property_names=["hydrosim_power_planning_url"],
            path_property_names=["hydrosim_power_planning_file"],
            default_path=str(DATA_DIR / "time_series_power_planning.json"),
            local_filename="time_series_power_planning.json",
        )
        return planning_file, None

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        with self._runtime_lock:
            logger.info("Time series update received: commandId=%s", request.command_id)
            event = request.time_series_data_changed_event
            task_state = self._activate_mpc_task_state_from_event(event)
            self._refresh_hydrosim_session_from_event(event)
            self._refresh_rolling_window_for_boundary_change(task_state.current_step, task_state)

        return TimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_outflow_time_series_data_update(
        self,
        request: OutflowTimeSeriesDataUpdateRequest,
    ) -> OutflowTimeSeriesDataUpdateResponse:
        with self._runtime_lock:
            logger.info("Outflow time series update received: commandId=%s", request.command_id)
            event = request.outflow_time_series_data_changed_event
            task_state = self._activate_mpc_task_state_from_event(event)
            self._refresh_hydrosim_session_from_event(event)
            self._refresh_rolling_window_for_boundary_change(task_state.current_step, task_state)

        return OutflowTimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )

    def _refresh_hydrosim_session_from_event(self, event: Any) -> None:
        if event is None or not getattr(event, "object_time_series", None):
            return

        self._ensure_hydrosim_initialized()
        self._ensure_hydrosim_power_plan_loaded()
        current_step = self._resolve_event_current_step(event)
        current_step_metrics = self._build_current_step_metrics_for_hydrosim(current_step)
        refresh_result = self._hydrosim_api.apply_time_series_event_update(
            event,
            current_step=current_step,
            current_step_metrics=current_step_metrics,
        )
        logger.debug(
            "HydroSim session refreshed from event: source=%s, step=%s, cacheMetrics=%s, updatedSeries=%s, stations=%s, devices=%s",
            getattr(event, "hydro_event_source_type", None),
            current_step,
            len(current_step_metrics),
            refresh_result.get("updated_time_series_count", 0),
            len(refresh_result.get("station_power_series", []) or []),
            len(refresh_result.get("device_output_series", []) or []),
        )

    def _refresh_rolling_window_for_boundary_change(
        self,
        current_step: int,
        task_state: MpcTaskState,
    ) -> None:
        effective_control_step = self._resolve_effective_control_step(current_step)
        commands = self.on_optimization(effective_control_step)
        self._pending_boundary_control_commands = list(commands or [])
        self._pending_boundary_control_target_step = (
            int(effective_control_step) if self._pending_boundary_control_commands else None
        )
        self._refresh_rolling_window_dataset(
            effective_control_step,
            task_state,
            window_start_override=effective_control_step,
        )

    def _resolve_effective_control_step(self, current_step: int) -> int:
        max_steps = self._resolve_max_steps()
        effective_step = max(0, int(current_step) + 1)
        if max_steps > 0:
            effective_step = min(effective_step, max(0, int(max_steps) - 1))
        return effective_step

    def _resolve_event_current_step(self, event: Any) -> int:
        task_state = self._peek_mpc_task_state()
        active_step = None
        if task_state is not None and getattr(task_state, "current_step", None) is not None:
            active_step = int(task_state.current_step)
        event_step = getattr(event, "auto_schedule_at_step", None)
        if event_step is not None and int(event_step) >= 0:
            return max(int(event_step), active_step if active_step is not None else 0)
        return active_step if active_step is not None else 0

    def _build_current_step_metrics_for_hydrosim(self, current_step: int) -> List[Dict[str, Any]]:
        metrics_at_step = self._metrics_data_cache.by_step(current_step)
        metrics_source = metrics_at_step.values() if metrics_at_step else self._metrics_data_cache.latest_metrics.values()
        overrides: List[Dict[str, Any]] = []
        for metrics_data in metrics_source:
            object_id = metrics_data.get("object_id")
            metrics_code = metrics_data.get("metrics_code")
            value = metrics_data.get("value")
            object_type = metrics_data.get("object_type")
            if object_id is None or not metrics_code or value is None or not object_type:
                continue
            overrides.append(
                {
                    "object_id": int(object_id),
                    "object_type": str(object_type),
                    "metrics_code": str(metrics_code),
                    "value": float(value),
                }
            )
        return overrides

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        with self._runtime_lock:
            logger.info("Stopping power scheduling agent: %s", self.agent_id)
            self._optimization_model = None

            if self._hydrosim_initialized:
                try:
                    self._hydrosim_api.cancel()
                except Exception:
                    logger.warning("Failed to cancel HydroSim session during terminate.", exc_info=True)
            self._hydrosim_initialized = False
            self._hydrosim_power_plan_loaded = False
            self._rolling_window_start_step = None
            self._rolling_window_end_step = None
            self._rolling_window_dataset = []
            self._pending_boundary_control_commands = []
            self._pending_boundary_control_target_step = None
            self._dispatched_control_target_steps.clear()
            self.discard_control_execution_waiters()
            self._mpc_task_state_lifecycle.clear()
            self._agent_command_gateway.shutdown()
            object.__setattr__(self, "agent_status", AgentStatus.TERMINATED)
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )
