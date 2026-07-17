from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ControlTaskType(str, Enum):
    STATION_FLOW_ALLOCATION = "STATION_FLOW_ALLOCATION"
    STATION_WATER_LEVEL_CONTROL = "STATION_WATER_LEVEL_CONTROL"
    DIRECT_ACTUATOR_CONTROL = "DIRECT_ACTUATOR_CONTROL"


class SignalType(str, Enum):
    TARGET = "TARGET"
    OBSERVATION = "OBSERVATION"
    REFERENCE = "REFERENCE"
    DISTURBANCE = "DISTURBANCE"
    UPSTREAM_SELECTED = "UPSTREAM_SELECTED"
    RESULT = "RESULT"


class ScalarRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_value: Optional[float] = None
    max_value: Optional[float] = None


class ControlAlgorithmContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    context_id: Optional[str] = None
    session_id: Optional[str] = None
    step_index: Optional[int] = None
    timestamp_ms: Optional[int] = None
    target_object_type: Optional[str] = None
    target_object_id: Optional[int] = None


class ControlSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SignalType
    object_type: str
    object_id: int
    value_type: str
    value: Optional[float] = None
    series: Optional[List[float]] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ControlActuator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    object_id: int
    available: bool = True
    values: Dict[str, Any] = Field(default_factory=dict)
    ranges: Dict[str, ScalarRange] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ControlActuatorTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    object_id: int
    target_values: Dict[str, float]


class ControlAlgorithmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    algorithm_type: str
    algorithm_version: Optional[str] = None
    control_task_type: ControlTaskType
    context: ControlAlgorithmContext
    signals: List[ControlSignal] = Field(default_factory=list)
    actuators: List[ControlActuator] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ControlAlgorithmStatus(str, Enum):
    CONTINUE = "CONTINUE"
    COMPLETED = "COMPLETED"
    HOLD = "HOLD"
    FAILED = "FAILED"


class ControlAlgorithmOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    request_id: str
    status: ControlAlgorithmStatus
    reason: Optional[str] = None
    actuator_targets: List[ControlActuatorTarget] = Field(default_factory=list)
    results: List[ControlSignal] = Field(default_factory=list)
    next_state: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
