"""
Call the original ODD-DMPC LocalController from standalone algorithm context.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

import pandas as pd
import yaml

# Ensure odd_dmpc is importable
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_SCRIPT_DIR)
_ODD_DMPC_DIR = os.path.join(_PARENT_DIR, "scheduling", "odd_dmpc")
if _ODD_DMPC_DIR not in sys.path:
    sys.path.insert(0, _ODD_DMPC_DIR)

from odd_dmpc.config import load_runtime_context_from_payload
from odd_dmpc.environment import _boundary_plan_from_snapshot
from odd_dmpc.flow_service import FlowDepartService
from odd_dmpc.local_controller import LocalController, StationControlContext
from odd_dmpc.types import (
    ControlAction,
    LowerFeedback,
    StationMemory,
    TransferBundle,
    SystemConfig,
)

from .errors import PumpFlowDmpcError
from .types import PumpFlowDmpcArguments


class PumpFlowDmpcSolver:
    """Bridge to original ODD-DMPC LocalController."""

    def __init__(self) -> None:
        self._local_controller: LocalController | None = None
        self._system_config: SystemConfig | None = None
        self._flow_service: FlowDepartService | None = None
        self._runtime = None
        self._lower_feedback: LowerFeedback | None = None
        self._available_units_map: Dict[int, List[int]] = {}

    def _ensure_loaded(self, arguments: PumpFlowDmpcArguments) -> None:
        if self._system_config is not None:
            return
        config_path = arguments.config_path
        if not config_path or not os.path.exists(config_path):
            raise PumpFlowDmpcError(
                "CONFIG_NOT_FOUND",
                "config path not available: %s" % config_path,
            )
        with open(config_path, "r", encoding="utf-8") as f:
            payload = yaml.safe_load(f)
        context = load_runtime_context_from_payload(payload)
        self._system_config = context["system_config"]
        self._runtime = context["runtime"]
        self._flow_service = FlowDepartService(self._system_config, config_dict=payload)
        self._local_controller = LocalController(
            system_config=self._system_config,
            runtime=self._runtime,
            flow_service=self._flow_service,
        )
        # Build available_units_map
        self._available_units_map = {
            station.id: [unit.id for unit in station.units]
            for station in self._system_config.stations
        }

    def solve(self, arguments: PumpFlowDmpcArguments) -> ControlAction:
        self._ensure_loaded(arguments)

        station_id = arguments.station_id

        # Build StationMemory
        station_memory = StationMemory(
            active_unit_ids=list(arguments.active_unit_ids),
            unit_openings=dict(arguments.unit_openings),
            unit_status=dict(arguments.unit_status),
            time_since_adjust=dict(arguments.time_since_adjust),
            time_since_switch=dict(arguments.time_since_switch),
            last_selected_flow=float(arguments.last_selected_flow),
            mode=arguments.mode,
        )

        # Build TransferBundle
        ref_flow = list(arguments.reference_flow)
        ref_front = list(arguments.reference_front_level)
        ref_back = list(arguments.reference_back_level)
        ref_head = list(arguments.reference_head)

        transfer_bundle = TransferBundle(
            station_id=station_id,
            reference_flow=ref_flow,
            reference_back_level=ref_back,
            reference_front_level=ref_front,
            reference_head=ref_head,
            active_unit_ids=list(arguments.active_unit_ids),
            time_since_adjust=dict(arguments.time_since_adjust),
            time_since_switch=dict(arguments.time_since_switch),
            disturbance_estimate=dict(arguments.disturbance_estimate),
        )

        # Build or reuse boundary_level_plan
        boundary_level_plan = arguments.boundary_level_plan
        if boundary_level_plan is None and arguments.basin_levels:
            try:
                boundary_level_plan = _boundary_plan_from_snapshot(
                    self._system_config, arguments.basin_levels
                )
            except Exception:
                boundary_level_plan = pd.DataFrame()

        # Build StationControlContext
        station_model = self._flow_service.get_station_model(
            station_id, arguments.available_unit_ids
        )

        station_ctx = StationControlContext(
            station_id=station_id,
            station_model=station_model,
            available_unit_ids=list(arguments.available_unit_ids),
            basin_levels=dict(arguments.basin_levels),
            basin_profiles=None,
            pool_areas=dict(arguments.pool_areas),
            anchor_basin_levels=dict(arguments.anchor_basin_levels),
            boundary_nominal_flows={},
            current_back_level=float(arguments.current_back_level),
            current_front_level=float(arguments.current_front_level),
            current_head=float(arguments.current_head),
            upper_flow_refs={k: list(v) for k, v in arguments.upper_flow_refs.items()},
            flow_history={station_id: list(arguments.flow_history)},
            boundary_level_plan=boundary_level_plan,
            start_time_hours=float(arguments.start_time_hours),
            step_hours=float(arguments.step_hours),
            demand_plan=arguments.demand_plan,
        )

        return self._local_controller.solve(
            mode=arguments.mode,
            station_ctx=station_ctx,
            upstream_prediction={},
            disturbance_forecast={},
            transfer_bundle=transfer_bundle,
            station_memory=station_memory,
        )
