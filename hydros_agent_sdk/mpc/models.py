from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import ConfigDict, Field

from hydros_agent_sdk.control_algorithms.models import ControlSignal
from hydros_agent_sdk.protocol.base import HydroBaseModel
from hydros_agent_sdk.sensor_data import SensorData as _SensorData


def _payload_field(name: str, default: Any = None, default_factory: Any = None) -> Any:
    kwargs = {"default": default} if default_factory is None else {"default_factory": default_factory}
    return Field(
        **kwargs,
        serialization_alias=name,
    )


ScalarValue = Union[float, int, bool, str]


class MpcResultContractModel(HydroBaseModel):
    """严格校验规划契约，并立即暴露字段漂移的基础模型。"""

    model_config = ConfigDict(extra="forbid")


class ValueItem(MpcResultContractModel):
    """规划服务返回的带类型标量值。"""

    value_type: str
    value: ScalarValue

    def numeric_value(self) -> Optional[float]:
        """返回数值结果，但不把布尔值视为数字。"""

        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            return None
        return float(self.value)


class DeviceResult(MpcResultContractModel):
    """站点结果中某个设备的预测值。"""

    object_type: Optional[str] = None
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    value_list: List[ValueItem] = Field(default_factory=list)


class ControlObjectResult(MpcResultContractModel):
    """一个 horizon step 内某个站点的可执行控制意图。"""

    object_type: Optional[str] = None
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    target_value_list: List[ValueItem] = Field(default_factory=list)
    algorithm_input_signals: List[ControlSignal] = Field(default_factory=list)


class PredictedResult(MpcResultContractModel):
    """仅用于报告、回放和分析的站点及设备预测结果。"""

    object_type: Optional[str] = None
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    target_value: Optional[ValueItem] = None
    predicted_value_list: List[ValueItem] = Field(default_factory=list)
    device_result_list: List[DeviceResult] = Field(default_factory=list)


class HorizonStep(MpcResultContractModel):
    horizon_step: Optional[int] = None
    # 规划服务返回的可执行控制意图。消费方必须从该列表构造控制指令，
    # 不能从 predicted_result_list 派生控制指令。
    control_object_list: List[ControlObjectResult] = Field(default_factory=list)
    # 仅用于展示、回放、报告和分析的预测数据。
    predicted_result_list: List[PredictedResult] = Field(default_factory=list)


class MpcOptimizeRequest(HydroBaseModel):
    biz_scene_instance_id: str = _payload_field("biz_scene_instance_id", default=...)
    step_index: int = _payload_field("step_index", default=...)
    mpc_config_url: Optional[str] = _payload_field("mpc_config_url")
    control_config_url: Optional[str] = _payload_field("control_config_url")
    prediction_horizon: int = _payload_field("predictionHorizon", default=...)
    upstream_boundaries: Dict[str, List[float]] = _payload_field("upstream_boundaries", default_factory=dict)
    diversion_boundaries: Optional[Dict[str, List[float]]] = _payload_field("diversionBoundaries")
    sensor_data: List[_SensorData] = _payload_field("sensor_data", default_factory=list)
    fixed_controls: Dict[str, float] = _payload_field("fixed_controls", default_factory=dict)
    multi_profile: bool = _payload_field("multi_profile", default=False)
    targets: Optional[Dict[int, List[float]]] = _payload_field("targets")
    include_diversion: bool = _payload_field("include_diversion", default=False)
    horizon_interval_seconds: Optional[int] = _payload_field("horizon_interval_seconds")


class MpcOptimizeResponse(HydroBaseModel):
    plan_type: Optional[str] = None
    loss: Optional[float] = None
    gate_operations: Optional[int] = None
    gate_amplitude: Optional[float] = None
    horizon_controls: List[HorizonStep] = Field(default_factory=list)
