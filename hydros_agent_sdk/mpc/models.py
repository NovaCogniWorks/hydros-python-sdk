from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, Field

from hydros_agent_sdk.protocol.base import HydroBaseModel


def _camel_field(*names: str, default: Any = None, default_factory: Any = None) -> Any:
    kwargs = {"default": default} if default_factory is None else {"default_factory": default_factory}
    return Field(
        **kwargs,
        validation_alias=AliasChoices(*names),
        serialization_alias=names[0],
    )


class SensorData(HydroBaseModel):
    object_id: Optional[int] = _camel_field("objectId", "object_id")
    object_type: Optional[str] = _camel_field("objectType", "object_type")
    metrics_code: Optional[str] = _camel_field("metricsCode", "metrics_code")
    position_code: Optional[str] = _camel_field("positionCode", "position_code")
    value: Optional[float] = None
    step_index: Optional[int] = _camel_field("stepIndex", "step_index", "step")


class DeviceOpening(HydroBaseModel):
    device_type: Optional[str] = None
    node_id: Optional[int] = None
    node_name: Optional[str] = None
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    value: Optional[float] = None
    counts: Optional[int] = None


class TargetNode(HydroBaseModel):
    device_type: Optional[str] = None
    node_id: Optional[int] = None
    node_name: Optional[str] = None
    water_level: Optional[float] = None
    target_water_level: Optional[float] = Field(
        None,
        validation_alias=AliasChoices("target_water_value", "target_water_level"),
        serialization_alias="target_water_value",
    )
    out_water_level: Optional[float] = None
    total_flow: Optional[float] = None
    inflow: Optional[float] = None


class HorizonControlStep(HydroBaseModel):
    horizon_step: Optional[int] = None
    opening_list: List[DeviceOpening] = Field(default_factory=list)
    target_node_list: List[TargetNode] = Field(default_factory=list)


class MpcOptimizeRequest(HydroBaseModel):
    biz_scene_instance_id: str
    step_index: int = _camel_field("stepIndex", "step_index", default=...)
    mpc_config_url: Optional[str] = _camel_field("mpcConfigUrl", "mpc_config_url")
    control_config_url: Optional[str] = _camel_field("controlConfigUrl", "control_config_url")
    upstream_boundaries: Dict[str, List[float]] = Field(default_factory=dict)
    downstream_boundaries: Optional[Dict[str, Any]] = None
    sensor_data: List[SensorData] = _camel_field("sensorData", "sensor_data", default_factory=list)
    fixed_controls: Dict[str, float] = _camel_field("fixedControls", "fixed_controls", default_factory=dict)
    multi_profile: bool = _camel_field("multiProfile", "multi_profile", default=False)
    targets: Dict[int, List[float]] = Field(default_factory=dict)
    include_diversion: bool = _camel_field("includeDiversion", "include_diversion", default=False)


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
