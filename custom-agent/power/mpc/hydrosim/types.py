from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field


HydroOutputMode = Literal["file", "json", "mixed"]


class HydroSimulationModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class TimeSeriesValue(HydroSimulationModel):
    step: int | None = None
    time: Any | None = None
    value: float | None = None


class ObjectTimeSeries(HydroSimulationModel):
    time_series_name: str | None = None
    object_id: int | None = None
    object_ids: list[int] = Field(default_factory=list)
    object_type: str | None = None
    object_name: str | None = None
    metrics_code: str | None = None
    time_series: list[TimeSeriesValue] = Field(default_factory=list)


class HydroSimulationEventData(HydroSimulationModel):
    valid: bool = True
    object_time_series: list[ObjectTimeSeries] = Field(default_factory=list)


class HydroInitialStateOverride(HydroSimulationModel):
    id: Any
    name: str | None = None
    metrics_code: str
    value: float


class HydroInitialStateSection(HydroSimulationModel):
    overrides: list[HydroInitialStateOverride] | Dict[str, list[HydroInitialStateOverride]] = Field(default_factory=list)


class HydroInitialStatesData(HydroSimulationModel):
    initial_states: Dict[str, HydroInitialStateSection] = Field(default_factory=dict)


class HydroControlTarget(HydroSimulationModel):
    node_id: int
    min_water_level: float | None = None
    max_water_level: float | None = None
    max_flow: float | None = None


class HydroControlDomain(HydroSimulationModel):
    device_id: int
    node_id: int | None = None
    type: str


class HydroConstraintsData(HydroSimulationModel):
    control_targets: list[HydroControlTarget] = Field(default_factory=list)
    control_domains: list[HydroControlDomain] = Field(default_factory=list)


class HydroMpcConfigData(HydroSimulationModel):
    raw: Dict[str, Any] = Field(default_factory=dict)


class HydroSimulationInputBundle(HydroSimulationModel):
    event: HydroSimulationEventData
    initial_states: HydroInitialStatesData
    constraints: HydroConstraintsData
    mpc_config: HydroMpcConfigData = Field(default_factory=HydroMpcConfigData)


class HydroSimulationInputPatch(HydroSimulationModel):
    event: HydroSimulationEventData | None = None
    initial_states: HydroInitialStatesData | None = None
    constraints: HydroConstraintsData | None = None
    mpc_config: HydroMpcConfigData | None = None


@dataclass(frozen=True)
class HydroSimulationFileOutputs:
    output_dir: str
    formal_results_csv: str
    run_summary_json: str
    dispatch_min_p_json: str | None = None
    simulation_report_md: str | None = None
    configured_outputs_yaml: str | None = None

    def to_dict(self) -> Dict[str, str]:
        data = {
            "output_dir": self.output_dir,
            "formal_results_csv": self.formal_results_csv,
            "run_summary_json": self.run_summary_json,
        }
        if self.dispatch_min_p_json:
            data["dispatch_min_p_json"] = self.dispatch_min_p_json
        if self.simulation_report_md:
            data["simulation_report_md"] = self.simulation_report_md
        if self.configured_outputs_yaml:
            data["configured_outputs_yaml"] = self.configured_outputs_yaml
        return data


@dataclass(frozen=True)
class HydroSimulationJsonOutputs:
    run_summary: Dict[str, Any]
    dispatch_min_p: Any | None = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"run_summary": self.run_summary}
        if self.dispatch_min_p is not None:
            data["dispatch_min_p"] = self.dispatch_min_p
        if self.extra:
            data.update(self.extra)
        return data


@dataclass(frozen=True)
class HydroSimulationArtifacts:
    """仿真输出契约：文件输出、JSON 输出，以及显式混合输出。"""

    files: HydroSimulationFileOutputs
    json: HydroSimulationJsonOutputs

    def to_file_dict(self) -> Dict[str, str]:
        return self.files.to_dict()

    def to_json_dict(self) -> Dict[str, Any]:
        return self.json.to_dict()

    def to_mixed_dict(self) -> Dict[str, Any]:
        return {
            "files": self.to_file_dict(),
            "json": self.to_json_dict(),
        }

    def to_dict(self, mode: HydroOutputMode = "mixed") -> Dict[str, Any]:
        if mode == "file":
            return self.to_file_dict()
        if mode == "json":
            return self.to_json_dict()
        return self.to_mixed_dict()


@dataclass(frozen=True)
class HydroRandomSimulationRequest:
    sim_steps: int = 720
    warm_steps: int = 720
    output_dir: str | None = None
    make_plots: bool = True
    progress_interval: int = 100
    flow_seed: int = 555
    power_seed: int = 123
    flow_range: Tuple[float, float] = (1700.0, 3300.0)
    power_range: Tuple[float, float] = (1500.0, 4800.0)


@dataclass(frozen=True)
class HydroConfiguredSimulationRequest:
    time_series_file: str = "time_series_power_planning.json"
    mpc_config_file: str = "mpc_config.yaml"
    initial_states_file: str = "initial_states.yaml"
    constraints_file: str = "constrains_targets.yaml"
    sim_steps: int | None = None
    warm_steps: int = 0
    output_dir: str | None = None
    make_plots: bool = False
    progress_interval: int = 100
    output_sample_interval: int = 15
