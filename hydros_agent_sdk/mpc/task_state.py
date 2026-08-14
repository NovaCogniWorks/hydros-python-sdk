"""MPC 滚动任务的运行时状态。"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import SimulationContext

if TYPE_CHECKING:
    from hydros_agent_sdk.mpc.control_execution_plan import MpcControlExecutionPlan


@dataclass
class MpcTaskState:
    """单个 MPC 滚动循环的运行时状态。"""

    context: SimulationContext
    rolling_interval_steps: int
    start_step: int
    current_step: int = -1
    max_steps: int = 36
    current_loop: int = 1
    output_step_seconds: Optional[int] = None
    prediction_horizon: Optional[int] = None
    algorithm_config_url: Optional[str] = None
    control_config_url: Optional[str] = None
    biz_customize_config_url: Optional[str] = None
    hydro_environment_type: str = "NORMAL"
    hydro_events: List[TimeSeriesDataChangedEvent] = field(default_factory=list)
    hydro_event_injected_start_steps: Dict[int, Optional[int]] = field(
        default_factory=dict
    )
    latest_control_plan: Optional["MpcControlExecutionPlan"] = None
    latest_control_plan_start_step: Optional[int] = None
    dispatched_horizon_steps: Set[int] = field(default_factory=set)
    dispatched_control_keys: Set[str] = field(default_factory=set)

    def register_hydro_event(
        self,
        event: TimeSeriesDataChangedEvent,
        injected_start_step: Optional[int] = None,
    ) -> None:
        self.hydro_events.append(event)
        self.hydro_event_injected_start_steps[id(event)] = (
            self._resolve_injected_start_step(event, injected_start_step)
        )

    def get_injected_start_step(
        self,
        event: TimeSeriesDataChangedEvent,
    ) -> Optional[int]:
        event_identity = id(event)
        if event_identity in self.hydro_event_injected_start_steps:
            return self.hydro_event_injected_start_steps[event_identity]
        return self._resolve_injected_start_step(event, None)

    @staticmethod
    def _resolve_injected_start_step(
        event: TimeSeriesDataChangedEvent,
        injected_start_step: Optional[int],
    ) -> Optional[int]:
        if injected_start_step is not None and injected_start_step >= 0:
            return injected_start_step
        return getattr(event, "auto_schedule_at_step", None)

    def should_start_new_rolling(self, current_step: int) -> bool:
        if self.rolling_interval_steps <= 0:
            return False
        if self.max_steps > 0 and current_step >= self.max_steps:
            return False
        step_delta = current_step - self.start_step
        return (
            step_delta % self.rolling_interval_steps == 0
            and step_delta != 0
        )
