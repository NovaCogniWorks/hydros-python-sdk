"""
Pump flow DMPC domain models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


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
    unit_blade_bounds: Dict[int, Tuple[float, float]] = field(default_factory=dict)

    # Current observation
    current_front_level: float = 0.0
    current_back_level: float = 0.0
    current_head: float = 0.0
    current_flow: float = 0.0

    # Edge-provided safety constraint for one control step.
    max_blade_delta_per_step: float = 2.0
