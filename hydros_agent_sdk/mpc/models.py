from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from hydros_agent_sdk.protocol.base import HydroBaseModel
from hydros_agent_sdk.sensor_data import SensorData as _SensorData


def _payload_field(name: str, default: Any = None, default_factory: Any = None) -> Any:
    kwargs = {"default": default} if default_factory is None else {"default_factory": default_factory}
    return Field(
        **kwargs,
        serialization_alias=name,
    )


class ControlObjectResult(HydroBaseModel):
    object_type: Optional[str] = None
    node_id: Optional[int] = None
    node_name: Optional[str] = None
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    target_value: Optional[float] = None
    target_value_type: Optional[str] = None


class PredictedResult(HydroBaseModel):
    object_type: Optional[str] = None
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    front_water_level: Optional[float] = None
    back_water_level: Optional[float] = None
    final_target_value: Optional[float] = None
    final_target_value_type: Optional[str] = None
    out_flow: Optional[float] = None
    efficiency: Optional[float] = None


class HorizonStep(HydroBaseModel):
    horizon_step: Optional[int] = None
    # Executable control intents returned by planning. Consumers should build
    # control commands from this list, not from predicted_result_list.
    control_object_list: List[ControlObjectResult] = Field(default_factory=list)
    # Prediction-only data for display, replay, reporting, and analysis.
    predicted_result_list: List[PredictedResult] = Field(default_factory=list)


class MpcOptimizeRequest(HydroBaseModel):
    biz_scene_instance_id: str = _payload_field("biz_scene_instance_id", default=...)
    step_index: int = _payload_field("step_index", default=...)
    mpc_config_url: Optional[str] = _payload_field("mpc_config_url")
    control_config_url: Optional[str] = _payload_field("control_config_url")
    upstream_boundaries: Dict[str, List[float]] = _payload_field("upstream_boundaries", default_factory=dict)
    downstream_boundaries: Optional[Dict[str, Any]] = _payload_field("downstream_boundaries")
    sensor_data: List[_SensorData] = _payload_field("sensor_data", default_factory=list)
    fixed_controls: Dict[str, float] = _payload_field("fixed_controls", default_factory=dict)
    multi_profile: bool = _payload_field("multi_profile", default=False)
    include_diversion: bool = _payload_field("include_diversion", default=False)
    horizon_interval_seconds: Optional[int] = _payload_field("horizon_interval_seconds")


class MpcOptimizeResponse(HydroBaseModel):
    plan_type: Optional[str] = None
    loss: Optional[float] = None
    gate_operations: Optional[int] = None
    gate_amplitude: Optional[float] = None
    horizon_controls: List[HorizonStep] = Field(default_factory=list)
