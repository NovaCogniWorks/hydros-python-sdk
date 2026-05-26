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
    object_id: Optional[int] = _payload_field("objectId")
    object_type: Optional[str] = _payload_field("objectType")
    metrics_code: Optional[str] = _payload_field("metricsCode")
    position_code: Optional[str] = _payload_field("positionCode")
    value: Optional[float] = None
    step_index: Optional[int] = _payload_field("stepIndex")


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
    target_water_level: Optional[float] = None
    out_water_level: Optional[float] = None
    total_flow: Optional[float] = None
    inflow: Optional[float] = None


class HorizonControlStep(HydroBaseModel):
    horizon_step: Optional[int] = None
    opening_list: List[DeviceOpening] = Field(default_factory=list)
    target_node_list: List[TargetNode] = Field(default_factory=list)


class MpcOptimizeRequest(HydroBaseModel):
    biz_scene_instance_id: str
    step_index: int = _payload_field("stepIndex", default=...)
    mpc_config_url: Optional[str] = _payload_field("mpcConfigUrl")
    control_config_url: Optional[str] = _payload_field("controlConfigUrl")
    upstream_boundaries: Dict[str, List[float]] = Field(default_factory=dict)
    downstream_boundaries: Optional[Dict[str, Any]] = None
    sensor_data: List[SensorData] = _payload_field("sensorData", default_factory=list)
    fixed_controls: Dict[str, float] = _payload_field("fixedControls", default_factory=dict)
    multi_profile: bool = _payload_field("multiProfile", default=False)
    targets: Dict[int, List[float]] = Field(default_factory=dict)
    include_diversion: bool = _payload_field("includeDiversion", default=False)


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
