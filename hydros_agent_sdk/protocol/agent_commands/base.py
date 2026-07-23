"""
智能体指令协议基础模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Type, TypeVar

from hydros_agent_sdk.protocol.base import HydroCmd
from hydros_agent_sdk.protocol.models import CommandStatus, HydroAgentInstance


ResponseType = TypeVar("ResponseType", bound="AgentCommandResponse")

class AgentCommand(HydroCmd):
    """所有智能体指令的公共字段。"""

    command_type: str
    timestamp_ms: Optional[datetime] = None
    command_status: Optional[CommandStatus] = None
    command_response: Optional[str] = None
    source: Optional[HydroAgentInstance] = None
    target: Optional[HydroAgentInstance] = None
    wait_on_util_send: Optional[datetime] = None
    security_check: bool = False

class AgentCommandRequest(AgentCommand):
    """智能体指令请求的公共字段。"""

    need_ack_reply: Optional[bool] = None
    acked: Optional[bool] = None


class AgentCommandResponse(AgentCommand):
    """智能体指令响应的公共字段。"""

    success: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @classmethod
    def from_request(cls: Type[ResponseType], request: AgentCommandRequest, **kwargs: Any) -> ResponseType:
        return cls(
            command_id=request.command_id,
            source=request.target,
            target=request.source,
            **kwargs,
        )
