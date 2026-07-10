from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .base import HydroBaseModel


class MpcPredictionResultDetail(HydroBaseModel):
    """MPC 预测结果明细协议 DTO。"""

    biz_idem_key: Optional[str] = None
    horizon_step: Optional[int] = None
    command_type: Optional[str] = None
    object_type: Optional[str] = None
    node_id: Optional[int] = None
    object_id: Optional[int] = None
    value: Optional[float] = None
    target_value: Optional[float] = None
    horizon_time: Optional[str] = None
    attributes: Optional[str] = None


class MpcPredictionResult(HydroBaseModel):
    """MPC 预测结果报告协议 DTO。"""

    biz_scene_instance_id: str
    waterway_id: Optional[str] = None
    tenant_id: Optional[str] = None
    biz_scenario_id: Optional[str] = None
    step: int
    total_step: Optional[int] = None
    execution_status: Optional[str] = None
    plan_type: Optional[str] = None
    loss: Optional[float] = None
    gate_operations: Optional[int] = None
    gate_amplitude: Optional[float] = None
    attributes: Optional[str] = None
    details: List[MpcPredictionResultDetail] = Field(default_factory=list)
