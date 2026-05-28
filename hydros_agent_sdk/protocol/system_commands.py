"""
Hydros Agent SDK 的系统命令模型。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field

from hydros_agent_sdk.utils import generate_system_command_id

from .base import HydroBaseModel
from .models import CommandStatus
from hydros_agent_sdk.agent_commands.models import CommandLogDTO


class SystemCmd(HydroBaseModel):
    """所有系统命令共享的基础模型。"""

    command_id: str = Field(default_factory=generate_system_command_id)


class SystemCommand(SystemCmd):
    """系统命令公共字段。"""

    command_type: str
    command_status: Optional[CommandStatus] = None
    source_id: Optional[str] = None
    target_id: Optional[str] = None

    def auth(self) -> None:
        return None


class SystemCommandRequest(SystemCommand):
    """系统命令请求的基础字段。"""

    need_ack_reply: Optional[bool] = None
    acked: Optional[bool] = None


class SystemCommandResponse(SystemCommand):
    """系统命令响应的基础字段。"""

    error_code: Optional[str] = None
    error_detail: Optional[str] = None


class HydroCommandLogReportRequest(SystemCommandRequest):
    """智能体命令日志批量上报请求。"""

    command_type: Literal["agent_command_logs_report_request"] = "agent_command_logs_report_request"
    agent_logs: List[CommandLogDTO] = Field(default_factory=list)
    system_id: Optional[str] = None
