from __future__ import annotations
from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import Field, Discriminator
from .models import SimulationContext, HydroAgent, HydroAgentInstance, TopHydroObject, CommandStatus
from .base import HydroBaseModel

# Constants for Command Types
SIMCMD_TASK_INIT_REQUEST = "task_init_request"
SIMCMD_TASK_INIT_RESPONSE = "task_init_response"
SIMCMD_TASK_TERMINATED_REQUEST = "SIMCMD_TASK_TERMINATED_REQUEST"
SIMCMD_TASK_TERMINATED_RESPONSE = "SIMCMD_TASK_TERMINATED_RESPONSE"
SIMCMD_TICK_CMD_REQUEST = "tick_cmd_request"
SIMCMD_TICK_CMD_RESPONSE = "tick_cmd_response"
SIMCMD_TIME_SERIES_CALCULATION_REQUEST = "SIMCMD_TIME_SERIES_CALCULATION_REQUEST"
SIMCMD_TIME_SERIES_CALCULATION_RESPONSE = "SIMCMD_TIME_SERIES_CALCULATION_RESPONSE"
SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST = "SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST"
SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE = "SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE"

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

class SimTaskTerminatedRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TASK_TERMINATED_REQUEST"] = SIMCMD_TASK_TERMINATED_REQUEST
    reason: Optional[str] = None

class SimTaskTerminatedResponse(SimCoordinationResponse):
    command_type: Literal["SIMCMD_TASK_TERMINATED_RESPONSE"] = SIMCMD_TASK_TERMINATED_RESPONSE

class TickCmdRequest(SimCoordinationRequest):
    command_type: Literal["tick_cmd_request"] = SIMCMD_TICK_CMD_REQUEST
    tick_id: int
    delta_time: float

class TickCmdResponse(SimCoordinationResponse):
    command_type: Literal["tick_cmd_response"] = SIMCMD_TICK_CMD_RESPONSE

# --- Time Series Commands ---

from .events import HydroEvent, TimeSeriesDataChangedEvent
from .models import ObjectTimeSeries

class TimeSeriesCalculationRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TIME_SERIES_CALCULATION_REQUEST"] = SIMCMD_TIME_SERIES_CALCULATION_REQUEST
    target_agent_instance: HydroAgentInstance
    hydro_event: HydroEvent

class TimeSeriesCalculationResponse(SimCoordinationResponse):
    command_type: Literal["SIMCMD_TIME_SERIES_CALCULATION_RESPONSE"] = SIMCMD_TIME_SERIES_CALCULATION_RESPONSE
    hydro_event: HydroEvent
    object_time_series_list: List[ObjectTimeSeries]

class TimeSeriesDataUpdateRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST"] = SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST
    time_series_data_changed_event: TimeSeriesDataChangedEvent

class TimeSeriesDataUpdateResponse(SimCoordinationResponse):
    command_type: Literal["SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE"] = SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE

# --- Union for Polymorphic Deserialization ---

# Define the Union of all possible command types
CommandUnion = Union[
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminatedRequest,
    SimTaskTerminatedResponse,
    TickCmdRequest,
    TickCmdResponse,
    TimeSeriesCalculationRequest,
    TimeSeriesCalculationResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    # Add other commands here as needed
]

def get_command_type(obj: Any) -> str:
    if isinstance(obj, dict):
        return obj.get("command_type")
    return getattr(obj, "command_type", None)

class SimCommandEnvelope(HydroBaseModel):
    """
    Wrapper to handle polymorphic deserialization based on command_type.
    """
    command: CommandUnion = Field(discriminator='command_type')
