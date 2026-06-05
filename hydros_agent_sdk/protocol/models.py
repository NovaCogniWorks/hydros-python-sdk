from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import AliasChoices, Field, ConfigDict
from .base import HydroBaseModel

class AgentStatus(str, Enum):
    """
    Agent container management status enumeration matching Java implementation.
    """
    INIT = "INIT"
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"

class AgentInstanceStatus(str, Enum):
    """
    Agent instance lifecycle status enumeration matching Java implementation.
    """
    INIT = "INIT"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"

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
    agent_configuration_url: Optional[str] = None

class HydroAgentInstance(HydroAgent):
    """
    Represents a running instance of an agent.
    """
    agent_id: str
    biz_scene_instance_id: str
    cluster_id: str = Field(
        validation_alias=AliasChoices(
            "cluster_id",
            "clusterId",
            "hydros_cluster_id",
            "hydrosClusterId",
        )
    )
    node_id: str = Field(
        validation_alias=AliasChoices(
            "node_id",
            "nodeId",
            "hydros_node_id",
            "hydrosNodeId",
        )
    )
    context: SimulationContext
    agent_status: AgentStatus = Field(
        default=AgentStatus.INIT,
        validation_alias=AliasChoices(
            "agent_status",
            "agentStatus",
        )
    )
    agent_instance_status: AgentInstanceStatus = Field(
        default=AgentInstanceStatus.INIT,
        validation_alias=AliasChoices(
            "agent_instance_status",
            "agentInstanceStatus",
        ),
    )
    drive_mode: AgentDriveMode

    @property
    def hydros_cluster_id(self) -> str:
        """Backward-compatible SDK name for Java-compatible cluster_id."""
        return self.cluster_id

    @hydros_cluster_id.setter
    def hydros_cluster_id(self, value: str) -> None:
        self.cluster_id = value

    @property
    def hydros_node_id(self) -> str:
        """Backward-compatible SDK name for Java-compatible node_id."""
        return self.node_id

    @hydros_node_id.setter
    def hydros_node_id(self, value: str) -> None:
        self.node_id = value

class TopHydroObject(HydroBaseModel):
    """
    Represents a top-level hydro object managed by the simulation.
    Uses flexible schema to accommodate varying object types from the coordinator
    (e.g., gate stations, channels, etc.) with different nested properties.
    """
    model_config = ConfigDict(extra='allow')

    object_id: Optional[int] = None
    object_name: Optional[str] = None
    object_type: Optional[str] = None
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
