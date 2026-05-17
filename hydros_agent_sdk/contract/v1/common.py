from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from hydros_agent_sdk.protocol.base import HydroBaseModel


class CommandStatus(str, Enum):
    INIT = "INIT"
    PROCESSING = "PROCESSING"
    SUCCEED = "SUCCEED"
    FAILED = "FAILED"


class AgentStatus(str, Enum):
    INIT = "INIT"
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


class AgentInstanceStatus(str, Enum):
    INIT = "INIT"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"


class AgentDriveMode(str, Enum):
    SIM_TICK_DRIVEN = "SIM_TICK_DRIVEN"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    PROACTIVE = "PROACTIVE"


class TaskContextRef(HydroBaseModel):
    biz_scene_instance_id: str
    tenant_id: Optional[str] = None
    biz_scenario_id: Optional[str] = None
    waterway_id: Optional[str] = None
    valid: Optional[bool] = True


class AgentDefinitionRef(HydroBaseModel):
    agent_code: str
    agent_type: str
    agent_name: Optional[str] = None
    agent_configuration_url: Optional[str] = None
    drive_mode: Optional[AgentDriveMode] = None


class AgentInstanceRef(HydroBaseModel):
    agent_id: str
    agent_code: str
    agent_type: str
    biz_scene_instance_id: str
    hydros_cluster_id: Optional[str] = None
    hydros_node_id: Optional[str] = None
    drive_mode: Optional[AgentDriveMode] = None
    agent_status: Optional[AgentStatus] = None
    agent_instance_status: Optional[AgentInstanceStatus] = None
    remark: Optional[str] = None


class TopHydroObject(HydroBaseModel):
    model_config = ConfigDict(extra="allow")

    object_id: Optional[int] = None
    object_name: Optional[str] = None
    object_type: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class TimeSeriesValue(HydroBaseModel):
    step: Optional[int] = None
    time: Optional[Any] = None
    value: Optional[float] = None


class ObjectTimeSeries(HydroBaseModel):
    time_series_name: Optional[str] = None
    object_id: Optional[int] = None
    object_type: Optional[str] = None
    object_name: Optional[str] = None
    metrics_code: Optional[str] = None
    time_series: List[TimeSeriesValue] = Field(default_factory=list)
