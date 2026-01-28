from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import Field
from .base import HydroBaseModel

class SimulationContext(HydroBaseModel):
    """
    Represents the simulation context, used to support multi-task isolation.
    """
    biz_scene_instance_id: str
    task_id: Optional[str] = None

class HydroAgent(HydroBaseModel):
    """
    Represents an agent definition.
    """
    agent_code: str
    agent_type: str
    agent_name: Optional[str] = None
    agent_configuration_url: str

class HydroAgentInstance(HydroAgent):
    """
    Represents a running instance of an agent.
    """
    agent_id: str
    biz_scene_instance_id: str
    hydros_cluster_id: str
    hydros_node_id: str
    context: SimulationContext
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TopHydroObject(HydroBaseModel):
    """
    Placeholder for top-level hydro objects managed by the simulation.
    """
    id: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class CommandStatus(str, Enum):
    """
    Command status enumeration matching Java implementation.
    """
    INIT = "INIT"
    PROCESSING = "PROCESSING"
    SUCCEED = "SUCCEED"
    FAILED = "FAILED"

# --- Time Series Models ---

class TimeSeriesValue(HydroBaseModel):
    step: Optional[int] = None
    time: Optional[Any] = None # Using Any for Date/datetime generic support
    value: Optional[float] = None

class ObjectTimeSeries(HydroBaseModel):
    time_series_name: Optional[str] = None
    object_id: Optional[int] = None
    object_type: Optional[str] = None
    object_name: Optional[str] = None
    metrics_code: Optional[str] = None
    time_series: List[TimeSeriesValue] = Field(default_factory=list)
