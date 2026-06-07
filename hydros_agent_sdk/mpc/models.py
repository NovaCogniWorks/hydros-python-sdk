from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from hydros_agent_sdk.protocol.base import HydroBaseModel


def _payload_field(name: str, default: Any = None, default_factory: Any = None) -> Any:
    kwargs = {"default": default} if default_factory is None else {"default_factory": default_factory}
    return Field(
        **kwargs,
        serialization_alias=name,
    )


class SensorData(HydroBaseModel):
    object_id: Optional[int] = _payload_field("object_id")
    object_type: Optional[str] = _payload_field("object_type")
    metrics_code: Optional[str] = _payload_field("metrics_code")
    position_code: Optional[str] = _payload_field("position_code")
    value: Optional[float] = None
    step_index: Optional[int] = _payload_field("step_index")
    attributes: Optional[str] = _payload_field("attributes")


class ControlDeviceResult(HydroBaseModel):
    device_type: Optional[str] = None
    node_id: Optional[int] = None
    node_name: Optional[str] = None
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    value: Optional[float] = None
    counts: Optional[int] = None


class PredictedResult(HydroBaseModel):
    device_type: Optional[str] = None
    node_id: Optional[int] = None
    node_name: Optional[str] = None
    front_water_level: Optional[float] = None
    target_water_level: Optional[float] = None
    back_water_level: Optional[float] = None
    total_flow: Optional[float] = None
    inflow: Optional[float] = None


class HorizonControlStep(HydroBaseModel):
    horizon_step: Optional[int] = None
    control_device_list: List[ControlDeviceResult] = Field(default_factory=list)
    predicted_result_list: List[PredictedResult] = Field(default_factory=list)


class MpcOptimizeRequest(HydroBaseModel):
    biz_scene_instance_id: str = _payload_field("biz_scene_instance_id", default=...)
    step_index: int = _payload_field("step_index", default=...)
    mpc_config_url: Optional[str] = _payload_field("mpc_config_url")
    control_config_url: Optional[str] = _payload_field("control_config_url")
    upstream_boundaries: Dict[str, List[float]] = _payload_field("upstream_boundaries", default_factory=dict)
    downstream_boundaries: Optional[Dict[str, Any]] = _payload_field("downstream_boundaries")
    sensor_data: List[SensorData] = _payload_field("sensor_data", default_factory=list)
    fixed_controls: Dict[str, float] = _payload_field("fixed_controls", default_factory=dict)
    multi_profile: bool = _payload_field("multi_profile", default=False)
    include_diversion: bool = _payload_field("include_diversion", default=False)


class MpcOptimizeResponse(HydroBaseModel):
    plan_type: Optional[str] = None
    loss: Optional[float] = None
    gate_operations: Optional[int] = None
    gate_amplitude: Optional[float] = None
    horizon_controls: List[HorizonControlStep] = Field(default_factory=list)


class MpcResultDetail(HydroBaseModel):
    horizon_step: Optional[int] = None
    command_type: Optional[str] = None
    device_type: Optional[str] = None
    node_id: Optional[int] = None
    object_id: Optional[int] = None
    value: Optional[float] = None
    target_value: Optional[float] = None
    horizon_time: Optional[str] = None
    attributes: Optional[str] = None


class MpcResult(HydroBaseModel):
    biz_scene_instance_id: str
    waterway_id: Optional[str] = None
    tenant_id: Optional[str] = None
    biz_scenario_id: Optional[str] = None
    step: int
    plan_type: Optional[str] = None
    loss: Optional[float] = None
    gate_operations: Optional[int] = None
    gate_amplitude: Optional[float] = None
    attributes: Optional[str] = None
    details: List[MpcResultDetail] = Field(default_factory=list)
