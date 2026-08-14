"""MPC 滚动任务状态生命周期。"""

from __future__ import annotations

from typing import Callable, Optional

from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import SimulationContext
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.runtime.agent_context import resolve_simulation_runtime_options


class MpcTaskStateLifecycle:
    """创建、刷新并登记 MPC 滚动任务状态。"""

    def __init__(
        self,
        context: SimulationContext,
        get_current_step: Optional[Callable[[], int]] = None,
        get_rolling_interval_steps: Optional[Callable[[], int]] = None,
        get_max_steps: Optional[Callable[[], int]] = None,
        get_output_step_seconds: Optional[Callable[[], Optional[int]]] = None,
        get_prediction_horizon: Optional[Callable[[], Optional[int]]] = None,
        get_algorithm_config_url: Optional[Callable[[], Optional[str]]] = None,
        get_control_config_url: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.context = context
        self.get_current_step = get_current_step
        self.get_rolling_interval_steps = get_rolling_interval_steps
        self.get_max_steps = get_max_steps or self._get_runtime_max_steps
        self.get_output_step_seconds = (
            get_output_step_seconds or self._get_runtime_output_step_seconds
        )
        self.get_prediction_horizon = get_prediction_horizon
        self.get_algorithm_config_url = get_algorithm_config_url
        self.get_control_config_url = get_control_config_url
        self._task_state: Optional[MpcTaskState] = None

    @property
    def task_state(self) -> Optional[MpcTaskState]:
        return self._task_state

    def has_task_state(self) -> bool:
        return self._task_state is not None

    def require_task_state(
        self,
        message: str = "task_state is not initialized",
    ) -> MpcTaskState:
        if self._task_state is None:
            raise RuntimeError(message)
        return self._task_state

    def ensure_task_state(
        self,
        step: int,
        rolling_interval_steps: Optional[int] = None,
        max_steps: Optional[int] = None,
        output_step_seconds: Optional[int] = None,
        prediction_horizon: Optional[int] = None,
        algorithm_config_url: Optional[str] = None,
        control_config_url: Optional[str] = None,
    ) -> MpcTaskState:
        resolved_rolling_interval_steps = self._resolve_int(
            rolling_interval_steps,
            self.get_rolling_interval_steps,
            "rolling_interval_steps",
        )
        resolved_max_steps = self._resolve_int(
            max_steps,
            self.get_max_steps,
            "max_steps",
        )
        resolved_output_step_seconds = self._resolve_optional(
            output_step_seconds,
            self.get_output_step_seconds,
        )
        resolved_prediction_horizon = self._resolve_optional(
            prediction_horizon,
            self.get_prediction_horizon,
        )
        resolved_algorithm_config_url = self._resolve_optional(
            algorithm_config_url,
            self.get_algorithm_config_url,
        )
        resolved_control_config_url = self._resolve_optional(
            control_config_url,
            self.get_control_config_url,
        )

        if self._task_state is None:
            self._task_state = MpcTaskState(
                context=self.context,
                rolling_interval_steps=resolved_rolling_interval_steps,
                start_step=step,
                current_step=step,
                max_steps=resolved_max_steps,
                output_step_seconds=resolved_output_step_seconds,
                prediction_horizon=resolved_prediction_horizon,
                algorithm_config_url=resolved_algorithm_config_url,
                control_config_url=resolved_control_config_url,
            )
            return self._task_state

        self._task_state.rolling_interval_steps = resolved_rolling_interval_steps
        self._task_state.current_step = step
        self._task_state.max_steps = resolved_max_steps
        self._task_state.output_step_seconds = resolved_output_step_seconds
        self._task_state.prediction_horizon = resolved_prediction_horizon
        self._task_state.algorithm_config_url = resolved_algorithm_config_url
        self._task_state.control_config_url = resolved_control_config_url
        return self._task_state

    def activate_from_event(
        self,
        event: Optional[TimeSeriesDataChangedEvent],
        step: Optional[int] = None,
        use_event_step: bool = True,
        rolling_interval_steps: Optional[int] = None,
        max_steps: Optional[int] = None,
        output_step_seconds: Optional[int] = None,
        prediction_horizon: Optional[int] = None,
        algorithm_config_url: Optional[str] = None,
        control_config_url: Optional[str] = None,
    ) -> Optional[MpcTaskState]:
        if event is None:
            return self._task_state

        current_step = None
        if use_event_step:
            current_step = getattr(event, "auto_schedule_at_step", None)
        if current_step is None:
            current_step = step
        if current_step is None and self.get_current_step is not None:
            current_step = self.get_current_step()
        if current_step is None:
            raise ValueError("current step is required to activate MPC task state")

        task_state = self.ensure_task_state(
            int(current_step),
            rolling_interval_steps=rolling_interval_steps,
            max_steps=max_steps,
            output_step_seconds=output_step_seconds,
            prediction_horizon=prediction_horizon,
            algorithm_config_url=algorithm_config_url,
            control_config_url=control_config_url,
        )
        task_state.register_hydro_event(event, int(current_step))
        return task_state

    def clear(self) -> None:
        """Agent 终止时释放 task-scoped MPC 状态。"""
        self._task_state = None

    def _get_runtime_max_steps(self) -> int:
        runtime_options = resolve_simulation_runtime_options(self.context)
        if runtime_options is None:
            raise ValueError("simulation_runtime_options is required")
        return int(runtime_options.max_steps)

    def _get_runtime_output_step_seconds(self) -> Optional[int]:
        runtime_options = resolve_simulation_runtime_options(self.context)
        if runtime_options is None:
            return None
        return int(runtime_options.output_step_seconds)

    @staticmethod
    def _resolve_int(
        explicit_value: Optional[int],
        getter: Optional[Callable[[], int]],
        name: str,
    ) -> int:
        if explicit_value is not None:
            return int(explicit_value)
        if getter is not None:
            return int(getter())
        raise ValueError(f"{name} is required")

    @staticmethod
    def _resolve_optional(
        explicit_value,
        getter,
    ):
        if explicit_value is not None:
            return explicit_value
        if getter is not None:
            return getter()
        return None
