"""泵站流量 DMPC 的私有领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple


@dataclass(frozen=True)
class PumpUnitState:
    """一次求解中单台可用泵机组的只读输入事实。"""

    unit_id: int
    current_blade_angle: float
    min_blade_angle: float
    max_blade_angle: float


@dataclass(frozen=True)
class PumpFlowDmpcArguments:
    """一次泵站流量分配求解所需的完整领域输入。"""

    station_id: int
    target_flow: float
    current_flow: float
    water_head: float
    units: Tuple[PumpUnitState, ...]
    flow_tolerance: float
    max_blade_delta_per_step: float
    candidate_angle_step: float
    max_solver_iterations: int
    movement_weight: float


@dataclass(frozen=True)
class PumpFlowDmpcDecision:
    """纯 solver 的决策结果，尚不代表任何设备已经执行。"""

    station_id: int
    blade_angles: Mapping[int, float]
    predicted_station_flow: float
    objective: float
    completed: bool
    reason: str
