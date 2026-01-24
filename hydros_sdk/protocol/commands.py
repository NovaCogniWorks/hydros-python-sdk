from __future__ import annotations
from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import Field, Discriminator
from .models import SimulationContext, HydroAgent, HydroAgentInstance, TopHydroObject, CommandStatus
from .base import HydroBaseModel

# Constants for Command Types
SIMCMD_TASK_INIT_REQUEST = "SIMCMD_TASK_INIT_REQUEST"
SIMCMD_TASK_INIT_RESPONSE = "SIMCMD_TASK_INIT_RESPONSE"
SIMCMD_TASK_TERMINATED_REQUEST = "SIMCMD_TASK_TERMINATED_REQUEST"
SIMCMD_TASK_TERMINATED_RESPONSE = "SIMCMD_TASK_TERMINATED_RESPONSE"
SIMCMD_TICK_CMD_REQUEST = "SIMCMD_TICK_CMD_REQUEST"
SIMCMD_TICK_CMD_RESPONSE = "SIMCMD_TICK_CMD_RESPONSE"
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

    class Config:
        # Pydantic configuration if needed
        pass

# --- Base Request/Response ---

class SimCoordinationRequest(SimCommand):
    pass

class SimCoordinationResponse(SimCommand):
    commandStatus: Optional[CommandStatus] = None
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None
    sourceAgentInstance: HydroAgentInstance

# --- Specific Commands ---

class SimTaskInitRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TASK_INIT_REQUEST"] = SIMCMD_TASK_INIT_REQUEST
    agentList: List[HydroAgent]
    bizSceneConfigurationUrl: Optional[str] = None

class SimTaskInitResponse(SimCoordinationResponse):
    command_type: Literal["SIMCMD_TASK_INIT_RESPONSE"] = SIMCMD_TASK_INIT_RESPONSE
    createdAgentInstances: List[HydroAgentInstance]
    managedTopObjects: Dict[str, List[TopHydroObject]]

class SimTaskTerminatedRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TASK_TERMINATED_REQUEST"] = SIMCMD_TASK_TERMINATED_REQUEST
    reason: Optional[str] = None

class SimTaskTerminatedResponse(SimCoordinationResponse):
    command_type: Literal["SIMCMD_TASK_TERMINATED_RESPONSE"] = SIMCMD_TASK_TERMINATED_RESPONSE

class TickCmdRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TICK_CMD_REQUEST"] = SIMCMD_TICK_CMD_REQUEST
    tickId: int
    deltaTime: float

class TickCmdResponse(SimCoordinationResponse):
    command_type: Literal["SIMCMD_TICK_CMD_RESPONSE"] = SIMCMD_TICK_CMD_RESPONSE

# --- Time Series Commands ---

from .events import HydroEvent, TimeSeriesDataChangedEvent
from .models import ObjectTimeSeries

class TimeSeriesCalculationRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TIME_SERIES_CALCULATION_REQUEST"] = SIMCMD_TIME_SERIES_CALCULATION_REQUEST
    targetAgentInstance: HydroAgentInstance
    hydroEvent: HydroEvent

class TimeSeriesCalculationResponse(SimCoordinationResponse):
    command_type: Literal["SIMCMD_TIME_SERIES_CALCULATION_RESPONSE"] = SIMCMD_TIME_SERIES_CALCULATION_RESPONSE
    hydroEvent: HydroEvent
    objectTimeSeriesList: List[ObjectTimeSeries]

class TimeSeriesDataUpdateRequest(SimCoordinationRequest):
    command_type: Literal["SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST"] = SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST
    timeSeriesDataChangedEvent: TimeSeriesDataChangedEvent

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
