from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from hydros_agent_sdk.contract.v1.common import AgentInstanceRef, AgentInstanceStatus, TaskContextRef
from hydros_agent_sdk.contract.v1.coordination import SimCommand

SIMCMD_AGENT_INSTANCE_STATUS_REPORT = "report_agent_instance_status"
SIMCMD_IDENTIFIED_PARAMS_REPORT = "identified_params_report"
SIMCMD_HYDRO_ALERT_REPORT = "report_hydro_alert"


class AgentInstanceStatusReport(SimCommand):
    command_type: Literal["report_agent_instance_status"] = SIMCMD_AGENT_INSTANCE_STATUS_REPORT
    source_agent_instance_ref: AgentInstanceRef
    agent_instance_status: AgentInstanceStatus
    init_result: Optional[Dict[str, Any]] = None


class ParameterIdentifiedReport(SimCommand):
    command_type: Literal["identified_params_report"] = SIMCMD_IDENTIFIED_PARAMS_REPORT
    source_agent_instance_ref: AgentInstanceRef
    recognized_params: List[Dict[str, Any]]


class HydroAlertUpdatedReport(SimCommand):
    command_type: Literal["report_hydro_alert"] = SIMCMD_HYDRO_ALERT_REPORT
    source_agent_instance_ref: AgentInstanceRef
    hydro_alert_event: Dict[str, Any]
