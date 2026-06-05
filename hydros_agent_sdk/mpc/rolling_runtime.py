"""滚动 MPC 运行时协调。"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Callable, List, Optional

from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.mpc.config import MpcConfigResolver
from hydros_agent_sdk.mpc.task_state import MpcTaskState
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
        set_current_step: Callable[[int], None],
        get_current_step: Callable[[], int],
        set_agent_status: Callable[[AgentStatus], None],
        configured_mpc_config_url: Optional[str] = None,
        configured_target_and_constrain_config_url: Optional[str] = None,
        configured_mpc_service_base_url: Optional[str] = None,
        rolling_cycle_runner: Optional[Callable[[MpcTaskState], Optional[List[Any]]]] = None,
    ):
        self.context = context
        self.properties = properties
        self.optimize_step = optimize_step
        self.dispatch_control_commands = dispatch_control_commands
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
        self._mpc_task_state: Optional[MpcTaskState] = None
        self._lock = RLock()

    @property
    def last_optimization_step(self) -> int:
        return self._last_optimization_step

    @property
    def mpc_task_state(self) -> Optional[MpcTaskState]:
        return self._mpc_task_state

    def _get_scenario_sim_agent_properties(self):
        from hydros_agent_sdk.context_manager import ContextManager

        model_context = ContextManager.get_context(self.context)
        if model_context is None:
            return None
        return model_context.sim_agent_properties

    def _get_scenario_int(self, name: str) -> Optional[int]:
        sim_agent_properties = self._get_scenario_sim_agent_properties()
        if sim_agent_properties is None:
            return None

        value = getattr(sim_agent_properties, name, None)
        if value is None:
            return None
        return int(value)

    def get_roll_steps(self) -> int:
        """返回滚动间隔，匹配 Java 侧 roll_steps 兜底规则。"""
        scenario_roll_steps = self._get_scenario_int("roll_steps")
        if scenario_roll_steps is not None:
            return scenario_roll_steps

        return PropertyParseUtils.get_int(
            self.properties,
            "roll_steps",
            None,
        )

    def get_total_steps(self) -> int:
        """返回任务总步数，用于避免在任务结束时再次滚动。"""
        scenario_total_steps = self._get_scenario_int("total_steps")
        if scenario_total_steps is not None:
            return scenario_total_steps

        return PropertyParseUtils.get_int(self.properties, "total_steps", None)

    def should_auto_start_mpc_on_tick(self) -> bool:
        """判断 tick 是否可以在时间序列更新到达前激活 MPC。"""
        return PropertyParseUtils.get_bool(
            self.properties,
            "auto_start_mpc_on_tick",
            False,
        )

    def set_rolling_cycle_runner(
        self,
        rolling_cycle_runner: Optional[Callable[[MpcTaskState], Optional[List[Any]]]],
    ) -> None:
        self.rolling_cycle_runner = rolling_cycle_runner

    def is_mpc_optimizing_on_the_loop(self) -> bool:
        """任务是否已经激活滚动 MPC 循环。"""
        return self._mpc_task_state is not None

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

            mpc_task_state = self.require_mpc_task_state()
            mpc_task_state.current_step = step
            mpc_task_state.total_steps = self.get_total_steps()
            should_roll = mpc_task_state.active_new_rolling(step)

            logger.info(
                "MPC rolling check: bizSceneInstanceId=%s, startStep=%s, "
                "currentStep=%s, rollStep=%s, shouldRoll=%s",
                self.context.biz_scene_instance_id,
                mpc_task_state.start_step,
                step,
                mpc_task_state.rolling_interval_steps,
                should_roll,
            )

            if should_roll:
                self.do_rolling_optimal(mpc_task_state)
                self._last_optimization_step = step

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
                mpc_task_state = self._create_task_state(
                    rolling_interval_steps=rolling_interval_steps,
                    current_step=current_step,
                    total_steps=total_steps,
                )
                mpc_task_state.register_hydro_event(event)
                self._mpc_task_state = mpc_task_state
                self.do_rolling_optimal(mpc_task_state)
                self._last_optimization_step = current_step
                self.set_agent_status(AgentStatus.ACTIVE)
                return

            mpc_task_state = self.require_mpc_task_state()
            mpc_task_state.rolling_interval_steps = rolling_interval_steps
            mpc_task_state.current_step = current_step
            mpc_task_state.total_steps = total_steps
            mpc_task_state.register_hydro_event(event)

    def activate_from_tick(self, current_step: int) -> None:
        rolling_interval_steps = self.get_roll_steps()
        if rolling_interval_steps <= 0:
            raise ValueError(f"roll_steps must be positive: {rolling_interval_steps}")

        mpc_task_state = self._create_task_state(
            rolling_interval_steps=rolling_interval_steps,
            current_step=current_step,
            total_steps=self.get_total_steps(),
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
        self.do_rolling_optimal(mpc_task_state)
        self._last_optimization_step = current_step
        self.set_agent_status(AgentStatus.ACTIVE)

    def require_mpc_task_state(self) -> MpcTaskState:
        if self._mpc_task_state is None:
            raise RuntimeError("mpc_task_state is not initialized")
        return self._mpc_task_state

    def do_rolling_optimal(self, mpc_task_state: MpcTaskState) -> Optional[List[Any]]:
        if self.rolling_cycle_runner is not None:
            return self.rolling_cycle_runner(mpc_task_state)

        logger.info(
            "Executing MPC optimization: bizSceneInstanceId=%s, step=%s",
            self.context.biz_scene_instance_id,
            mpc_task_state.current_step,
        )
        control_commands = self.optimize_step(mpc_task_state.current_step)
        mpc_task_state.current_loop += 1
        if control_commands:
            self.dispatch_control_commands(control_commands)
        logger.info("MPC optimization completed at step %s", mpc_task_state.current_step)
        return control_commands

    def _create_task_state(
        self,
        rolling_interval_steps: int,
        current_step: int,
        total_steps: int,
    ) -> MpcTaskState:
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
        return MpcTaskState(
            context=self.context,
            rolling_interval_steps=rolling_interval_steps,
            start_step=current_step,
            current_step=current_step,
            total_steps=total_steps,
            mpc_config_url=mpc_config.mpc_config_url,
            target_and_constrain_config_url=mpc_config.target_and_constrain_config_url,
        )
