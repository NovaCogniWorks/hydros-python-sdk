"""控制算法的 Python SDK 标准模型。

本模块与 Java ``hydros-agent-protocol`` 的控制算法模型保持同名字段和
相同枚举语义，但不依赖共享 JSON 或 Java 运行时。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from hydros_agent_sdk.protocol.base import HydroBaseModel


class ControlAlgorithmModel(HydroBaseModel):
    """控制算法模型基类，拒绝未声明字段以尽早发现双端字段漂移。"""

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class ControlTaskType(str, Enum):
    """控制算法需要完成的任务类型。"""

    STATION_FLOW_ALLOCATION = "STATION_FLOW_ALLOCATION"
    STATION_WATER_LEVEL_CONTROL = "STATION_WATER_LEVEL_CONTROL"
    DIRECT_ACTUATOR_CONTROL = "DIRECT_ACTUATOR_CONTROL"


class ControlAlgorithmStatus(str, Enum):
    """单次控制算法调用的决策状态。"""

    CONTINUE = "CONTINUE"
    COMPLETED = "COMPLETED"
    HOLD = "HOLD"
    FAILED = "FAILED"


class SignalType(str, Enum):
    """控制信号在算法输入或输出中的语义角色。"""

    TARGET = "TARGET"
    OBSERVATION = "OBSERVATION"
    REFERENCE = "REFERENCE"
    DISTURBANCE = "DISTURBANCE"
    UPSTREAM_SELECTED = "UPSTREAM_SELECTED"
    RESULT = "RESULT"


class ControlAlgorithmContext(ControlAlgorithmModel):
    """单次算法调用的最小身份、时间和目标对象上下文。"""

    request_id: str
    context_id: Optional[str] = None
    step_index: Optional[int] = None
    elapsed_seconds: Optional[float] = None
    target_object_type: Optional[str] = None
    target_object_id: Optional[int] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ControlSignal(ControlAlgorithmModel):
    """目标、观测、参考、扰动或结果的统一标量/时域信号。"""

    type: SignalType
    object_type: str
    object_id: int
    value_type: str
    value: Optional[float] = None
    series: List[float] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ControlValueRange(ControlAlgorithmModel):
    """一个执行器数值类型的允许范围。"""

    min_value: Optional[float] = None
    max_value: Optional[float] = None


class ControlActuator(ControlAlgorithmModel):
    """算法调用时一个执行器的当前事实、可用性和安全范围。"""

    object_type: str
    object_id: int
    available: bool = False
    values: Dict[str, float] = Field(default_factory=dict)
    ranges: Dict[str, ControlValueRange] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ControlActuatorTarget(ControlAlgorithmModel):
    """算法计算出的候选执行器目标，尚不代表设备已执行。"""

    object_type: str
    object_id: int
    target_values: Dict[str, float] = Field(default_factory=dict)


class ControlAlgorithmInput(ControlAlgorithmModel):
    """与 Java 同形、但由 Python SDK 独立维护的算法标准输入。"""

    schema_version: str
    algorithm_type: str
    algorithm_version: Optional[str] = None
    control_task_type: ControlTaskType
    context: ControlAlgorithmContext
    signals: List[ControlSignal] = Field(default_factory=list)
    actuators: List[ControlActuator] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ControlAlgorithmOutput(ControlAlgorithmModel):
    """与 Java 同形、但由 Python SDK 独立维护的算法标准输出。"""

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
