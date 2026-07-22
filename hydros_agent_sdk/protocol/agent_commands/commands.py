"""
具体的 agent command 协议模型。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from hydros_agent_sdk.control_algorithms.models import ControlSignal

from .base import (
    AgentCommand,
    AgentCommandRequest,
    AgentCommandResponse,
)
from .catalog import AgentCommandCatalog


class HydroCommandReceivedAckReply(AgentCommand):
    """收到请求后的 ACK 回执。"""

    command_type: Literal["request_revived_ack"] = AgentCommandCatalog.AGTCMD_REQUEST_RECEIVED_ACK

    @classmethod
    def from_request(cls, request: AgentCommandRequest) -> "HydroCommandReceivedAckReply":
        return cls(
            command_id=request.command_id,
            command_status=request.command_status,
            source=request.target,
            target=request.source,
        )


class HydroEventReportRequest(AgentCommandRequest):
    """风险事件上报请求。"""

    command_type: Literal["agent_event_report_request"] = AgentCommandCatalog.AGTCMD_AGENT_EVENT_REPORT_REQUEST
    risk_alert: Optional[Dict[str, Any]] = None


class HydroEventReportResponse(AgentCommandResponse):
    """风险事件上报响应。"""

    command_type: Literal["agent_event_report_response"] = AgentCommandCatalog.AGTCMD_AGENT_EVENT_REPORT_RESPONSE


class HydroStationTargetValueRequest(AgentCommandRequest):
    """更通用的站点目标值下发请求。"""

    command_type: Literal[
        "update_station_target_value_request"
    ] = AgentCommandCatalog.AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST
    object_id: Optional[int] = None
    object_type: str = Field(..., min_length=1)
    target_value: float
    target_value_type: str = Field(..., min_length=1)
    target_value_map: Dict[int, Any] = Field(default_factory=dict)
    group_id: Optional[str] = None
    group_size: Optional[int] = None
    main_step_index: Optional[int] = None
    planning_signals: List[ControlSignal] = Field(default_factory=list)

    @field_validator("object_type", "target_value_type")
    @classmethod
    def _required_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

class HydroStationTargetValueResponse(AgentCommandResponse):
    """更通用的站点目标值下发响应。"""

    command_type: Literal[
        "update_station_target_value_response"
    ] = AgentCommandCatalog.AGTCMD_UPDATE_STATION_TARGET_VALUE_RESPONSE
    object_id: Optional[int] = None
    target_value_type: Optional[str] = None
    target_value: Optional[Any] = None
    target_value_map: Optional[Dict[int, Any]] = None
