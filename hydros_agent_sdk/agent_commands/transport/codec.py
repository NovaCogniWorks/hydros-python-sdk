"""Agent 指令 MQTT payload 解码。"""

from __future__ import annotations

from typing import Any, Mapping, Type

from hydros_agent_sdk.protocol.agent_commands import (
    AgentCommandCatalog,
    HydroCommandReceivedAckReply,
    HydroEventReportRequest,
    HydroEventReportResponse,
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.protocol.agent_commands.base import AgentCommand


class AgentCommandDecoder:
    """将 MQTT 字典载荷解码为已知 agent-command DTO。"""

    _command_models: Mapping[str, Type[AgentCommand]] = {
        AgentCommandCatalog.AGTCMD_REQUEST_RECEIVED_ACK: HydroCommandReceivedAckReply,
        AgentCommandCatalog.AGTCMD_AGENT_EVENT_REPORT_REQUEST: HydroEventReportRequest,
        AgentCommandCatalog.AGTCMD_AGENT_EVENT_REPORT_RESPONSE: HydroEventReportResponse,
        AgentCommandCatalog.AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST: HydroStationTargetValueRequest,
        AgentCommandCatalog.AGTCMD_UPDATE_STATION_TARGET_VALUE_RESPONSE: HydroStationTargetValueResponse,
    }

    def decode(self, payload: Mapping[str, Any]) -> AgentCommand:
        command_type = payload.get("command_type")
        if not isinstance(command_type, str) or not command_type:
            raise ValueError("agent command payload 缺少 command_type")

        command_model = self._command_models.get(command_type)
        if command_model is None:
            raise ValueError(f"不支持的 agent command_type: {command_type!r}")
        return command_model.model_validate(payload)
