from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import AliasChoices, Field, ConfigDict
from .base import HydroBaseModel

class AgentStatus(str, Enum):
    """
    匹配 Java 实现的智能体容器管理状态枚举。
    """
    INIT = "INIT"
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"

class AgentInstanceStatus(str, Enum):
    """
    匹配 Java 实现的智能体实例生命周期状态枚举。
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
    匹配 Java 实现的智能体驱动模式枚举。
    定义智能体如何响应仿真控制信号。
    """
    SIM_TICK_DRIVEN = "SIM_TICK_DRIVEN"  # Tick驱动：响应时钟节拍，同步执行仿真步骤
    EVENT_DRIVEN = "EVENT_DRIVEN"        # 事件驱动：响应特定事件，异步执行处理逻辑
    PROACTIVE = "PROACTIVE"              # 主动模式：现地部署模式，不受coordinator管理协调

class CommandStatus(str, Enum):
    """
    匹配 Java 实现的指令状态枚举。
    """
    INIT = "INIT"
    PROCESSING = "PROCESSING"
    SUCCEED = "SUCCEED"
    FAILED = "FAILED"

class Tenant(HydroBaseModel):
    """
    表示租户信息。
    """
    tenant_id: str
    tenant_name: str

class BizScenario(HydroBaseModel):
    """
    表示业务场景信息。
    """
    biz_scenario_id: str
    biz_scenario_name: str

class Waterway(HydroBaseModel):
    """
    表示水系信息。
    """
    waterway_id: str
    waterway_name: str

class SimulationContext(HydroBaseModel):
    """
    表示仿真上下文，用于支持多任务隔离。
    """
    biz_scene_instance_id: str
    tenant: Optional[Tenant] = None
    biz_scenario: Optional[BizScenario] = None
    waterway: Optional[Waterway] = None
    valid: bool = True

class HydroAgent(HydroBaseModel):
    """
    表示智能体定义。
    """
    agent_code: str
    agent_type: str
    agent_name: Optional[str] = None
    agent_configuration_url: Optional[str] = None

class HydroAgentInstance(HydroAgent):
    """
    表示正在运行的智能体实例。
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
        """兼容旧 SDK 的名称，对应 Java 兼容字段 cluster_id。"""
        return self.cluster_id

    @hydros_cluster_id.setter
    def hydros_cluster_id(self, value: str) -> None:
        self.cluster_id = value

    @property
    def hydros_node_id(self) -> str:
        """兼容旧 SDK 的名称，对应 Java 兼容字段 node_id。"""
        return self.node_id

    @hydros_node_id.setter
    def hydros_node_id(self, value: str) -> None:
        self.node_id = value

class TopHydroObject(HydroBaseModel):
    """
    表示仿真管理的顶层水利对象。

    使用灵活 schema 兼容协调器下发的不同对象类型（例如闸站、渠道等）
    以及它们不同的嵌套属性。
    """
    model_config = ConfigDict(extra='allow')

    object_id: Optional[int] = None
    object_name: Optional[str] = None
    object_type: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)

# --- 时序数据模型 ---

class TimeSeriesValue(HydroBaseModel):
    step: Optional[int] = None
    time: Optional[Any] = None # 使用 Any 兼容 Date/datetime 泛型支持
    value: Optional[float] = None

class ObjectTimeSeries(HydroBaseModel):
    time_series_name: Optional[str] = None
    object_id: Optional[int] = None
    object_ids: List[int] = Field(
        default_factory=list,
        validation_alias=AliasChoices("object_ids", "objectIds"),
    )
    object_type: Optional[str] = None
    object_name: Optional[str] = None
    metrics_code: Optional[str] = None
    time_series: List[TimeSeriesValue] = Field(default_factory=list)
