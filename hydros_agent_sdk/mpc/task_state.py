"""滚动 MPC 任务的运行时状态。"""

from dataclasses import dataclass, field
from typing import List, Optional

from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import SimulationContext


@dataclass
class MpcTaskState:
    """单个兼容 Java 侧滚动 MPC 循环的运行时状态。"""

    context: SimulationContext
    rolling_interval_steps: int
    start_step: int
    current_step: int = -1
    total_steps: int = 36
    current_loop: int = 1
    mpc_config_url: Optional[str] = None
    target_and_constrain_config_url: Optional[str] = None
    hydro_events: List[TimeSeriesDataChangedEvent] = field(default_factory=list)

    def register_hydro_event(self, event: TimeSeriesDataChangedEvent) -> None:
        self.hydro_events.append(event)

    def active_new_rolling(self, current_step: int) -> bool:
        if self.rolling_interval_steps <= 0:
            return False
        step_delta = current_step - self.start_step
        return (
            step_delta % self.rolling_interval_steps == 0
            and step_delta != 0
            and current_step - self.total_steps != 0
        )
