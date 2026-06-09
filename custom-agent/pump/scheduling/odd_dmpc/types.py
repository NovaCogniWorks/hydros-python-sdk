from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional


AvailableUnitsMap = Dict[int, List[int]]


@dataclass(frozen=True)
class InlineTableConfig:
    columns: List[str] = field(default_factory=list)
    rows: List[List[float]] = field(default_factory=list)


@dataclass(frozen=True)
class BoundaryNodeConfig:
    id: str
    hydro_node: str
    series_column: Optional[str] = None
    mpc_key: Optional[str] = None


@dataclass(frozen=True)
class ChannelSegmentConfig:
    id: str
    upstream_station_id: int
    downstream_station_id: int
    hydro_channel: str
    hydro_profile_node: Optional[str] = None
    disturbance_node: Optional[str] = None


@dataclass(frozen=True)
class ChannelGroupConfig:
    upstream_station_id: int
    downstream_station_id: int
    segment_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TopologyConfig:
    boundary_series_source: str = "file"
    boundary_nodes: List[BoundaryNodeConfig] = field(default_factory=list)
    channel_segments: List[ChannelSegmentConfig] = field(default_factory=list)
    channel_groups: List[ChannelGroupConfig] = field(default_factory=list)

    @property
    def boundary_node_map(self) -> Dict[str, BoundaryNodeConfig]:
        return {node.id: node for node in self.boundary_nodes}

    @property
    def boundary_hydro_nodes(self) -> List[str]:
        return [node.hydro_node for node in self.boundary_nodes]

    @property
    def boundary_series_columns(self) -> List[str]:
        columns: List[str] = []
        for node in self.boundary_nodes:
            columns.append(node.series_column or node.hydro_node)
        return columns

    @property
    def segment_map(self) -> Dict[str, ChannelSegmentConfig]:
        return {segment.id: segment for segment in self.channel_segments}


@dataclass(frozen=True)
class UnitConfig:
    id: int
    name: str
    remote_name: Optional[str] = None
    q_min: Optional[float] = None
    q_max: Optional[float] = None
    table_e: Optional[InlineTableConfig] = None
    table_r: Optional[InlineTableConfig] = None


@dataclass(frozen=True)
class StationConfig:
    id: int
    name: str
    level_back_min: float
    level_back_max: float
    level_front_min: float
    level_front_max: float
    num_units: int
    units: List[UnitConfig]
    units_file: Mapping[str, str] = field(default_factory=dict)
    remote_name: Optional[str] = None
    front_level_key: Optional[str] = None
    back_level_key: Optional[str] = None
    hydro_front_node: Optional[str] = None
    hydro_back_node: Optional[str] = None

    @property
    def unit_name_by_id(self) -> Dict[int, str]:
        return {unit.id: unit.name for unit in self.units}

    @property
    def unit_id_by_name(self) -> Dict[str, int]:
        return {unit.name: unit.id for unit in self.units}

    @property
    def level_up_min(self) -> float:
        return self.level_back_min

    @property
    def level_up_max(self) -> float:
        return self.level_back_max

    @property
    def level_down_min(self) -> float:
        return self.level_front_min

    @property
    def level_down_max(self) -> float:
        return self.level_front_max


@dataclass(frozen=True)
class PoolConfig:
    id: int
    name: str
    area: Optional[float] = None


@dataclass
class PoolProfileState:
    pool_id: int
    name: str
    spacings: List[float]
    bed_elevations: List[float]
    water_levels: List[float]
    section_flows: List[float]
    wet_areas: List[float]
    representative_level: float
    representative_depth: float
    reported_volume: float
    computed_volume: float
    volume_offset: float
    raw_surface_area: float
    storage_area: float


@dataclass(frozen=True)
class SystemConfig:
    project: str
    description: str
    rho: float
    g: float
    horizon_hours: int
    dt_hours: float
    target_avg_flow_last_station: float
    stations: List[StationConfig]
    canal_pools: List[PoolConfig]
    flow_depart_step_q: float
    flow_depart_step_h: float
    flow_depart_data_dir: str
    flow_depart_output_dir: str
    source_config_path: str = "data/config.yaml"
    demand_plan_path: Optional[str] = "data/inflow-demand-plan.xlsx"
    demand_plan_inline: Optional[InlineTableConfig] = None
    hydro_model_path: Optional[str] = "hydro_model.json"
    boundary_level_path: Optional[str] = "data/boundary-level.xlsx"
    boundary_level_inline: Optional[InlineTableConfig] = None
    topology: TopologyConfig = field(default_factory=TopologyConfig)

    @property
    def station_by_id(self) -> Dict[int, StationConfig]:
        return {station.id: station for station in self.stations}

    @property
    def station_ids(self) -> List[int]:
        return [station.id for station in self.stations]

    @property
    def first_station_id(self) -> int:
        if not self.stations:
            raise ValueError("SystemConfig has no stations")
        return int(self.stations[0].id)

    @property
    def last_station_id(self) -> int:
        if not self.stations:
            raise ValueError("SystemConfig has no stations")
        return int(self.stations[-1].id)

    @property
    def pool_ids(self) -> List[int]:
        return [pool.id for pool in self.canal_pools]

    @property
    def level_key_sequence(self) -> List[str]:
        keys: List[str] = []
        for idx, station in enumerate(self.stations):
            if idx == 0:
                if station.front_level_key is None:
                    break
                keys.append(station.front_level_key)
            if station.back_level_key is None:
                break
            keys.append(station.back_level_key)
        if keys:
            return keys
        return [f"b{i}" for i in range(len(self.stations) + 1)]


@dataclass
class RuntimeParameters:
    odd1_flow_tolerance: float = 2.0
    odd1_level_tolerance: float = 0.15
    odd2_fit_threshold: float = 0.62
    odd3_flow_tolerance: float = 8.0
    odd3_level_tolerance: float = 0.8
    head_search_tolerance: float = 0.35
    flow_search_tolerance: float = 8.0
    candidate_pool_limit: int = 60
    control_horizon_lower: int = 10
    opening_change_threshold: float = 0.0
    station_memory_init_age: int = 999
    upper_level_correction_gain: float = 0.25
    upper_flow_bias_correction_gain: float = 0.0
    upper_mpc_optimization_method: str = "nlp"
    lower_flow_weight: float = 3.0
    lower_level_weight: float = 2.5
    lower_switch_weight: float = 3.0
    lower_adjust_count_weight: float = 0.8
    hidden_disturbance_enabled: bool = True
    hidden_disturbance_active_scenario: str = "moderate"
    hidden_disturbance_rain_light_path: str = "data/hidden-disturbance-rain-light.xlsx"
    hidden_disturbance_rain_moderate_path: str = "data/hidden-disturbance-rain-moderate.xlsx"
    hidden_disturbance_rain_heavy_path: str = "data/hidden-disturbance-rain-heavy.xlsx"
    unit_availability_enabled: bool = True
    unit_availability_active_scenario: str = "maintenance_fault"
    unit_availability_scenarios: Dict[str, Dict[str, List[Dict[str, object]]]] = field(default_factory=dict)
    observer_gain: float = 0.35
    observer_smoothing: float = 0.0
    disturbance_forecast_window_hours: float = 4.0
    disturbance_forecast_method: str = "linear"
    env_substeps: int = 6
    basin_clip_margin_b1: float = 1.0
    basin_clip_margin_b2: float = 1.5
    sim_api_base_url: str = "http://47.97.1.45:8000/"
    sim_create_is_steady_state: bool = True
    sim_sync_dt_seconds: int = 100
    auto_identify_pool_areas: bool = False
    console_verbose: bool = True
    console_float_precision: int = 3
    output_dir: str = "output"
    save_step_plots: bool = True


@dataclass
class ThreadSnapshotState:
    thread_uuid: str
    boundary_levels: Dict[str, float]
    basin_levels: Dict[str, float]
    basin_volumes: Dict[int, float]
    pool_areas: Dict[int, float]
    basin_profiles: Dict[int, PoolProfileState]
    station_front_levels: Dict[int, float]
    station_back_levels: Dict[int, float]
    station_total_flows: Dict[int, float]
    unit_status: Dict[int, Dict[int, int]]
    unit_openings: Dict[int, Dict[int, float]]
    unit_flows: Dict[int, Dict[int, float]]
    unit_front_levels: Dict[int, Dict[int, float]]
    unit_back_levels: Dict[int, Dict[int, float]]
    available_units_map: AvailableUnitsMap
    raw_result: Mapping[str, object]


@dataclass
class EnvironmentObservation:
    time_index: int
    time_hours: float
    basin_levels: Dict[str, float]
    basin_volumes: Dict[int, float]
    pool_areas: Dict[int, float]
    basin_profiles: Dict[int, PoolProfileState]
    anchor_basin_levels: Dict[str, float]
    boundary_nominal_flows: Dict[str, float]
    station_back_levels: Dict[int, float]
    station_front_levels: Dict[int, float]
    station_heads: Dict[int, float]
    station_flows: Dict[int, float]
    pool_levels: Dict[int, float]
    thread_uuid: Optional[str] = None

    @property
    def station_up_levels(self) -> Dict[int, float]:
        return self.station_back_levels

    @property
    def station_down_levels(self) -> Dict[int, float]:
        return self.station_front_levels


@dataclass
class UpperPlan:
    hour_index: int
    horizon: int
    flow_refs: Dict[int, List[float]]
    station_back_levels: Dict[int, List[float]]
    station_front_levels: Dict[int, List[float]]
    station_heads: Dict[int, List[float]]
    efficiency_refs: Dict[int, List[float]]
    target_last_station_flow: float
    effective_flow_refs: Dict[int, List[float]] = field(default_factory=dict)
    command_flow_refs: Dict[int, List[float]] = field(default_factory=dict)
    metadata: Dict[str, float] = field(default_factory=dict)

    @property
    def station_up_levels(self) -> Dict[int, List[float]]:
        return self.station_back_levels

    @property
    def station_down_levels(self) -> Dict[int, List[float]]:
        return self.station_front_levels

    @property
    def predicted_flow_refs(self) -> Dict[int, List[float]]:
        return self.effective_flow_refs or self.flow_refs


@dataclass
class TransferBundle:
    station_id: int
    reference_flow: List[float]
    reference_back_level: List[float]
    reference_front_level: List[float]
    reference_head: List[float]
    active_unit_ids: List[int]
    time_since_adjust: Dict[int, int]
    time_since_switch: Dict[int, int]
    disturbance_estimate: Dict[int, float]

    @property
    def reference_up_level(self) -> List[float]:
        return self.reference_back_level

    @property
    def reference_down_level(self) -> List[float]:
        return self.reference_front_level


@dataclass
class ModeDecision:
    station_id: int
    mode: str
    reason: str
    fit_score: float
    flow_error: float
    level_error: float


@dataclass
class ControlAction:
    station_id: int
    mode: str
    selected_flow: float
    unit_status: Dict[int, int]
    unit_openings: Dict[int, float]
    unit_flows: Dict[int, float]
    fit_score: float
    objective: float
    predicted_flow_error: float
    predicted_level_error: float
    predicted_back_level: Optional[float] = None
    predicted_front_level: Optional[float] = None
    predicted_head: Optional[float] = None
    predicted_openings: List[float] = field(default_factory=list)
    predicted_efficiencies: List[float] = field(default_factory=list)
    predicted_unit_openings: Dict[int, List[float]] = field(default_factory=dict)
    predicted_unit_flows: Dict[int, List[float]] = field(default_factory=dict)
    predicted_unit_status: Dict[int, List[int]] = field(default_factory=dict)
    predicted_unit_efficiencies: Dict[int, List[float]] = field(default_factory=dict)
    candidate_plans: List[Dict[str, object]] = field(default_factory=list)

    @property
    def predicted_up_level(self) -> Optional[float]:
        return self.predicted_back_level

    @property
    def predicted_down_level(self) -> Optional[float]:
        return self.predicted_front_level


@dataclass
class StationMemory:
    active_unit_ids: List[int]
    unit_openings: Dict[int, float]
    unit_status: Dict[int, int]
    time_since_adjust: Dict[int, int]
    time_since_switch: Dict[int, int]
    last_selected_flow: float
    mode: str


@dataclass
class LowerFeedback:
    available_units_map: AvailableUnitsMap
    feasible_flow_ranges: Dict[int, List[float]]
    current_modes: Dict[int, str]
    plan_execution_errors: Dict[int, float]
    reconfigured_stations: Dict[int, bool]
