from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from hydros_agent_sdk.protocol.base import HydroBaseModel


def _payload_field(name: str, default: Any = None) -> Any:
    return Field(
        default=default,
        serialization_alias=name,
    )


class SensorData(HydroBaseModel):
    """通用现地指标/传感器观测值 DTO，供调度、优化和自定义算法复用。"""

    object_id: Optional[int] = _payload_field("object_id")
    object_type: Optional[str] = _payload_field("object_type")
    metrics_code: Optional[str] = _payload_field("metrics_code")
    position_code: Optional[str] = _payload_field("position_code")
    value: Optional[float] = None
    step_index: Optional[int] = _payload_field("step_index")
    attributes: Optional[str] = _payload_field("attributes")
