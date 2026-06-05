"""
智能体指令日志 DTO 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from hydros_agent_sdk.protocol.base import HydroBaseModel
from hydros_agent_sdk.protocol.models import CommandStatus


class CommandLogDTO(HydroBaseModel):
    """智能体命令日志的可序列化快照。"""

    tenant_id: Optional[str] = None
    biz_scenario_id: Optional[str] = None
    biz_scene_instance_id: Optional[str] = None
    source_id: Optional[str] = None
    source_type: Optional[str] = None
    command_id: str
    command_type: Optional[str] = None
    command_request: Optional[str] = None
    source_agent_id: Optional[str] = None
    source_agent_name: Optional[str] = None
    target_agent_id: Optional[str] = None
    target_agent_name: Optional[str] = None
    need_ack_reply: Optional[bool] = None
    acked: Optional[bool] = None
    command_status: Optional[CommandStatus] = None
    command_response: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    reported: Optional[bool] = None
    gmt_create: Optional[datetime] = None
    gmt_modified: Optional[datetime] = None
