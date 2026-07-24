"""
Pump flow DMPC domain models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

import pandas as pd


@dataclass
class PumpFlowDmpcArguments:
    """Complete domain input extracted from ControlAlgorithmInput signals."""

    station_id: int
    mode: str
    config_path: str

    # Station memory
    active_unit_ids: List[int] = field(default_factory=list)
    unit_openings: Dict[int, float] = field(default_factory=dict)
    unit_status: Dict[int, int] = field(default_factory=dict)
    time_since_adjust: Dict[int, int] = field(default_factory=dict)
    time_since_switch: Dict[int, int] = field(default_factory=dict)
    last_selected_flow: float = 0.0

    # Transfer bundle
    reference_flow: List[float] = field(default_factory=list)
    reference_front_level: List[float] = field(default_factory=list)
    reference_back_level: List[float] = field(default_factory=list)
    reference_head: List[float] = field(default_factory=list)

    # Available units
    available_unit_ids: List[int] = field(default_factory=list)

    # Current observation
    current_front_level: float = 0.0
    current_back_level: float = 0.0
    current_head: float = 0.0
    current_flow: float = 0.0

    # Environment for basin simulation
    basin_levels: Dict[str, float] = field(default_factory=dict)
    pool_areas: Dict[int, float] = field(default_factory=dict)
    anchor_basin_levels: Dict[str, float] = field(default_factory=dict)
    boundary_level_plan: Optional[pd.DataFrame] = None
    disturbance_estimate: Dict = field(default_factory=dict)
    demand_plan: Optional[pd.DataFrame] = None
    start_time_hours: float = 0.0
    step_hours: float = 1.0

    # Cross-station
    upper_flow_refs: Dict[int, List[float]] = field(default_factory=dict)
    flow_history: List[float] = field(default_factory=list)
