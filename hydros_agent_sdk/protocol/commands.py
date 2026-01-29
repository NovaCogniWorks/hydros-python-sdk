from __future__ import annotations
from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import Field, Discriminator
from .models import SimulationContext, HydroAgent, HydroAgentInstance, TopHydroObject, CommandStatus
from .base import HydroBaseModel

# Constants for Command Types
SIMCMD_TASK_INIT_REQUEST = "task_init_request"
SIMCMD_TASK_INIT_RESPONSE = "task_init_response"
SIMCMD_TASK_TERMINATE_REQUEST = "task_terminate_request"
SIMCMD_TASK_TERMINATE_RESPONSE = "task_terminate_response"
SIMCMD_TICK_CMD_REQUEST = "tick_cmd_request"
SIMCMD_TICK_CMD_RESPONSE = "tick_cmd_response"
SIMCMD_TIME_SERIES_CALCULATION_REQUEST = "calculation_request"
SIMCMD_TIME_SERIES_CALCULATION_RESPONSE = "calculation_response"
SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST = "time_series_data_update_request"
SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE = "time_series_data_update_response"
SIMCMD_AGENT_INSTANCE_STATUS_REPORT = "report_agent_instance_status"
SIMCMD_IDENTIFIED_PARAMS_REPORT = "identified_params_report"
SIMCMD_HYDRO_ALERT_REPORT = "report_hydro_alert"

class HydroCmd(HydroBaseModel):
    command_id: str

class SimCommand(HydroCmd):
    command_type: str
    context: SimulationContext
    broadcast: bool = False

# --- Base Request/Response ---

class SimCoordinationRequest(SimCommand):
    pass

class SimCoordinationResponse(SimCommand):
    command_status: Optional[CommandStatus] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    source_agent_instance: HydroAgentInstance

# --- Specific Commands ---

class SimTaskInitRequest(SimCoordinationRequest):
    command_type: Literal["task_init_request"] = SIMCMD_TASK_INIT_REQUEST
    agent_list: List[HydroAgent]
    biz_scene_configuration_url: Optional[str] = None

class SimTaskInitResponse(SimCoordinationResponse):
    command_type: Literal["task_init_response"] = SIMCMD_TASK_INIT_RESPONSE
    created_agent_instances: List[HydroAgentInstance]
    managed_top_objects: Dict[str, List[TopHydroObject]]

class SimTaskTerminateRequest(SimCoordinationRequest):
    command_type: Literal["task_terminate_request"] = SIMCMD_TASK_TERMINATE_REQUEST
    reason: Optional[str] = None

class SimTaskTerminateResponse(SimCoordinationResponse):
    command_type: Literal["task_terminate_response"] = SIMCMD_TASK_TERMINATE_RESPONSE

class TickCmdRequest(SimCoordinationRequest):
    command_type: Literal["tick_cmd_request"] = SIMCMD_TICK_CMD_REQUEST
    step: int

class TickCmdResponse(SimCoordinationResponse):
    command_type: Literal["tick_cmd_response"] = SIMCMD_TICK_CMD_RESPONSE

# --- Time Series Commands ---

from .events import HydroEvent, TimeSeriesDataChangedEvent
from .models import ObjectTimeSeries

class TimeSeriesCalculationRequest(SimCoordinationRequest):
    command_type: Literal["calculation_request"] = SIMCMD_TIME_SERIES_CALCULATION_REQUEST
    target_agent_instance: HydroAgentInstance
    hydro_event: HydroEvent

class TimeSeriesCalculationResponse(SimCoordinationResponse):
    command_type: Literal["calculation_response"] = SIMCMD_TIME_SERIES_CALCULATION_RESPONSE
    hydro_event: HydroEvent
    object_time_series_list: List[ObjectTimeSeries]

class TimeSeriesDataUpdateRequest(SimCoordinationRequest):
    command_type: Literal["time_series_data_update_request"] = SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST
    time_series_data_changed_event: TimeSeriesDataChangedEvent

class TimeSeriesDataUpdateResponse(SimCoordinationResponse):
    command_type: Literal["time_series_data_update_response"] = SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE

# --- Report Commands ---

class AgentInstanceStatusReport(SimCommand):
    """
    Report for agent instance status updates.
    Sent when an agent instance is created or its status changes.
    """
    command_type: Literal["report_agent_instance_status"] = SIMCMD_AGENT_INSTANCE_STATUS_REPORT
    source_agent_instance: HydroAgentInstance
    created_state: str
    init_result: Optional[Dict[str, Any]] = None

class ParameterIdentifiedReport(SimCommand):
    """
    Report for identified parameters.
    Sent when an agent identifies new parameters.
    """
    command_type: Literal["identified_params_report"] = SIMCMD_IDENTIFIED_PARAMS_REPORT
    source_agent_instance: HydroAgentInstance
    recognized_params: List[Dict[str, Any]]  # List of IdentifiedParam objects

class HydroAlertUpdatedReport(SimCommand):
    """
    Report for hydro alert updates.
    Sent when a hydro alert event occurs.
    """
    command_type: Literal["report_hydro_alert"] = SIMCMD_HYDRO_ALERT_REPORT
    source_agent_instance: HydroAgentInstance
    hydro_alert_event: Dict[str, Any]  # HydroAlertEvent object

# --- Union for Polymorphic Deserialization ---

# Define the Union of all possible command types
CommandUnion = Union[
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TickCmdResponse,
    TimeSeriesCalculationRequest,
    TimeSeriesCalculationResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    AgentInstanceStatusReport,
    ParameterIdentifiedReport,
    HydroAlertUpdatedReport,
    # Add other commands here as needed
]

def get_command_type(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        return obj.get("command_type")
    return getattr(obj, "command_type", None)

class SimCommandEnvelope(HydroBaseModel):
    """
    Wrapper to handle polymorphic deserialization based on command_type.
    """
    command: CommandUnion = Field(discriminator='command_type')
