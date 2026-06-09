"""
具体的 agent command 模型。
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import Field, field_validator, model_validator

from hydros_agent_sdk.protocol.base import HydroBaseModel

from .base import (
    AgentCommand,
    AgentCommandRequest,
    AgentCommandResponse,
    parse_agent_command,
    register_agent_command,
)
from .types import AgentCommandTypes


@register_agent_command
class DisturbanceNodeWaterFlowRequest(AgentCommandRequest):
    """分水口流量调整请求。"""

    command_type: Literal[
        "disturbance_node_water_flow_request"
    ] = AgentCommandTypes.AGTCMD_DISTURBANCE_NODE_WATER_FLOW_REQUEST
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    object_type: Optional[str] = None
    value: float


@register_agent_command
class DisturbanceNodeWaterFlowResponse(AgentCommandResponse):
    """分水口流量调整响应。"""

    command_type: Literal[
        "disturbance_node_water_flow_response"
    ] = AgentCommandTypes.AGTCMD_DISTURBANCE_NODE_WATER_FLOW_RESPONSE


@register_agent_command
class HydroCommandReceivedAckReply(AgentCommand):
    """收到请求后的 ACK 回执。"""

    command_type: Literal["request_revived_ack"] = AgentCommandTypes.AGTCMD_REQUEST_RECEIVED_ACK

    @classmethod
    def from_request(cls, request: AgentCommandRequest) -> "HydroCommandReceivedAckReply":
        return cls(
            command_id=request.command_id,
            command_status=request.command_status,
            source=request.target,
            target=request.source,
        )


@register_agent_command
class HydroDirectGateOpeningRequest(AgentCommandRequest):
    """直接调闸门开度请求。"""

    command_type: Literal["direct_gate_opening_request"] = AgentCommandTypes.AGTCMD_GATE_OPENING_REQUEST
    object_id: Optional[int] = None
    object_name: Optional[str] = None
    object_type: Optional[str] = None
    gate_opening: float


@register_agent_command
class HydroDirectGateOpeningResponse(AgentCommandResponse):
    """直接调闸门开度响应。"""

    command_type: Literal["direct_gate_opening_response"] = AgentCommandTypes.AGTCMD_GATE_OPENING_RESPONSE
    final_gate_opening: Optional[float] = None


@register_agent_command
class HydroEventReportRequest(AgentCommandRequest):
    """风险事件上报请求。"""

    command_type: Literal["agent_event_report_request"] = AgentCommandTypes.AGTCMD_AGENT_EVENT_REPORT_REQUEST
    risk_alert: Dict[str, Any] = Field(default_factory=dict)


@register_agent_command
class HydroEventReportResponse(AgentCommandResponse):
    """风险事件上报响应。"""

    command_type: Literal["agent_event_report_response"] = AgentCommandTypes.AGTCMD_AGENT_EVENT_REPORT_RESPONSE


@register_agent_command
class HydroStationTargetValueRequest(AgentCommandRequest):
    """更通用的站点目标值下发请求。"""

    command_type: Literal[
        "update_station_target_value_request"
    ] = AgentCommandTypes.AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST
    object_id: Optional[int] = None
    object_type: str = Field(..., min_length=1)
    target_value: Any
    target_value_type: str = Field(..., min_length=1)

    @field_validator("object_type", "target_value_type")
    @classmethod
    def _required_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

    @field_validator("target_value")
    @classmethod
    def _target_value_not_none(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("target_value 不能为空")
        return value


@register_agent_command
class HydroStationTargetValueResponse(AgentCommandResponse):
    """更通用的站点目标值下发响应。"""

    command_type: Literal[
        "update_station_target_value_response"
    ] = AgentCommandTypes.AGTCMD_UPDATE_STATION_TARGET_VALUE_RESPONSE
    target_value_type: Optional[str] = None
    target_value: Optional[Any] = None


@register_agent_command
class HydroTargetWaterLevelRequest(AgentCommandRequest):
    """目标水位更新请求。"""

    command_type: Literal[
        "update_target_water_level_request"
    ] = AgentCommandTypes.AGTCMD_UPDATE_TARGET_WATER_LEVEL_REQUEST
    target_water_level: float


@register_agent_command
class HydroTargetWaterLevelResponse(AgentCommandResponse):
    """目标水位更新响应。"""

    command_type: Literal[
        "update_target_water_level_response"
    ] = AgentCommandTypes.AGTCMD_UPDATE_TARGET_WATER_LEVEL_RESPONSE


class AgentCommandEnvelope(HydroBaseModel):
    """用于基于注册表进行多态解析的包裹模型。"""

    command: AgentCommand

    @model_validator(mode="before")
    @classmethod
    def _normalize_command(cls, data):
        if isinstance(data, dict) and "command" in data:
            payload = dict(data)
            payload["command"] = parse_agent_command(payload["command"])
            return payload
        return data


def build_ack_reply(request: AgentCommandRequest) -> HydroCommandReceivedAckReply:
    return HydroCommandReceivedAckReply.from_request(request)
