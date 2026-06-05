from __future__ import annotations
from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import Field, AliasChoices
from .models import (
    AgentInstanceStatus,
    SimulationContext,
    HydroAgent,
    HydroAgentInstance,
    TopHydroObject,
    CommandStatus,
)
from .base import HydroBaseModel
from hydros_agent_sdk.mpc.models import MpcResult

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
SIMCMD_HYDRO_EVENT_COMMAND = "hydro_event_command"
SIMCMD_HYDRO_EVENT_ACK_RESPONSE = "hydro_event_ack_response"
SIMCMD_AGENT_INSTANCE_STATUS_REPORT = "report_agent_instance_status"
SIMCMD_MPC_RESULT_REPORT = "mpc_result_report"
SIMCMD_IDENTIFIED_PARAMS_REPORT = "identified_params_report"
SIMCMD_HYDRO_ALERT_REPORT = "report_hydro_alert"
SIMCMD_OUTFLOW_TIME_SERIES_REQUEST = "outflow_time_series_request"
SIMCMD_OUTFLOW_TIME_SERIES_RESPONSE = "outflow_time_series_response"
SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST = "outflow_time_series_data_update_request"
SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_RESPONSE = "outflow_time_series_data_update_response"
SIMCMD_DEVICE_STATUS_CHANGE_RESPONSE = "device_status_change_response"

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
    managed_top_objects: Dict[str, List[TopHydroObject]] = Field(default_factory=dict)

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

from .events import HydroEvent, TimeSeriesDataChangedEvent, OutflowTimeSeriesEvent, OutflowTimeSeriesDataChangedEvent
from .events import HydroEventUnion
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

class HydroEventCommand(SimCoordinationRequest):
    command_type: Literal["hydro_event_command"] = SIMCMD_HYDRO_EVENT_COMMAND
    target_agent_instance: Optional[HydroAgentInstance] = None
    payload: HydroEventUnion

class HydroEventAckResponse(SimCoordinationResponse):
    command_type: Literal["hydro_event_ack_response"] = SIMCMD_HYDRO_EVENT_ACK_RESPONSE

class OutflowTimeSeriesRequest(SimCoordinationRequest):
    command_type: Literal["outflow_time_series_request"] = SIMCMD_OUTFLOW_TIME_SERIES_REQUEST
    target_agent_instance: HydroAgentInstance
    hydro_event: OutflowTimeSeriesEvent = Field(
        validation_alias=AliasChoices("hydro_event", "outflow_time_series_event")
    )

class OutflowTimeSeriesResponse(SimCoordinationResponse):
    command_type: Literal["outflow_time_series_response"] = SIMCMD_OUTFLOW_TIME_SERIES_RESPONSE
    hydro_event: HydroEvent
    outflow_time_series_map: Dict[str, List[ObjectTimeSeries]]

class OutflowTimeSeriesDataUpdateRequest(SimCoordinationRequest):
    command_type: Literal["outflow_time_series_data_update_request"] = SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST
    outflow_time_series_data_changed_event: OutflowTimeSeriesDataChangedEvent

class OutflowTimeSeriesDataUpdateResponse(SimCoordinationResponse):
    command_type: Literal["outflow_time_series_data_update_response"] = SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_RESPONSE

class DeviceStatusChangeResponse(SimCoordinationResponse):
    command_type: Literal["device_status_change_response"] = SIMCMD_DEVICE_STATUS_CHANGE_RESPONSE
    object_time_series: List[ObjectTimeSeries] = Field(
        default_factory=list,
        validation_alias=AliasChoices("object_time_series", "objectTimeSeries"),
    )

# --- Report Commands ---

class AgentInstanceStatusReport(SimCommand):
    """
    Report for agent instance status updates.
    Sent when an agent instance is created or its status changes.
    """
    command_type: Literal["report_agent_instance_status"] = SIMCMD_AGENT_INSTANCE_STATUS_REPORT
    source_agent_instance: HydroAgentInstance
    agent_instance_status: AgentInstanceStatus = Field(
        validation_alias=AliasChoices("agent_instance_status", "agentInstanceStatus")
    )
    init_result: Optional[Dict[str, Any]] = None

class MpcResultReport(SimCommand):
    """
    Report for MPC optimization results.
    Sent by central scheduling agents and consumed by coordinator/data.
    """
    command_type: Literal["mpc_result_report"] = SIMCMD_MPC_RESULT_REPORT
    source_agent_instance: HydroAgentInstance
    mpc_results: List[MpcResult]

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
    HydroEventCommand,
    HydroEventAckResponse,
    OutflowTimeSeriesRequest,
    OutflowTimeSeriesResponse,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
    DeviceStatusChangeResponse,
    AgentInstanceStatusReport,
    MpcResultReport,
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
