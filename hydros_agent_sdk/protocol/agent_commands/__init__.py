"""Agent command 的稳定 wire DTO 与 command catalog。"""

from .catalog import AgentCommandCatalog
from .commands import (
    HydroCommandReceivedAckReply,
    HydroEventReportRequest,
    HydroEventReportResponse,
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)

__all__ = [
    "AgentCommandCatalog",
    "HydroCommandReceivedAckReply",
    "HydroEventReportRequest",
    "HydroEventReportResponse",
    "HydroStationTargetValueRequest",
    "HydroStationTargetValueResponse",
]
