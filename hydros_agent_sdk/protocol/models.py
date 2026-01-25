from typing import List, Optional, Dict, Any
from pydantic import Field
from .base import HydroBaseModel

class SimulationContext(HydroBaseModel):
    """
    Represents the simulation context, used to support multi-task isolation.
    """
    bizSceneInstanceId: str
    taskId: Optional[str] = None

class HydroAgent(HydroBaseModel):
    """
    Represents an agent definition.
    """
    agentId: str
    name: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)

class HydroAgentInstance(HydroBaseModel):
    """
    Represents a running instance of an agent.
    """
    agentId: str
    instanceId: str
    context: SimulationContext
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TopHydroObject(HydroBaseModel):
    """
    Placeholder for top-level hydro objects managed by the simulation.
    """
    id: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class CommandStatus(HydroBaseModel):
    status: str

# --- Time Series Models ---

class TimeSeriesValue(HydroBaseModel):
    step: Optional[int] = None
    time: Optional[Any] = None # Using Any for Date/datetime generic support
    value: Optional[float] = None

class ObjectTimeSeries(HydroBaseModel):
    timeSeriesName: Optional[str] = None
    objectId: Optional[int] = None
    objectType: Optional[str] = None
    objectName: Optional[str] = None
    metricsCode: Optional[str] = None
    timeSeries: List[TimeSeriesValue] = Field(default_factory=list)
