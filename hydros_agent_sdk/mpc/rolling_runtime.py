"""滚动 MPC 运行时协调。"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Callable, List, Optional

from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.mpc.config import MpcConfigResolver
from hydros_agent_sdk.scheduling_task_state import SchedulingTaskState
from hydros_agent_sdk.scheduling_task_state_lifecycle import SchedulingTaskStateLifecycle
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import AgentStatus, SimulationContext
from hydros_agent_sdk.utils.property_parse_utils import PropertyParseUtils

logger = logging.getLogger(__name__)


class MpcRollingRuntime:
    """持有滚动 MPC 任务状态并触发优化周期。"""

    def __init__(
        self,
        context: SimulationContext,
        properties: AgentProperties,
        optimize_step: Callable[[int], Optional[List[Any]]],
        dispatch_control_commands: Callable[[List[Any]], None],
        build_control_commands: Callable[[List[Any], int], List[Any]],
        set_current_step: Callable[[int], None],
        get_current_step: Callable[[], int],
        set_agent_status: Callable[[AgentStatus], None],
        record_dispatched_control_commands: Optional[Callable[[List[Any], int], None]] = None,
        configured_mpc_config_url: Optional[str] = None,
        configured_target_and_constrain_config_url: Optional[str] = None,
        configured_mpc_service_base_url: Optional[str] = None,
        rolling_cycle_runner: Optional[Callable[[SchedulingTaskState], Optional[List[Any]]]] = None,
    ):
        self.context = context
        self.properties = properties
        self.optimize_step = optimize_step
        self.dispatch_control_commands = dispatch_control_commands
        self.build_control_commands = build_control_commands
        self.record_dispatched_control_commands = record_dispatched_control_commands
        self.set_current_step = set_current_step
        self.get_current_step = get_current_step
        self.set_agent_status = set_agent_status
        self.configured_mpc_config_url = configured_mpc_config_url
        self.configured_target_and_constrain_config_url = (
            configured_target_and_constrain_config_url
        )
        self.configured_mpc_service_base_url = configured_mpc_service_base_url
        self.rolling_cycle_runner = rolling_cycle_runner
        self._last_optimization_step = 0
        self._task_state_lifecycle = SchedulingTaskStateLifecycle(
            context=context,
            get_current_step=get_current_step,
            get_rolling_interval_steps=self.get_roll_steps,
            get_total_steps=self.get_total_steps,
            get_output_step_size=self.get_output_step_size,
        )
        self._lock = RLock()

    @property
    def last_optimization_step(self) -> int:
        return self._last_optimization_step

    @property
    def task_state(self) -> Optional[SchedulingTaskState]:
        return self._task_state_lifecycle.task_state

    def _get_model_context(self):
        from hydros_agent_sdk.context_manager import ContextManager

        return ContextManager.get_context(self.context)

    def _get_scenario_runtime_options(self):
        model_context = self._get_model_context()
        if model_context is None:
            return None
        return getattr(model_context, "simulation_runtime_options", None)

    def _get_scenario_sim_agent_properties(self):
        model_context = self._get_model_context()
        if model_context is None:
            return None
        return model_context.sim_agent_properties

    def _get_scenario_int(
        self,
        runtime_name: str,
        scenario_property_name: Optional[str] = None,
    ) -> Optional[int]:
        runtime_options = self._get_scenario_runtime_options()
        if runtime_options is not None:
            value = getattr(runtime_options, runtime_name, None)
            if value is not None:
                return int(value)

        sim_agent_properties = self._get_scenario_sim_agent_properties()
        if sim_agent_properties is None:
            return None

        value = getattr(sim_agent_properties, scenario_property_name or runtime_name, None)
        if value is None:
            return None
        return int(value)

    def get_roll_steps(self) -> int:
        """返回滚动间隔，匹配 Java 侧 runtime options 优先的兜底规则。"""
        scenario_roll_steps = self._get_scenario_int("roll_steps", "roll_steps")
        if scenario_roll_steps is not None:
            return scenario_roll_steps

        return PropertyParseUtils.get_int(
            self.properties,
            "roll_steps",
            None,
        )

    def get_total_steps(self) -> int:
        """返回任务总步数，用于避免在任务结束时再次滚动。"""
        scenario_total_steps = self._get_scenario_int("max_steps", "total_steps")
        if scenario_total_steps is not None:
            return scenario_total_steps

        return PropertyParseUtils.get_int(self.properties, "total_steps", None)

    def get_output_step_size(self) -> Optional[int]:
        """返回每步预测时长，匹配 Java 侧 runtime options 优先的兜底规则。"""
        scenario_output_step_size = self._get_scenario_int(
            "output_step_seconds",
            "output_step_size",
        )
        if scenario_output_step_size is not None:
            return scenario_output_step_size

        value = self.properties.get_property("output_step_size", None)
        if value is None:
            return None
        return int(value)

    def should_auto_start_mpc_on_tick(self) -> bool:
        """判断 tick 是否可以在时间序列更新到达前激活 MPC。"""
        return PropertyParseUtils.get_bool(
            self.properties,
            "auto_start_mpc_on_tick",
            False,
        )

    def set_rolling_cycle_runner(
        self,
        rolling_cycle_runner: Optional[Callable[[SchedulingTaskState], Optional[List[Any]]]],
    ) -> None:
        self.rolling_cycle_runner = rolling_cycle_runner

    def is_mpc_optimizing_on_the_loop(self) -> bool:
        """任务是否已经激活滚动 MPC 循环。"""
        return self._task_state_lifecycle.has_task_state()

    def on_tick(self, step: int) -> None:
        with self._lock:
            self.set_current_step(step)
            if not self.is_mpc_optimizing_on_the_loop():
                if not self.should_auto_start_mpc_on_tick():
                    logger.debug(
                        "MPC rolling loop has not been activated yet and auto-start is disabled: "
                        "bizSceneInstanceId=%s, step=%s",
                        self.context.biz_scene_instance_id,
                        step,
                    )
                    return

                self.activate_from_tick(step)
                return

            task_state = self.require_task_state()
            task_state.current_step = step
            task_state.total_steps = self.get_total_steps()
            should_roll = task_state.active_new_rolling(step)

            logger.info(
                "MPC rolling check: bizSceneInstanceId=%s, startStep=%s, "
                "currentStep=%s, rollStep=%s, shouldRoll=%s",
                self.context.biz_scene_instance_id,
                task_state.start_step,
                step,
                task_state.rolling_interval_steps,
                should_roll,
            )

            if should_roll:
                self.do_rolling_optimal(task_state)
                self._last_optimization_step = step

            self.dispatch_control_for_current_step(task_state)

            self.set_agent_status(AgentStatus.ACTIVE)

    def handle_time_series_changed(
        self,
        event: Optional[TimeSeriesDataChangedEvent],
    ) -> None:
        if event is None or not event.object_time_series:
            raise ValueError("time series update event has no object_time_series")

        with self._lock:
            rolling_interval_steps = self.get_roll_steps()
            if rolling_interval_steps <= 0:
                raise ValueError(f"roll_steps must be positive: {rolling_interval_steps}")

            if (
                event.auto_schedule_at_step is not None
                and event.auto_schedule_at_step > self.get_current_step()
            ):
                self.set_current_step(event.auto_schedule_at_step)

            current_step = self.get_current_step()
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
                task_state = self._activate_task_state_from_event(
                    event,
                    rolling_interval_steps=rolling_interval_steps,
                    current_step=current_step,
                    total_steps=total_steps,
                )
                self.do_rolling_optimal(task_state)
                self._last_optimization_step = current_step
                self.set_agent_status(AgentStatus.ACTIVE)
                return

            self._activate_task_state_from_event(
                event,
                rolling_interval_steps=rolling_interval_steps,
                current_step=current_step,
                total_steps=total_steps,
            )

    def activate_from_tick(self, current_step: int) -> None:
        rolling_interval_steps = self.get_roll_steps()
        if rolling_interval_steps <= 0:
            raise ValueError(f"roll_steps must be positive: {rolling_interval_steps}")

        task_state = self._create_task_state(
            rolling_interval_steps=rolling_interval_steps,
            current_step=current_step,
            total_steps=self.get_total_steps(),
        )

        logger.info(
            "MPC rolling loop auto-started by tick: bizSceneInstanceId=%s, "
            "startStep=%s, rollStep=%s, totalSteps=%s",
            self.context.biz_scene_instance_id,
            task_state.start_step,
            task_state.rolling_interval_steps,
            task_state.total_steps,
        )
        self.do_rolling_optimal(task_state)
        self._last_optimization_step = current_step
        self.set_agent_status(AgentStatus.ACTIVE)

    def require_task_state(self) -> SchedulingTaskState:
        return self._task_state_lifecycle.require_task_state(
            "task_state is not initialized"
        )

    def do_rolling_optimal(self, task_state: SchedulingTaskState) -> Optional[List[Any]]:
        if self.rolling_cycle_runner is not None:
            return self.rolling_cycle_runner(task_state)

        logger.info(
            "Executing MPC optimization: bizSceneInstanceId=%s, step=%s",
            self.context.biz_scene_instance_id,
            task_state.current_step,
        )
        control_plan = self.optimize_step(task_state.current_step)
        task_state.current_loop += 1
        task_state.latest_control_plan = list(control_plan or [])
        task_state.latest_control_plan_start_step = task_state.current_step
        task_state.dispatched_horizon_steps.clear()
        logger.info("MPC optimization completed at step %s", task_state.current_step)
        self.dispatch_control_for_current_step(task_state)
        return control_plan

    def dispatch_control_for_current_step(self, task_state: SchedulingTaskState) -> None:
        if not task_state.latest_control_plan or task_state.latest_control_plan_start_step is None:
            return
        horizon_step = task_state.current_step - task_state.latest_control_plan_start_step + 1
        if horizon_step <= 0 or horizon_step in task_state.dispatched_horizon_steps:
            return
        control_commands = self.build_control_commands(task_state.latest_control_plan, horizon_step)
        if control_commands:
            if self.record_dispatched_control_commands is not None:
                self.record_dispatched_control_commands(control_commands, horizon_step)
            self.dispatch_control_commands(control_commands)
        task_state.dispatched_horizon_steps.add(horizon_step)

    def _create_task_state(
        self,
        rolling_interval_steps: int,
        current_step: int,
        total_steps: int,
    ) -> SchedulingTaskState:
        mpc_config = MpcConfigResolver.resolve(
            self.properties,
            configured_mpc_config_url=self.configured_mpc_config_url,
            configured_target_and_constrain_config_url=(
                self.configured_target_and_constrain_config_url
            ),
            configured_mpc_service_base_url=self.configured_mpc_service_base_url,
        )
        logger.debug(
            "MPC config URLs resolved from agent properties: bizSceneInstanceId=%s, "
            "mpcConfigUrl=%s, controlConfigUrl=%s",
            self.context.biz_scene_instance_id,
            mpc_config.mpc_config_url,
            mpc_config.target_and_constrain_config_url,
        )
        return self._task_state_lifecycle.ensure_task_state(
            current_step,
            rolling_interval_steps=rolling_interval_steps,
            total_steps=total_steps,
            output_step_size=self.get_output_step_size(),
            algorithm_config_url=mpc_config.mpc_config_url,
            control_config_url=mpc_config.target_and_constrain_config_url,
        )

    def _activate_task_state_from_event(
        self,
        event: TimeSeriesDataChangedEvent,
        rolling_interval_steps: int,
        current_step: int,
        total_steps: int,
    ) -> SchedulingTaskState:
        mpc_config = MpcConfigResolver.resolve(
            self.properties,
            configured_mpc_config_url=self.configured_mpc_config_url,
            configured_target_and_constrain_config_url=(
                self.configured_target_and_constrain_config_url
            ),
            configured_mpc_service_base_url=self.configured_mpc_service_base_url,
        )
        return self._task_state_lifecycle.activate_from_event(
            event,
            step=current_step,
            use_event_step=False,
            rolling_interval_steps=rolling_interval_steps,
            total_steps=total_steps,
            output_step_size=self.get_output_step_size(),
            algorithm_config_url=mpc_config.mpc_config_url,
            control_config_url=mpc_config.target_and_constrain_config_url,
        )
