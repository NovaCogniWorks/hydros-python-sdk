"""将 MPC 规划输出投影为明确且可执行的控制意图。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set, Tuple

from hydros_agent_sdk.control_algorithms.models import ControlSignal
from hydros_agent_sdk.mpc.models import MpcOptimizeResponse


SUPPORTED_STATION_OBJECT_TYPES = frozenset({"GateStation", "PumpStation"})
SUPPORTED_TARGET_VALUE_TYPE = "water_level"


@dataclass(frozen=True)
class MpcControlExecutionTarget:
    """从 ``control_object_list`` 提取的一条可下发站点控制目标。"""

    horizon_step: int
    object_id: int
    object_type: str
    target_value: float
    target_value_type: str
    algorithm_input_signals: List[ControlSignal] = field(default_factory=list)


@dataclass
class MpcControlExecutionPlan:
    """从 MPC ``control_object_list`` 提取可执行目标及其规划信号。"""

    optimize_step: int
    control_targets_by_horizon: Dict[int, List[MpcControlExecutionTarget]] = field(
        default_factory=dict
    )

    @classmethod
    def from_responses(
        cls,
        optimize_step: int,
        responses: Iterable[MpcOptimizeResponse],
    ) -> "MpcControlExecutionPlan":
        plan = cls(optimize_step=optimize_step)
        target_keys: Set[Tuple[int, int, str]] = set()

        for response in responses:
            if (response.plan_type or "").upper() != "OPTIMAL":
                continue
            for horizon in response.horizon_controls:
                if horizon.horizon_step is None:
                    continue

                targets: List[MpcControlExecutionTarget] = []
                for control_object in horizon.control_object_list or []:
                    if (
                        control_object.object_id is None
                        or control_object.object_type not in SUPPORTED_STATION_OBJECT_TYPES
                    ):
                        continue
                    for target_value in control_object.target_value_list or []:
                        numeric_value = target_value.numeric_value()
                        if (
                            numeric_value is None
                            or target_value.value_type.lower()
                            != SUPPORTED_TARGET_VALUE_TYPE
                        ):
                            continue
                        target_key = (
                            horizon.horizon_step,
                            control_object.object_id,
                            target_value.value_type.lower(),
                        )
                        if target_key in target_keys:
                            continue
                        target_keys.add(target_key)
                        targets.append(
                            MpcControlExecutionTarget(
                                horizon_step=horizon.horizon_step,
                                object_id=control_object.object_id,
                                object_type=control_object.object_type,
                                target_value=numeric_value,
                                target_value_type=target_value.value_type,
                                algorithm_input_signals=list(control_object.algorithm_input_signals),
                            )
                        )
                if targets:
                    plan.control_targets_by_horizon.setdefault(
                        horizon.horizon_step,
                        [],
                    ).extend(targets)
        return plan

    def get_control_targets(
        self,
        horizon_step: int,
    ) -> List[MpcControlExecutionTarget]:
        return list(self.control_targets_by_horizon.get(horizon_step, []))
