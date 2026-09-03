"""
电站 HydroSim 集成的集中调度智能体示例。
"""

import logging
import sys
import tempfile
import time
import uuid
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

CURRENT_DIR = Path(__file__).resolve().parent
HYDROSIM_DIR = CURRENT_DIR.parent / "mpc"
DATA_DIR = CURRENT_DIR.parent / "data"
RUNTIME_DIR = CURRENT_DIR.parent / ".runtime" / "scheduling"
if str(HYDROSIM_DIR) not in sys.path:
    sys.path.insert(0, str(HYDROSIM_DIR))

from hydrosim import config as hydrosim_config
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
    HydroEventCommand,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
    OutflowTimeSeriesResponse,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.events import OutflowPlanningEvent
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    CommandStatus,
    ObjectTimeSeries,
    SimulationContext,
    TimeSeriesValue,
)
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

logger = logging.getLogger(__name__)

POWER_SCHEDULING_RUNTIME_REVISION = "2026-08-24-central-outflow-planning-v11"
POWER_STATION_TURBINE = "POWER_STATION_TURBINE"
POWER_STATION_GATE = "POWER_STATION_GATE"
MPC_STATION_FLOW_COMMAND_TYPE = DeviceValueTypeEnum.WATER_FLOW.code
MPC_STATION_POWER_COMMAND_TYPE = DeviceValueTypeEnum.OUTPUT_POWER.code
MPC_GATE_OPENING_COMMAND_TYPE = DeviceValueTypeEnum.GATE_OPENING.code
MPC_GATE_STATION_FLOW_COMMAND_TYPE = DeviceValueTypeEnum.WATER_FLOW.code
STATION_DIVERSION_FLOW_SERIES_KEY = "diversion_flow_time_series"
RESERVOIR_EVIDENCE_SERIES_KEY = "reservoir_evidence_time_series"
DEFAULT_POWER_PLAN_PRELOAD_WAIT_SECONDS = 360.0


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
        self._hydrosim_power_plan_preload_done = Event()
        self._hydrosim_power_plan_preload_thread: Optional[Thread] = None
        self._hydrosim_power_plan_preload_error: Optional[Exception] = None
        self._hydrosim_power_plan_preload_started_at: Optional[float] = None
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
            # registration first and then warm the plan in the background. This
            # preserves the accepted agentId ordering without making STEP_1 run
            # the full configured HydroSim conversion on the tick ACK path.
            logger.info(
                "HydroSim power planning load scheduled for background preload: runtime_revision=%s",
                POWER_SCHEDULING_RUNTIME_REVISION,
            )

            self.subscribe_field_metrics()
            self._agent_command_gateway.start()

            object.__setattr__(self, "agent_status", AgentStatus.ACTIVE)
            self._start_hydrosim_power_plan_preload()
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
        self._await_hydrosim_power_plan_preload_for_command(
            command_name="tick",
            step=request.step,
        )
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
            logger.info(
                "Power internal scheduling runtime advanced at step=%s; "
                "skip publishing internal prediction outputs as ordinary MqttMetrics: "
                "stationOutputs=%s, deviceOutputs=%s",
                request.step,
                len(step_result.get("station_step_outputs") or []),
                len(step_result.get("device_step_outputs") or []),
            )
            return []

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        session = getattr(self._hydrosim_api, "_session", None)
        if session is None:
            logger.warning("Skip optimization at step=%s because HydroSim session is unavailable.", step)
            return []

        power_commands = self._build_station_output_power_commands(
            session,
            step,
            assign_groups=False,
        )
        if power_commands:
            return self._with_gate_station_flow_control_commands(
                session=session,
                step=step,
                base_commands=power_commands,
                group_prefix="POWER_STATION_OUTPUT_POWER",
            )
        logger.warning(
            "No station output-power control command is available at step=%s; fallback to station water-flow command.",
            step,
        )
        flow_commands = self._build_station_turbine_out_flow_commands(
            session,
            step,
            assign_groups=False,
        )
        return self._with_gate_station_flow_control_commands(
            session=session,
            step=step,
            base_commands=flow_commands,
            group_prefix="POWER_STATION_OUT_FLOW",
        )

    def _build_station_output_power_commands(
        self,
        session: Any,
        step: int,
        *,
        assign_groups: bool = True,
    ) -> List[Dict[str, Any]]:
        station_output_powers: Dict[int, float] = {}
        for station in getattr(session, "latest_station_power_series", []) or []:
            metrics_code = station.get("metrics_code")
            if metrics_code is not None and str(metrics_code) != DeviceValueTypeEnum.OUTPUT_POWER.code:
                continue
            object_type = station.get("object_type")
            if object_type is not None and str(object_type) not in {
                HydroObjectType.STATION.value,
                HydroObjectType.POWER_STATION.value,
            }:
                continue
            station_id = station.get("node_id", station.get("object_id"))
            if station_id is None:
                continue
            row = self._get_series_row_for_step(station.get("time_series", []), step)
            if row is None:
                continue
            station_output_powers[int(station_id)] = float(row["value"])

        if not station_output_powers:
            for device in getattr(session, "latest_device_output_series", []) or []:
                if (
                    str(device.get("object_type")) != HydroObjectType.TURBINE.value
                    or str(device.get("metrics_code")) != DeviceValueTypeEnum.OUTPUT_POWER.code
                    or device.get("node_id") is None
                ):
                    continue
                row = self._get_series_row_for_step(device.get("time_series", []), step)
                if row is None:
                    continue
                station_id = int(device["node_id"])
                station_output_powers[station_id] = station_output_powers.get(station_id, 0.0) + float(row["value"])

        return self._build_station_target_commands(
            station_values=station_output_powers,
            step=step,
            target_command_type=MPC_STATION_POWER_COMMAND_TYPE,
            group_prefix="POWER_STATION_OUTPUT_POWER",
            assign_groups=assign_groups,
        )

    def _build_station_turbine_out_flow_commands(
        self,
        session: Any,
        step: int,
        *,
        assign_groups: bool = True,
    ) -> List[Dict[str, Any]]:
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

        return self._build_station_target_commands(
            station_values=station_out_flows,
            step=step,
            target_command_type=MPC_STATION_FLOW_COMMAND_TYPE,
            group_prefix="POWER_STATION_OUT_FLOW",
            assign_groups=assign_groups,
        )

    def _build_station_target_commands(
        self,
        *,
        station_values: Dict[int, float],
        step: int,
        target_command_type: str,
        group_prefix: str,
        assign_groups: bool = True,
    ) -> List[Dict[str, Any]]:
        commands: List[Dict[str, Any]] = []
        for station_id, target_value in station_values.items():
            target_agent = self._target_agent_resolver.resolve_target_agent_for_object(
                object_id=station_id,
                device_type=HydroObjectType.POWER_STATION.value,
            )
            if target_agent is None:
                logger.warning(
                    "Skip station control because target agent is unavailable: stationId=%s, step=%s, targetCommandType=%s",
                    station_id,
                    step,
                    target_command_type,
                )
                continue
            commands.append(
                {
                    "target_agent_code": target_agent.agent_code,
                    "target_command_type": target_command_type,
                    "target_value": target_value,
                    "object_id": station_id,
                    "object_type": HydroObjectType.POWER_STATION.value,
                    "main_step_index": step,
                    "_control_group_key": self._resolve_control_group_key(target_agent),
                }
            )

        if not assign_groups:
            return commands
        return self._assign_control_groups(commands, step=step, group_prefix=group_prefix)

    def _with_gate_station_flow_control_commands(
        self,
        *,
        session: Any,
        step: int,
        base_commands: List[Dict[str, Any]],
        group_prefix: str,
    ) -> List[Dict[str, Any]]:
        if not base_commands:
            return base_commands
        gate_commands = self._build_gate_station_flow_control_commands(session, step)
        if not gate_commands:
            return self._assign_control_groups(
                base_commands,
                step=step,
                group_prefix=group_prefix,
            )
        return self._assign_control_groups(
            list(base_commands) + gate_commands,
            step=step,
            group_prefix=group_prefix,
        )

    def _build_gate_station_flow_control_commands(self, session: Any, step: int) -> List[Dict[str, Any]]:
        commands: List[Dict[str, Any]] = []
        device_series = getattr(session, "latest_device_output_series", []) or []
        station_series = getattr(session, "latest_station_power_series", []) or []
        gate_intents_by_station: Dict[Optional[int], List[Dict[str, Any]]] = {}
        gate_flow_by_station: Dict[int, float] = {}
        missing_series_by_station: Dict[Optional[int], int] = {}
        missing_target_agent_by_station: Dict[Optional[int], int] = {}
        gate_opening_series_seen = False

        for device in device_series:
            if (
                str(device.get("object_type")) != HydroObjectType.GATE.value
                or str(device.get("metrics_code")) != MPC_GATE_OPENING_COMMAND_TYPE
                or device.get("object_id") is None
            ):
                continue
            gate_opening_series_seen = True
            station_id = self._normalize_optional_int(device.get("node_id"))
            row = self._get_series_row_for_step(device.get("time_series", []), step)
            if row is None:
                missing_series_by_station[station_id] = missing_series_by_station.get(station_id, 0) + 1
                continue
            gate_id = int(device["object_id"])
            gate_intents_by_station.setdefault(station_id, []).append(
                {
                    "gate_id": gate_id,
                    "gate_name": device.get("object_name") or f"Gate-{gate_id}",
                    "opening": float(row["value"]),
                }
            )

        for device in device_series:
            if (
                str(device.get("object_type")) != HydroObjectType.GATE.value
                or str(device.get("metrics_code")) != DeviceValueTypeEnum.WATER_FLOW.code
                or device.get("node_id") is None
            ):
                continue
            row = self._get_series_row_for_step(device.get("time_series", []), step)
            if row is None:
                continue
            station_id = int(device["node_id"])
            gate_flow_by_station[station_id] = gate_flow_by_station.get(station_id, 0.0) + float(row["value"])

        candidate_station_ids = self._collect_gate_station_flow_candidate_ids(
            session=session,
            step=step,
            gate_intents_by_station=gate_intents_by_station,
            gate_flow_by_station=gate_flow_by_station,
        )
        for station_id in candidate_station_ids:
            gate_flow = gate_flow_by_station.get(station_id)
            target_flow = self._resolve_station_diversion_flow(
                station_series=station_series,
                station_id=station_id,
                step=step,
                gate_flow=gate_flow,
            )
            if target_flow is None:
                logger.info(
                    "Skip gate station flow control because no diversion-flow intent is available: "
                    "task_id=%s, step=%s, station_id=%s",
                    self.context.biz_scene_instance_id,
                    step,
                    station_id,
                )
                continue
            target_agent = self._target_agent_resolver.resolve_target_agent_for_object(
                object_id=station_id,
                device_type=HydroObjectType.GATE_STATION.value,
            )
            if target_agent is None:
                missing_target_agent_by_station[station_id] = missing_target_agent_by_station.get(station_id, 0) + 1
                logger.warning(
                    "Skip gate station flow control because target agent is unavailable: stationId=%s, step=%s",
                    station_id,
                    step,
                )
                continue
            commands.append(
                {
                    "target_agent_code": target_agent.agent_code,
                    "target_command_type": MPC_GATE_STATION_FLOW_COMMAND_TYPE,
                    "target_value": float(target_flow),
                    "object_id": station_id,
                    "object_type": HydroObjectType.GATE_STATION.value,
                    "main_step_index": step,
                    "_control_group_key": self._resolve_control_group_key(target_agent),
                }
            )
        self._log_gate_opening_control_intent_evidence(
            session=session,
            step=step,
            gate_opening_series_seen=gate_opening_series_seen,
            gate_intents_by_station=gate_intents_by_station,
            missing_series_by_station=missing_series_by_station,
            missing_target_agent_by_station=missing_target_agent_by_station,
        )
        return commands

    def _collect_gate_station_flow_candidate_ids(
        self,
        *,
        session: Any,
        step: int,
        gate_intents_by_station: Dict[Optional[int], List[Dict[str, Any]]],
        gate_flow_by_station: Dict[int, float],
    ) -> List[int]:
        station_ids: List[int] = []
        for station in getattr(session, "latest_station_power_series", []) or []:
            station_id = self._normalize_optional_int(station.get("node_id"))
            if station_id is None:
                continue
            row = self._get_series_row_for_step(
                station.get(STATION_DIVERSION_FLOW_SERIES_KEY, []),
                step,
            )
            if row is not None and station_id not in station_ids:
                station_ids.append(station_id)
        for station_id in gate_flow_by_station:
            if station_id not in station_ids:
                station_ids.append(station_id)
        for station_id in gate_intents_by_station:
            if station_id is not None and station_id not in station_ids:
                station_ids.append(station_id)
        return station_ids

    def _log_gate_opening_control_intent_evidence(
        self,
        *,
        session: Any,
        step: int,
        gate_opening_series_seen: bool,
        gate_intents_by_station: Dict[Optional[int], List[Dict[str, Any]]],
        missing_series_by_station: Dict[Optional[int], int],
        missing_target_agent_by_station: Dict[Optional[int], int],
    ) -> None:
        if not gate_opening_series_seen:
            logger.info(
                "Power gate control intent evidence: task_id=%s, step=%s, "
                "source=power_internal_reservoir_model, edge_semantics=gate_station_flow_intent_edge_feedback_control, "
                "reason=no_gate_opening_series_configured, gate_count=0",
                self.context.biz_scene_instance_id,
                step,
            )
            return

        station_ids = set(gate_intents_by_station.keys())
        station_ids.update(missing_series_by_station.keys())
        station_ids.update(missing_target_agent_by_station.keys())
        device_series = getattr(session, "latest_device_output_series", []) or []
        station_series = getattr(session, "latest_station_power_series", []) or []
        all_station_ids = self._collect_station_ids_for_evidence(session)

        for station_id in sorted(station_ids, key=lambda value: -1 if value is None else int(value)):
            intents = gate_intents_by_station.get(station_id, [])
            gate_count = len(intents)
            missing_series_count = missing_series_by_station.get(station_id, 0)
            missing_target_agent_count = missing_target_agent_by_station.get(station_id, 0)
            openings = [float(intent["opening"]) for intent in intents]
            total_opening = sum(openings)
            max_opening = max(openings) if openings else 0.0
            station_name = self._resolve_evidence_station_name(session, station_id, intents)

            gate_flow = None
            station_diversion_flow = None
            turbine_outflow = None
            station_output_power = None
            front_water_level = None
            target_water_level = None
            back_water_level = None
            reservoir_evidence: Dict[str, Any] = {}
            if station_id is not None:
                gate_flow = self._sum_device_metric_for_station_step(
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
                    gate_flow=gate_flow,
                )
                turbine_outflow = self._sum_device_metric_for_station_step(
                    device_series=device_series,
                    station_id=station_id,
                    object_type=HydroObjectType.TURBINE.value,
                    metrics_code=DeviceValueTypeEnum.WATER_FLOW.code,
                    step=step,
                )
                station_output_power = self._sum_device_metric_for_station_step(
                    device_series=device_series,
                    station_id=station_id,
                    object_type=HydroObjectType.TURBINE.value,
                    metrics_code=DeviceValueTypeEnum.OUTPUT_POWER.code,
                    step=step,
                )
                front_water_level = self._resolve_station_front_water_level(
                    station_id=station_id,
                    step=step,
                )
                target_water_level = self._resolve_station_target_water_level(
                    station_id=station_id,
                    step=step,
                )
                back_water_level = self._resolve_station_back_water_level(
                    station_ids=all_station_ids,
                    station_id=station_id,
                    step=step,
                )
                reservoir_evidence = self._resolve_station_reservoir_evidence(
                    session=session,
                    station_id=station_id,
                    step=step,
                )

            reason = self._resolve_gate_opening_intent_reason(
                gate_count=gate_count,
                missing_series_count=missing_series_count,
                total_opening=total_opening,
                max_opening=max_opening,
                station_diversion_flow=station_diversion_flow,
                gate_flow=gate_flow,
                turbine_outflow=turbine_outflow,
                front_water_level=front_water_level,
                target_water_level=target_water_level,
            )
            logger.info(
                "Power gate control intent evidence: task_id=%s, step=%s, station_id=%s, station_name=%s, "
                "source=power_internal_reservoir_model, edge_semantics=gate_station_flow_intent_edge_feedback_control, "
                "gate_count=%s, missing_series=%s, target_agent_missing=%s, "
                "total_opening=%.6f, max_opening=%.6f, gate_flow=%s, station_diversion_flow=%s, "
                "turbine_outflow=%s, station_output_power=%s, front_water_level=%s, "
                "target_water_level=%s, back_water_level=%s, reservoir_inflow=%s, "
                "reservoir_outflow_power=%s, reservoir_spill_ff=%s, reservoir_spill_ff_gain=%s, "
                "reservoir_spill_ff_deadband=%s, reservoir_spill_ff_surplus=%s, "
                "reservoir_spill_ff_force_pass=%s, reservoir_pid_output=%s, "
                "reservoir_target_spill=%s, reservoir_spill_delta=%s, "
                "reason=%s, gates=%s",
                self.context.biz_scene_instance_id,
                step,
                station_id if station_id is not None else "null",
                station_name,
                gate_count,
                missing_series_count,
                missing_target_agent_count,
                total_opening,
                max_opening,
                self._format_optional_float(gate_flow),
                self._format_optional_float(station_diversion_flow),
                self._format_optional_float(turbine_outflow),
                self._format_optional_float(station_output_power),
                self._format_optional_float(front_water_level),
                self._format_optional_float(target_water_level),
                self._format_optional_float(back_water_level),
                self._format_optional_float(reservoir_evidence.get("current_inflow")),
                self._format_optional_float(reservoir_evidence.get("current_outflow_power")),
                self._format_optional_float(reservoir_evidence.get("current_outflow_discharge_ff")),
                self._format_optional_float(reservoir_evidence.get("current_spill_ff_gain")),
                self._format_optional_float(reservoir_evidence.get("current_spill_ff_deadband")),
                self._format_optional_float(reservoir_evidence.get("current_spill_ff_surplus")),
                reservoir_evidence.get("current_spill_ff_force_pass", "null"),
                self._format_optional_float(reservoir_evidence.get("current_pid_output")),
                self._format_optional_float(reservoir_evidence.get("current_target_spill")),
                self._format_optional_float(reservoir_evidence.get("current_spill_delta")),
                reason,
                self._format_gate_intents(intents),
            )

    def _resolve_station_reservoir_evidence(
        self,
        *,
        session: Any,
        station_id: int,
        step: int,
    ) -> Dict[str, Any]:
        series_evidence = self._resolve_station_reservoir_evidence_from_planning_series(
            session=session,
            station_id=station_id,
            step=step,
        )
        if series_evidence is not None:
            return series_evidence

        station_idx = hydrosim_config.NODE_TO_INDEX.get(int(station_id))
        if station_idx is None:
            return {}
        step_runtime = getattr(session, "step_runtime", None)
        multi_reservoir = getattr(step_runtime, "multi_reservoir", None)
        reservoirs = getattr(multi_reservoir, "Capacity_Stairs", None)
        if reservoirs is None or station_idx >= len(reservoirs):
            return {}
        history = getattr(reservoirs[station_idx], "history", {}) or {}
        row_index = self._resolve_reservoir_history_index(history, step)
        if row_index is None:
            return {}
        keys = [
            "current_inflow",
            "current_outflow_power",
            "current_outflow_discharge_ff",
            "current_spill_ff_gain",
            "current_spill_ff_deadband",
            "current_spill_ff_surplus",
            "current_spill_ff_force_pass",
            "current_pid_output",
            "current_target_spill",
            "current_spill_delta",
        ]
        return {
            key: self._history_value_at_index(history, key, row_index)
            for key in keys
        }

    def _resolve_station_reservoir_evidence_from_planning_series(
        self,
        *,
        session: Any,
        station_id: int,
        step: int,
    ) -> Optional[Dict[str, Any]]:
        for station in getattr(session, "latest_station_power_series", []) or []:
            if int(station.get("node_id", -1)) != int(station_id):
                continue
            row = self._get_series_row_for_step(
                station.get(RESERVOIR_EVIDENCE_SERIES_KEY, []),
                step,
            )
            if row is None:
                return None
            keys = [
                "current_inflow",
                "current_outflow_power",
                "current_outflow_discharge_ff",
                "current_spill_ff_gain",
                "current_spill_ff_deadband",
                "current_spill_ff_surplus",
                "current_spill_ff_force_pass",
                "current_pid_output",
                "current_target_spill",
                "current_spill_delta",
            ]
            return {key: row.get(key) for key in keys}
        return None

    @staticmethod
    def _resolve_reservoir_history_index(history: Dict[str, Any], step: int) -> Optional[int]:
        times = history.get("time") or []
        try:
            return list(times).index(int(step))
        except ValueError:
            pass
        if 0 <= int(step) < len(times):
            return int(step)
        lengths = [len(value) for value in history.values() if hasattr(value, "__len__")]
        if lengths and 0 <= int(step) < min(lengths):
            return int(step)
        return None

    @staticmethod
    def _history_value_at_index(history: Dict[str, Any], key: str, index: int) -> Any:
        values = history.get(key) or []
        if index < 0 or index >= len(values):
            return None
        return values[index]

    def _resolve_gate_opening_intent_reason(
        self,
        *,
        gate_count: int,
        missing_series_count: int,
        total_opening: float,
        max_opening: float,
        station_diversion_flow: Optional[float],
        gate_flow: Optional[float],
        turbine_outflow: Optional[float],
        front_water_level: Optional[float],
        target_water_level: Optional[float],
    ) -> str:
        epsilon = 1e-9
        if gate_count <= 0:
            if missing_series_count > 0:
                return "gate_opening_series_missing_for_step"
            return "gate_opening_series_not_available"
        if abs(total_opening) > epsilon or abs(max_opening) > epsilon:
            return "nonzero_gate_opening_intent"

        spill_flow = station_diversion_flow if station_diversion_flow is not None else gate_flow
        if spill_flow is None:
            return "zero_gate_opening_without_spill_flow_evidence"
        if abs(spill_flow) > epsilon:
            return "zero_gate_opening_but_spill_flow_positive_check_opening_conversion"
        if front_water_level is not None and target_water_level is not None:
            if float(front_water_level) <= float(target_water_level) + epsilon:
                return "water_level_not_triggered_or_no_spill_required"
            return "spill_intent_zero_despite_front_level_above_target_check_pid_or_constraints"
        if turbine_outflow is not None and abs(turbine_outflow) > epsilon:
            return "spill_intent_zero_with_turbine_outflow_available"
        return "spill_intent_zero"

    def _resolve_evidence_station_name(
        self,
        session: Any,
        station_id: Optional[int],
        intents: List[Dict[str, Any]],
    ) -> str:
        if station_id is None:
            return "unknown"
        for station in getattr(session, "latest_station_power_series", []) or []:
            if int(station.get("node_id", -1)) == int(station_id):
                return str(station.get("station") or station.get("object_name") or f"Station-{station_id}")
        for device in getattr(session, "latest_device_output_series", []) or []:
            if int(device.get("node_id", -1)) == int(station_id):
                station_name = device.get("station") or device.get("station_name")
                if station_name:
                    return str(station_name)
        if intents:
            first_gate_name = str(intents[0].get("gate_name") or "")
            return f"Station-{station_id}({first_gate_name})"
        return f"Station-{station_id}"

    def _collect_station_ids_for_evidence(self, session: Any) -> List[int]:
        station_ids: List[int] = []
        for station in getattr(session, "latest_station_power_series", []) or []:
            station_id = self._normalize_optional_int(station.get("node_id"))
            if station_id is not None and station_id not in station_ids:
                station_ids.append(station_id)
        for device in getattr(session, "latest_device_output_series", []) or []:
            station_id = self._normalize_optional_int(device.get("node_id"))
            if station_id is not None and station_id not in station_ids:
                station_ids.append(station_id)
        return station_ids

    @staticmethod
    def _normalize_optional_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_optional_float(value: Optional[float]) -> str:
        if value is None:
            return "null"
        return f"{float(value):.6f}"

    @staticmethod
    def _format_gate_intents(intents: List[Dict[str, Any]]) -> str:
        if not intents:
            return "[]"
        return "[" + ",".join(
            f"{intent.get('gate_name')}({intent.get('gate_id')})={float(intent.get('opening', 0.0)):.6f}"
            for intent in intents
        ) + "]"

    def _assign_control_groups(
        self,
        commands: List[Dict[str, Any]],
        *,
        step: int,
        group_prefix: str,
    ) -> List[Dict[str, Any]]:
        commands_by_group: Dict[str, List[Dict[str, Any]]] = {}
        for source_command in commands:
            command = dict(source_command)
            group_key = str(command.pop("_control_group_key", None) or command.get("target_agent_code"))
            commands_by_group.setdefault(group_key, []).append(command)

        grouped: List[Dict[str, Any]] = []
        for group_key, grouped_commands in commands_by_group.items():
            group_id = (
                f"{group_prefix}:{self.context.biz_scene_instance_id}:"
                f"{step}:{group_key}:{uuid.uuid4()}"
            )
            for command in grouped_commands:
                command["group_id"] = group_id
                command["group_size"] = len(grouped_commands)
                grouped.append(command)
        return grouped

    def _resolve_control_group_key(self, target_agent: Any) -> str:
        edge_node_code = getattr(target_agent, "edge_node_code", None)
        if edge_node_code:
            return str(edge_node_code)
        return str(target_agent.agent_code)

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
            station_output_power = self._sum_device_metric_for_station_step(
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
            if station_out_flow is not None or station_output_power is not None or turbine_device_results:
                target_value = self._value_item(MPC_STATION_POWER_COMMAND_TYPE, station_output_power)
                if target_value is None:
                    target_value = self._value_item(MPC_STATION_FLOW_COMMAND_TYPE, station_out_flow)
                predicted_results.append(
                    MpcResultFactory.build_predicted_result(
                        object_id=station_id,
                        object_type=POWER_STATION_TURBINE,
                        object_name=station_name,
                        target_value=target_value,
                        predicted_value_list=self._build_station_prediction_values(
                            front_water_level=front_water_level,
                            final_target_water_level=final_target_water_level,
                            back_water_level=back_water_level,
                            out_flow=station_out_flow,
                            diversion_flow=None,
                            output_power=station_output_power,
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
                            output_power=None,
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
        output_power: Optional[float],
    ) -> List[ValueItem]:
        values = (
            ("front_water_level", front_water_level),
            ("final_target_water_level", final_target_water_level),
            ("back_water_level", back_water_level),
            ("out_flow", out_flow),
            ("diversion_flow", diversion_flow),
            ("output_power", output_power),
            # Historical reports used the efficiency field to carry station
            # turbine output. Keep it during migration so old consumers do not
            # lose the value while new consumers switch to output_power.
            ("efficiency", output_power),
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
            status = item.get("status")
            metrics_list.append(
                MqttMetrics(
                    source_id=self.agent_code,
                    biz_scene_instance_id=self.biz_scene_instance_id,
                    job_instance_id=self.biz_scene_instance_id,
                    object_id=int(item["object_id"]),
                    object_type=str(item["object_type"]),
                    object_name=str(item["object_name"]),
                    step_index=int(item["step"]),
                    source_timestamp_ms=int(time.time() * 1000),
                    metrics_code=str(item["metrics_code"]),
                    value=float(item["value"]),
                    status=str(status) if status is not None else None,
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

    def _start_hydrosim_power_plan_preload(self) -> None:
        if self._hydrosim_power_plan_loaded:
            return
        preload_thread = self._hydrosim_power_plan_preload_thread
        if preload_thread is not None and preload_thread.is_alive():
            return

        self._hydrosim_power_plan_preload_error = None
        self._hydrosim_power_plan_preload_done.clear()
        self._hydrosim_power_plan_preload_started_at = time.monotonic()
        preload_thread = Thread(
            target=self._preload_hydrosim_power_plan,
            name=f"hydrosim-power-plan-preload-{self.agent_id}",
            daemon=True,
        )
        self._hydrosim_power_plan_preload_thread = preload_thread
        preload_thread.start()

    def _preload_hydrosim_power_plan(self) -> None:
        try:
            with self._runtime_lock:
                self._ensure_hydrosim_initialized()
                self._load_hydrosim_power_plan_locked()
        except Exception as exc:
            self._hydrosim_power_plan_preload_error = exc
            logger.exception(
                "HydroSim power planning background preload failed: runtime_revision=%s",
                POWER_SCHEDULING_RUNTIME_REVISION,
            )
        finally:
            self._hydrosim_power_plan_preload_done.set()

    def _await_hydrosim_power_plan_preload_for_command(
        self,
        *,
        command_name: str,
        step: Optional[int] = None,
    ) -> None:
        if self._hydrosim_power_plan_loaded:
            return

        preload_thread = self._hydrosim_power_plan_preload_thread
        if preload_thread is None:
            return

        wait_seconds = self._resolve_power_plan_preload_wait_seconds()
        if preload_thread.is_alive():
            elapsed_seconds = self._hydrosim_power_plan_preload_elapsed_seconds()
            thread_name = getattr(preload_thread, "name", None)
            thread_ident = getattr(preload_thread, "ident", None)
            logger.info(
                "Waiting HydroSim power planning background preload before %s: "
                "task_id=%s, step=%s, wait_seconds=%.3f, elapsed_seconds=%.3f, "
                "thread_name=%s, thread_ident=%s, thread_alive=%s, done=%s",
                command_name,
                self.context.biz_scene_instance_id,
                step,
                wait_seconds,
                elapsed_seconds,
                thread_name,
                thread_ident,
                preload_thread.is_alive(),
                self._hydrosim_power_plan_preload_done.is_set(),
            )
            if not self._hydrosim_power_plan_preload_done.wait(wait_seconds):
                elapsed_seconds = self._hydrosim_power_plan_preload_elapsed_seconds()
                thread_alive = preload_thread.is_alive()
                done = self._hydrosim_power_plan_preload_done.is_set()
                thread_name = getattr(preload_thread, "name", None)
                thread_ident = getattr(preload_thread, "ident", None)
                logger.error(
                    "HydroSim power planning preload timeout before %s: "
                    "task_id=%s, step=%s, waited_seconds=%.3f, elapsed_seconds=%.3f, "
                    "thread_name=%s, thread_ident=%s, thread_alive=%s, done=%s",
                    command_name,
                    self.context.biz_scene_instance_id,
                    step,
                    wait_seconds,
                    elapsed_seconds,
                    thread_name,
                    thread_ident,
                    thread_alive,
                    done,
                )
                raise RuntimeError(
                    "HydroSim power planning preload is still running "
                    f"before {command_name}: task_id={self.context.biz_scene_instance_id}, "
                    f"step={step}, waited_seconds={wait_seconds:.3f}, "
                    f"elapsed_seconds={elapsed_seconds:.3f}, thread_name={thread_name}, "
                    f"thread_ident={thread_ident}, thread_alive={thread_alive}, done={done}"
                )

        if self._hydrosim_power_plan_preload_error is not None:
            raise RuntimeError(
                "HydroSim power planning preload failed before "
                f"{command_name}: {type(self._hydrosim_power_plan_preload_error).__name__}: "
                f"{self._hydrosim_power_plan_preload_error}"
            ) from self._hydrosim_power_plan_preload_error

    def _resolve_power_plan_preload_wait_seconds(self) -> float:
        raw_value = self.properties.get_property(
            "hydrosim_power_plan_preload_wait_seconds",
            DEFAULT_POWER_PLAN_PRELOAD_WAIT_SECONDS,
        )
        try:
            wait_seconds = float(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid hydrosim_power_plan_preload_wait_seconds=%s; using default %.3f",
                raw_value,
                DEFAULT_POWER_PLAN_PRELOAD_WAIT_SECONDS,
            )
            wait_seconds = DEFAULT_POWER_PLAN_PRELOAD_WAIT_SECONDS
        return max(0.0, wait_seconds)

    def _hydrosim_power_plan_preload_elapsed_seconds(self) -> float:
        started_at = self._hydrosim_power_plan_preload_started_at
        if started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - started_at)

    def _ensure_hydrosim_power_plan_loaded(self) -> None:
        if self._hydrosim_power_plan_loaded:
            return
        self._await_hydrosim_power_plan_preload_for_command(
            command_name="power plan ensure",
        )
        if self._hydrosim_power_plan_loaded:
            return
        self._load_hydrosim_power_plan_locked()

    def _load_hydrosim_power_plan_locked(self) -> None:
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
        self._await_hydrosim_power_plan_preload_for_command(
            command_name="time series update",
        )
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
        logger.info(
            "Outflow planning follow-up acknowledged without reprocessing: commandId=%s",
            request.command_id,
        )
        return ResponseFactory.outflow_time_series_data_update_succeed(self, request)

    def on_outflow_planning(
        self,
        request: HydroEventCommand,
    ) -> OutflowTimeSeriesResponse:
        """使用当前 HydroSim 会话生成 Station/output_power 规划结果。"""
        event = request.payload
        if not isinstance(event, OutflowPlanningEvent):
            raise TypeError("HydroEventCommand.payload must be OutflowPlanningEvent")
        if not event.object_time_series:
            raise ValueError("OutflowPlanningEvent.object_time_series must not be empty")

        self._await_hydrosim_power_plan_preload_for_command(
            command_name="outflow planning",
        )
        with self._runtime_lock:
            logger.info("Power outflow planning received: commandId=%s", request.command_id)
            self._ensure_hydrosim_initialized()
            planned_series = self._execute_power_outflow_planning(event.object_time_series)
            self._hydrosim_power_plan_loaded = True

            changed_event = self._build_time_series_changed_event_from_outflow(
                event,
                planned_series,
            )
            task_state = self._activate_mpc_task_state_from_event(changed_event)
            self._refresh_rolling_window_for_boundary_change(
                task_state.current_step,
                task_state,
            )

        return ResponseFactory.outflow_planning_succeed(
            self,
            request,
            {"Station": planned_series},
        )

    def _execute_power_outflow_planning(
        self,
        object_time_series: List[ObjectTimeSeries],
    ) -> List[ObjectTimeSeries]:
        power_series = [
            item
            for item in object_time_series
            if item.object_type == "Station" and item.metrics_code == "output_power"
        ]
        inflow_series = [
            item
            for item in object_time_series
            if item.object_type == "Station" and item.metrics_code == "water_flow"
        ]

        if power_series:
            planning_result = self._hydrosim_api.get_station_power_planning_series(
                self._build_planning_payload(power_series)
            )
        elif inflow_series:
            planning_result = self._hydrosim_api.get_station_power_planning_series_from_inflow(
                self._build_planning_payload(inflow_series)
            )
        else:
            raise ValueError(
                "OutflowPlanningEvent requires Station/output_power or Station/water_flow series"
            )

        planned_series = self._build_station_power_object_time_series(
            planning_result.get("station_power_series", [])
        )
        if not planned_series:
            raise ValueError("HydroSim returned no Station/output_power planning series")
        return planned_series

    @staticmethod
    def _build_planning_payload(
        object_time_series: List[ObjectTimeSeries],
    ) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "object_time_series": [
                item.model_dump(mode="json", exclude_none=True)
                for item in object_time_series
            ]
        }

    @staticmethod
    def _build_station_power_object_time_series(
        station_power_series: List[Dict[str, Any]],
    ) -> List[ObjectTimeSeries]:
        return [
            ObjectTimeSeries(
                time_series_name=f"{station['station']}_power_plan",
                object_id=int(station["node_id"]),
                object_type="Station",
                object_name=station["station"],
                metrics_code="output_power",
                time_series=[
                    TimeSeriesValue(
                        step=int(row["step"]),
                        value=float(row["value"]),
                    )
                    for row in station.get("time_series", [])
                ],
            )
            for station in station_power_series
        ]

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
