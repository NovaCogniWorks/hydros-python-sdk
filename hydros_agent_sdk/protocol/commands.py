from __future__ import annotations
from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import Field, AliasChoices
from .models import (
    AgentInstanceStatus,
    SimulationContext,
    HydroAgent,
    HydroAgentInstance,
    TopHydroObject,
    CommandStatus,
)
from .base import HydroBaseModel
from .mpc_results import MpcResult
from hydros_agent_sdk.scenario_config import SimAgentProperties, SimulationRuntimeOptions

# 指令类型常量
SIMCMD_TASK_INIT_REQUEST = "task_init_request"
SIMCMD_TASK_INIT_RESPONSE = "task_init_response"
SIMCMD_TASK_TERMINATE_REQUEST = "task_terminate_request"
SIMCMD_TASK_TERMINATE_RESPONSE = "task_terminate_response"
SIMCMD_TICK_CMD_REQUEST = "tick_cmd_request"
SIMCMD_TICK_CMD_RESPONSE = "tick_cmd_response"
SIMCMD_TIME_SERIES_CALCULATION_REQUEST = "calculation_request"
SIMCMD_TIME_SERIES_CALCULATION_RESPONSE = "calculation_response"
SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST = "time_series_data_update_request"
SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE = "time_series_data_update_response"
SIMCMD_HYDRO_EVENT_COMMAND = "hydro_event_command"
SIMCMD_HYDRO_EVENT_ACK_RESPONSE = "hydro_event_ack_response"
SIMCMD_AGENT_INSTANCE_STATUS_REPORT = "report_agent_instance_status"
SIMCMD_MPC_RESULT_REPORT = "mpc_result_report"
SIMCMD_MPC_EXECUTION_STATUS_REPORT = "mpc_execution_status_report"
SIMCMD_PID_CONTROL_EXECUTION_REPORT = "pid_control_execution_report"
SIMCMD_STATION_CONTROL_EXECUTION_REPORT = "station_control_execution_report"
SIMCMD_IDENTIFIED_PARAMS_REPORT = "identified_params_report"
SIMCMD_HYDRO_ALERT_REPORT = "report_hydro_alert"
SIMCMD_OUTFLOW_TIME_SERIES_REQUEST = "outflow_time_series_request"
SIMCMD_OUTFLOW_TIME_SERIES_RESPONSE = "outflow_time_series_response"
SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST = "outflow_time_series_data_update_request"
SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_RESPONSE = "outflow_time_series_data_update_response"
SIMCMD_DEVICE_STATUS_CHANGE_RESPONSE = "device_status_change_response"

class HydroCmd(HydroBaseModel):
    command_id: str

class SimCommand(HydroCmd):
    command_type: str
    context: SimulationContext
    broadcast: bool = False

# --- 基础请求/响应 ---

class SimCoordinationRequest(SimCommand):
    pass

class SimCoordinationResponse(SimCommand):
    command_status: Optional[CommandStatus] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    source_agent_instance: HydroAgentInstance

# --- 具体指令 ---

class SimTaskInitRequest(SimCoordinationRequest):
    command_type: Literal["task_init_request"] = SIMCMD_TASK_INIT_REQUEST
    agent_list: List[HydroAgent]
    biz_scene_configuration_url: Optional[str] = None
    simulation_runtime_options: Optional[SimulationRuntimeOptions] = Field(
        default=None,
        validation_alias=AliasChoices("simulation_runtime_options", "simulationRuntimeOptions"),
    )
    sim_agent_properties: Optional[SimAgentProperties] = Field(
        default=None,
        validation_alias=AliasChoices("sim_agent_properties", "simAgentProperties"),
    )

class SimTaskInitResponse(SimCoordinationResponse):
    command_type: Literal["task_init_response"] = SIMCMD_TASK_INIT_RESPONSE
    created_agent_instances: List[HydroAgentInstance]
    managed_top_objects: Dict[str, List[TopHydroObject]] = Field(default_factory=dict)

class SimTaskTerminateRequest(SimCoordinationRequest):
    command_type: Literal["task_terminate_request"] = SIMCMD_TASK_TERMINATE_REQUEST
    reason: Optional[str] = None

class SimTaskTerminateResponse(SimCoordinationResponse):
    command_type: Literal["task_terminate_response"] = SIMCMD_TASK_TERMINATE_RESPONSE

class TickCmdRequest(SimCoordinationRequest):
    command_type: Literal["tick_cmd_request"] = SIMCMD_TICK_CMD_REQUEST
    step: int

class TickCmdResponse(SimCoordinationResponse):
    command_type: Literal["tick_cmd_response"] = SIMCMD_TICK_CMD_RESPONSE

# --- 时间序列指令 ---

from .events import HydroEvent, TimeSeriesDataChangedEvent, OutflowTimeSeriesEvent, OutflowTimeSeriesDataChangedEvent
from .events import HydroEventUnion
from .models import ObjectTimeSeries

class TimeSeriesCalculationRequest(SimCoordinationRequest):
    command_type: Literal["calculation_request"] = SIMCMD_TIME_SERIES_CALCULATION_REQUEST
    target_agent_instance: HydroAgentInstance
    hydro_event: HydroEvent

class TimeSeriesCalculationResponse(SimCoordinationResponse):
    command_type: Literal["calculation_response"] = SIMCMD_TIME_SERIES_CALCULATION_RESPONSE
    hydro_event: HydroEvent
    object_time_series_list: List[ObjectTimeSeries]

class TimeSeriesDataUpdateRequest(SimCoordinationRequest):
    command_type: Literal["time_series_data_update_request"] = SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST
    time_series_data_changed_event: TimeSeriesDataChangedEvent

class TimeSeriesDataUpdateResponse(SimCoordinationResponse):
    command_type: Literal["time_series_data_update_response"] = SIMCMD_TIME_SERIES_DATA_UPDATE_RESPONSE

class HydroEventCommand(SimCoordinationRequest):
    command_type: Literal["hydro_event_command"] = SIMCMD_HYDRO_EVENT_COMMAND
    target_agent_instance: Optional[HydroAgentInstance] = None
    payload: HydroEventUnion

class HydroEventAckResponse(SimCoordinationResponse):
    command_type: Literal["hydro_event_ack_response"] = SIMCMD_HYDRO_EVENT_ACK_RESPONSE

class OutflowTimeSeriesRequest(SimCoordinationRequest):
    command_type: Literal["outflow_time_series_request"] = SIMCMD_OUTFLOW_TIME_SERIES_REQUEST
    target_agent_instance: HydroAgentInstance
    hydro_event: OutflowTimeSeriesEvent = Field(
        validation_alias=AliasChoices("hydro_event", "outflow_time_series_event")
    )

class OutflowTimeSeriesResponse(SimCoordinationResponse):
    command_type: Literal["outflow_time_series_response"] = SIMCMD_OUTFLOW_TIME_SERIES_RESPONSE
    hydro_event: HydroEvent
    outflow_time_series_map: Dict[str, List[ObjectTimeSeries]]

class OutflowTimeSeriesDataUpdateRequest(SimCoordinationRequest):
    command_type: Literal["outflow_time_series_data_update_request"] = SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST
    outflow_time_series_data_changed_event: OutflowTimeSeriesDataChangedEvent

class OutflowTimeSeriesDataUpdateResponse(SimCoordinationResponse):
    command_type: Literal["outflow_time_series_data_update_response"] = SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_RESPONSE

class DeviceStatusChangeResponse(SimCoordinationResponse):
    command_type: Literal["device_status_change_response"] = SIMCMD_DEVICE_STATUS_CHANGE_RESPONSE
    object_time_series: List[ObjectTimeSeries] = Field(
        default_factory=list,
        validation_alias=AliasChoices("object_time_series", "objectTimeSeries"),
    )

# --- 报告指令 ---

class AgentInstanceStatusReport(SimCommand):
    """
    智能体实例状态更新报告。
    在智能体实例创建或状态变化时发送。
    """
    command_type: Literal["report_agent_instance_status"] = SIMCMD_AGENT_INSTANCE_STATUS_REPORT
    source_agent_instance: HydroAgentInstance
    agent_instance_status: AgentInstanceStatus = Field(
        validation_alias=AliasChoices("agent_instance_status", "agentInstanceStatus")
    )
    init_result: Optional[Dict[str, Any]] = None

class MpcResultReport(SimCommand):
    """
    MPC 优化结果报告。
    由中央调度智能体发送，并由协调器或数据侧消费。
    """
    command_type: Literal["mpc_result_report"] = SIMCMD_MPC_RESULT_REPORT
    source_agent_instance: HydroAgentInstance
    mpc_results: List[MpcResult]

class MpcExecutionStatusReport(SimCommand):
    """
    MPC 执行状态报告。
    Python SDK 只承载 Java 协议反序列化，具体状态语义由协调器消费。
    """
    command_type: Literal["mpc_execution_status_report"] = SIMCMD_MPC_EXECUTION_STATUS_REPORT
    source_agent_instance: HydroAgentInstance
    optimize_step: int = Field(validation_alias=AliasChoices("optimize_step", "optimizeStep"))
    horizon_step: int = Field(validation_alias=AliasChoices("horizon_step", "horizonStep"))
    biz_idem_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("biz_idem_key", "bizIdemKey"),
    )
    node_id: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("node_id", "nodeId"),
    )
    object_id: int = Field(validation_alias=AliasChoices("object_id", "objectId"))
    object_type: str = Field(validation_alias=AliasChoices("object_type", "objectType"))
    target_value_type: str = Field(
        validation_alias=AliasChoices("target_value_type", "targetValueType")
    )
    target_value: float = Field(validation_alias=AliasChoices("target_value", "targetValue"))
    execution_command_id: str = Field(
        validation_alias=AliasChoices("execution_command_id", "executionCommandId")
    )
    dispatch_key: str = Field(validation_alias=AliasChoices("dispatch_key", "dispatchKey"))
    execution_status: str = Field(validation_alias=AliasChoices("execution_status", "executionStatus"))
    execution_error_code: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("execution_error_code", "executionErrorCode"),
    )
    execution_error_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("execution_error_message", "executionErrorMessage"),
    )
    dispatched_at: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("dispatched_at", "dispatchedAt"),
    )
    executed_at: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("executed_at", "executedAt"),
    )

class PidControlExecutionReport(SimCommand):
    """
    PID 控制执行报告。
    run_result/actuator_results 保持轻量 dict，避免在 SDK 内复制 Java 深层模型。
    """
    command_type: Literal["pid_control_execution_report"] = SIMCMD_PID_CONTROL_EXECUTION_REPORT
    source_agent_instance: HydroAgentInstance
    run_result: Dict[str, Any] = Field(validation_alias=AliasChoices("run_result", "runResult"))
    actuator_results: List[Dict[str, Any]] = Field(
        validation_alias=AliasChoices("actuator_results", "actuatorResults")
    )

class StationControlExecutionReport(SimCommand):
    """
    站点控制执行报告。
    Python 侧只补齐协议反序列化，是否消费由后续路由/filter 决定。
    """
    command_type: Literal["station_control_execution_report"] = SIMCMD_STATION_CONTROL_EXECUTION_REPORT
    source_agent_instance: HydroAgentInstance
    target_agent_instance: Optional[HydroAgentInstance] = Field(
        default=None,
        validation_alias=AliasChoices("target_agent_instance", "targetAgentInstance"),
    )
    execution_command_id: str = Field(
        validation_alias=AliasChoices("execution_command_id", "executionCommandId")
    )
    control_run_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("control_run_id", "controlRunId"),
    )
    object_type: str = Field(validation_alias=AliasChoices("object_type", "objectType"))
    object_id: int = Field(validation_alias=AliasChoices("object_id", "objectId"))
    target_value_type: str = Field(
        validation_alias=AliasChoices("target_value_type", "targetValueType")
    )
    target_value: float = Field(validation_alias=AliasChoices("target_value", "targetValue"))
    execution_status: str = Field(validation_alias=AliasChoices("execution_status", "executionStatus"))
    execution_error_code: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("execution_error_code", "executionErrorCode"),
    )
    execution_error_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("execution_error_message", "executionErrorMessage"),
    )
    started_at: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("started_at", "startedAt"),
    )
    finished_at: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("finished_at", "finishedAt"),
    )

class ParameterIdentifiedReport(SimCommand):
    """
    参数识别结果报告。
    在智能体识别出新参数时发送。
    """
    command_type: Literal["identified_params_report"] = SIMCMD_IDENTIFIED_PARAMS_REPORT
    source_agent_instance: HydroAgentInstance
    recognized_params: List[Dict[str, Any]]  # IdentifiedParam 对象列表

class HydroAlertUpdatedReport(SimCommand):
    """
    水利告警更新报告。
    在发生水利告警事件时发送。
    """
    command_type: Literal["report_hydro_alert"] = SIMCMD_HYDRO_ALERT_REPORT
    source_agent_instance: HydroAgentInstance
    hydro_alert_event: Dict[str, Any]  # HydroAlertEvent 对象

# --- 多态反序列化 Union ---

# 定义全部可能指令类型的 Union
CommandUnion = Union[
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TickCmdResponse,
    TimeSeriesCalculationRequest,
    TimeSeriesCalculationResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    HydroEventCommand,
    HydroEventAckResponse,
    OutflowTimeSeriesRequest,
    OutflowTimeSeriesResponse,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
    DeviceStatusChangeResponse,
    AgentInstanceStatusReport,
    MpcResultReport,
    MpcExecutionStatusReport,
    PidControlExecutionReport,
    StationControlExecutionReport,
    ParameterIdentifiedReport,
    HydroAlertUpdatedReport,
    # 后续按需在这里补充其他指令
]

def get_command_type(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        return obj.get("command_type")
    return getattr(obj, "command_type", None)

class SimCommandEnvelope(HydroBaseModel):
    """
    基于 command_type 处理多态反序列化的包装对象。
    """
    command: CommandUnion = Field(discriminator='command_type')
