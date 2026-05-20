from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .station_model import PumpStationModel
from .types import ModeDecision, RuntimeParameters, StationMemory, UpperPlan


@dataclass
class ODDSupervisor:
    runtime: RuntimeParameters

    def select_mode(
        self,
        station_id: int,
        env_snapshot,
        upper_plan: UpperPlan,
        station_model: PumpStationModel,
        station_memory: StationMemory,
        available_unit_ids,
        force_reconfiguration: bool = False,
        reference_flow: Optional[float] = None,
        reference_back: Optional[float] = None,
        reference_front: Optional[float] = None,
    ) -> ModeDecision:
        ref_flow = float(reference_flow if reference_flow is not None else upper_plan.flow_refs[station_id][0])
        ref_back = float(reference_back if reference_back is not None else upper_plan.station_back_levels[station_id][0])
        ref_front = float(reference_front if reference_front is not None else upper_plan.station_front_levels[station_id][0])
        actual_flow = env_snapshot.station_flows[station_id]
        actual_back = env_snapshot.station_back_levels[station_id]
        actual_front = env_snapshot.station_front_levels[station_id]
        del station_model

        flow_error = abs(actual_flow - ref_flow)
        level_error = max(abs(actual_back - ref_back), abs(actual_front - ref_front))
        if force_reconfiguration:
            return ModeDecision(
                station_id=station_id,
                mode="ODD3",
                reason="unit availability changed",
                fit_score=0.0,
                flow_error=float(flow_error),
                level_error=float(level_error),
            )

        if (
            flow_error <= self.runtime.odd1_flow_tolerance and
            level_error <= self.runtime.odd1_level_tolerance
        ):
            return ModeDecision(
                station_id=station_id,
                mode="ODD1",
                reason="steady-state hold",
                fit_score=1.0,
                flow_error=float(flow_error),
                level_error=float(level_error),
            )

        if (
            flow_error >= self.runtime.odd3_flow_tolerance or
            level_error >= self.runtime.odd3_level_tolerance
        ):
            return ModeDecision(
                station_id=station_id,
                mode="ODD3",
                reason="ODD3 threshold exceeded",
                fit_score=0.0,
                flow_error=float(flow_error),
                level_error=float(level_error),
            )

        current_active_set = set(station_memory.active_unit_ids)
        if not current_active_set.issubset(set(available_unit_ids)):
            return ModeDecision(
                station_id=station_id,
                mode="ODD3",
                reason="active units unavailable",
                fit_score=0.0,
                flow_error=float(flow_error),
                level_error=float(level_error),
            )

        if current_active_set:
            return ModeDecision(
                station_id=station_id,
                mode="ODD2",
                reason="attempt angle tuning",
                fit_score=0.0,
                flow_error=float(flow_error),
                level_error=float(level_error),
            )

        return ModeDecision(
            station_id=station_id,
            mode="ODD3",
            reason="needs reconfiguration",
            fit_score=0.0,
            flow_error=float(flow_error),
            level_error=float(level_error),
        )
