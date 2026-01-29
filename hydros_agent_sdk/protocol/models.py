from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import Field
from .base import HydroBaseModel

class AgentBizStatus(str, Enum):
    """
    Agent business status enumeration matching Java implementation.
    """
    INIT = "INIT"
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"

class AgentDriveMode(str, Enum):
    """
    Agent drive mode enumeration matching Java implementation.
    Defines how an agent responds to simulation control signals.
    """
    SIM_TICK_DRIVEN = "SIM_TICK_DRIVEN"  # Tick驱动：响应时钟节拍，同步执行仿真步骤
    EVENT_DRIVEN = "EVENT_DRIVEN"        # 事件驱动：响应特定事件，异步执行处理逻辑
    PROACTIVE = "PROACTIVE"              # 主动模式：现地部署模式，不受coordinator管理协调

class CommandStatus(str, Enum):
    """
    Command status enumeration matching Java implementation.
    """
    INIT = "INIT"
    PROCESSING = "PROCESSING"
    SUCCEED = "SUCCEED"
    FAILED = "FAILED"

class Tenant(HydroBaseModel):
    """
    Represents tenant information.
    """
    tenant_id: str
    tenant_name: str

class BizScenario(HydroBaseModel):
    """
    Represents business scenario information.
    """
    biz_scenario_id: str
    biz_scenario_name: str

class Waterway(HydroBaseModel):
    """
    Represents waterway information.
    """
    waterway_id: str
    waterway_name: str

class SimulationContext(HydroBaseModel):
    """
    Represents the simulation context, used to support multi-task isolation.
    """
    biz_scene_instance_id: str
    tenant: Optional[Tenant] = None
    biz_scenario: Optional[BizScenario] = None
    waterway: Optional[Waterway] = None
    valid: bool = True

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
    agent_biz_status: AgentBizStatus
    drive_mode: AgentDriveMode

class TopHydroObject(HydroBaseModel):
    """
    Placeholder for top-level hydro objects managed by the simulation.
    """
    id: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

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
