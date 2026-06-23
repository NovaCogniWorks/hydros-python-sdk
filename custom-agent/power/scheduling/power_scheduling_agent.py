"""
Central scheduling agent example for the power HydroSim integration.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
HYDROSIM_DIR = CURRENT_DIR.parent / "mpc"
DATA_DIR = CURRENT_DIR.parent / "data"
if str(HYDROSIM_DIR) not in sys.path:
    sys.path.insert(0, str(HYDROSIM_DIR))

from hydrosim_api import HydroSimulationApi
from hydros_agent_sdk import (
    DeviceValueTypeEnum,
    ErrorCodes,
    HydroObjectType,
    handle_agent_errors,
    load_env_config,
)
from hydros_agent_sdk.agents.mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from hydros_agent_sdk.mpc.models import HorizonStep
from hydros_agent_sdk.mpc.mpc_result_factory import MpcResultFactory
from hydros_agent_sdk.mpc.mpc_result_reporter import MpcResultReporter
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
from hydros_agent_sdk.scheduling_task_state import SchedulingTaskState
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

logger = logging.getLogger(__name__)


class PumpCentralSchedulingAgent(MpcCentralSchedulingAgent):
    """
    Power HydroSim central scheduling agent.

    The agent keeps the SDK central-scheduling wiring, but refreshes its
    scheduling window only once per ``roll_steps`` interval. A refreshed window
    publishes a horizon dataset, while every tick still executes the current
    HydroSim step and returns step metrics.
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
        self._rolling_window_start_step: Optional[int] = None
        self._rolling_window_end_step: Optional[int] = None
        self._rolling_window_dataset: List[HorizonStep] = []
        self._local_mpc_task_state: Optional[SchedulingTaskState] = None
        logger.info("Power central scheduling agent created: %s", agent_id)

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initializing power scheduling agent: %s", self.agent_id)

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
                logger.info("Subscribing rendered field metrics topic: %s", full_metrics_topic)
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

    def _initialize_optimization_model(self) -> None:
        logger.info("Loading MPC optimization model ...")
        self._optimization_model = {"status": "ready"}
        logger.info("Optimization model ready")

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        self._ensure_hydrosim_initialized()
        self._ensure_hydrosim_power_plan_loaded()
        task_state = self._ensure_mpc_task_state(request.step)

        if self._should_refresh_rolling_window(request.step, task_state):
            logger.info("Refreshing rolling scheduling window at step=%s", request.step)
            commands = self.on_optimization(request.step)
            if commands:
                self._control_command_dispatcher.dispatch(commands)
            self._refresh_rolling_window_dataset(request.step, task_state)

        step_result = self._hydrosim_api.execute_step(step_index=request.step)
        metrics_list = self._build_metrics_from_step_result(step_result)
        logger.info("step=%s HydroSim execute_step returned %s metrics", request.step, len(metrics_list))
        return metrics_list

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        logger.info("--- step %s: running MPC rolling optimization ---", step)
        session = getattr(self._hydrosim_api, "_session", None)
        if session is None:
            logger.warning("Skip optimization at step=%s because HydroSim session is unavailable.", step)
            return []

        commands: List[Dict[str, Any]] = []
        for station in getattr(session, "latest_station_power_series", []) or []:
            station_row = self._get_series_row_for_step(station.get("time_series", []), step)
            if station_row is None:
                continue

            object_id = int(station["node_id"])
            target_agent = self._target_agent_resolver.resolve_target_agent_for_object(
                object_id=object_id,
                device_type=HydroObjectType.STATION.value,
            )
            if target_agent is None:
                logger.warning(
                    "Skip station output-power command because target agent is unavailable: objectId=%s, step=%s",
                    object_id,
                    step,
                )
                continue

            commands.append(
                {
                    "target_agent_code": target_agent.agent_code,
                    "target_command_type": DeviceValueTypeEnum.OUTPUT_POWER.code,
                    "target_value": float(station_row["value"]),
                    "object_id": object_id,
                    "object_type": HydroObjectType.STATION.value,
                }
            )

        logger.info("Built %s power scheduling commands for step=%s", len(commands), step)
        return commands

    def _ensure_mpc_task_state(self, step: int) -> SchedulingTaskState:
        return self._resolve_mpc_task_state(step)

    def _resolve_mpc_task_state(self, step: int) -> SchedulingTaskState:
        try:
            task_state = self._mpc_rolling_runtime.require_mpc_task_state()
        except Exception:
            if self._local_mpc_task_state is None:
                self._local_mpc_task_state = SchedulingTaskState(
                    context=self.context,
                    rolling_interval_steps=self._resolve_roll_steps(),
                    start_step=step,
                    current_step=step,
                    total_steps=self._resolve_total_steps(),
                    algorithm_config_url=getattr(self._mpc_rolling_runtime, "configured_mpc_config_url", None),
                    control_config_url=getattr(
                        self._mpc_rolling_runtime,
                        "configured_target_and_constrain_config_url",
                        None,
                    ),
                )
            task_state = self._local_mpc_task_state

        task_state.current_step = step
        task_state.total_steps = self._resolve_total_steps()
        task_state.rolling_interval_steps = self._resolve_roll_steps()
        return task_state

    def _activate_mpc_task_state_from_event(self, event: Any, step: Optional[int] = None) -> SchedulingTaskState:
        current_step = step
        event_step = getattr(event, "auto_schedule_at_step", None)
        if event_step is not None and int(event_step) >= 0:
            current_step = int(event_step)
        if current_step is None:
            current_step = 0

        task_state = self._ensure_mpc_task_state(current_step)
        if self._local_mpc_task_state is task_state:
            task_state.start_step = current_step
        if event is not None:
            task_state.register_hydro_event(event)
        logger.info(
            "Power scheduling task state activated: bizSceneInstanceId=%s, currentStep=%s, rollSteps=%s",
            self.context.biz_scene_instance_id,
            task_state.current_step,
            task_state.rolling_interval_steps,
        )
        return task_state

    def _resolve_roll_steps(self) -> int:
        runtime = getattr(self, "_mpc_rolling_runtime", None)
        if runtime is not None:
            get_roll_steps = getattr(runtime, "get_roll_steps", None)
            if callable(get_roll_steps):
                roll_steps = int(get_roll_steps())
                if roll_steps > 0:
                    return roll_steps
        value = self.properties.get_property("roll_steps", None)
        if value is None:
            return 1
        return max(int(value), 1)

    def _resolve_total_steps(self) -> int:
        session = getattr(self._hydrosim_api, "_session", None)
        if session is None:
            return 0
        return max([len(item.get("time_series", [])) for item in getattr(session, "latest_station_power_series", [])] or [0])

    def _resolve_window_range(self, step: int, task_state: SchedulingTaskState) -> Tuple[int, int]:
        roll_steps = max(int(task_state.rolling_interval_steps), 1)
        start_step = int(task_state.start_step)
        total_steps = int(task_state.total_steps)
        if step < start_step:
            window_start = start_step
        else:
            window_index = (step - start_step) // roll_steps
            window_start = start_step + (window_index * roll_steps)
        window_end = window_start + roll_steps - 1
        if total_steps > 0:
            window_end = min(window_end, total_steps - 1)
        return window_start, window_end

    def _should_refresh_rolling_window(self, step: int, task_state: SchedulingTaskState) -> bool:
        window_start, window_end = self._resolve_window_range(step, task_state)
        return (
            self._rolling_window_start_step != window_start
            or self._rolling_window_end_step != window_end
            or not self._rolling_window_dataset
        )

    def _refresh_rolling_window_dataset(self, step: int, task_state: SchedulingTaskState) -> None:
        window_start, window_end = self._resolve_window_range(step, task_state)
        horizon_steps = self._build_window_horizon_steps(window_start, window_end)
        self._rolling_window_start_step = window_start
        self._rolling_window_end_step = window_end
        self._rolling_window_dataset = horizon_steps
        self._publish_rolling_window_report(step, task_state, horizon_steps)

    def _publish_rolling_window_report(
        self,
        step: int,
        task_state: SchedulingTaskState,
        horizon_steps: List[HorizonStep],
    ) -> None:
        if not horizon_steps:
            logger.info("Skip rolling window report publish because no horizon dataset is available: step=%s", step)
            return

        reporter = getattr(self, "_mpc_result_reporter", None) or MpcResultReporter(
            sim_coordination_client=self.sim_coordination_client
        )
        reporter.publish_customize_report(
            source_agent_instance=self,
            mpc_task_state=task_state,
            horizon_step=horizon_steps,
            plan_type="optimal",
        )

    def _build_window_horizon_steps(self, window_start: int, window_end: int) -> List[HorizonStep]:
        session = getattr(self._hydrosim_api, "_session", None)
        if session is None:
            return []

        station_series = getattr(session, "latest_station_power_series", []) or []
        device_series = getattr(session, "latest_device_output_series", []) or []
        horizon_steps: List[HorizonStep] = []
        for absolute_step in range(window_start, window_end + 1):
            control_object_list = []
            for station in station_series:
                station_row = self._get_series_row_for_step(station.get("time_series", []), absolute_step)
                if station_row is None:
                    continue
                control_object_list.append(
                    MpcResultFactory.build_control_object_result(
                        object_id=int(station["node_id"]),
                        node_id=int(station["node_id"]),
                        object_name=station.get("station"),
                        target_value=float(station_row["value"]),
                        object_type=HydroObjectType.STATION.value,
                        target_value_type=DeviceValueTypeEnum.OUTPUT_POWER.code,
                    )
                )

            for device in device_series:
                device_row = self._get_series_row_for_step(device.get("time_series", []), absolute_step)
                if device_row is None:
                    continue
                control_object_list.append(
                    MpcResultFactory.build_control_object_result(
                        object_id=int(device["object_id"]),
                        node_id=int(device["node_id"]) if device.get("node_id") is not None else None,
                        object_name=device.get("object_name"),
                        target_value=float(device_row["value"]),
                        object_type=str(device["object_type"]),
                        target_value_type=str(device["metrics_code"]),
                    )
                )

            if not control_object_list:
                continue
            horizon_steps.append(
                HorizonStep(
                    horizon_step=absolute_step,
                    control_object_list=control_object_list,
                    predicted_result_list=[],
                )
            )
        return horizon_steps

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
        logger.info("HydroSim power planning loaded, stations=%s", len(result.get("station_power_series", [])))

    def _get_hydrosim_property(self, key: str, default: str) -> str:
        value = self.properties.get_property(key, default)
        return str(Path(value).resolve())

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        logger.info("--- time series update received: %s ---", request.command_id)
        event = request.time_series_data_changed_event
        self._activate_mpc_task_state_from_event(event)
        if event and event.object_time_series:
            for obj_ts in event.object_time_series:
                logger.info("Object %s metric %s updated", obj_ts.object_name, obj_ts.metrics_code)
                if obj_ts.time_series:
                    first_val = obj_ts.time_series[0]
                    logger.debug("First point: Step=%s, Value=%s", first_val.step, first_val.value)

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
        logger.info("--- outflow time series update received: %s ---", request.command_id)
        event = request.outflow_time_series_data_changed_event
        self._activate_mpc_task_state_from_event(event)
        if event and event.object_time_series:
            for obj_ts in event.object_time_series:
                if obj_ts.time_series:
                    first_val = obj_ts.time_series[0]
                    logger.debug("First point: Step=%s, Value=%s", first_val.step, first_val.value)

        return OutflowTimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("Stopping power scheduling agent: %s", self.agent_id)
        self._agent_command_gateway.shutdown()
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
        self._local_mpc_task_state = None

        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )
