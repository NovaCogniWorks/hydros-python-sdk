from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import Field

from hydros_agent_sdk.contract.v1.common import (
    AgentDefinitionRef,
    AgentInstanceRef,
    CommandStatus,
    ObjectTimeSeries,
    TaskContextRef,
    TopHydroObject,
)
from hydros_agent_sdk.contract.v1.events import HydroEvent, TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.base import HydroBaseModel

SIMCMD_TASK_INIT_REQUEST = "task_init_request"
SIMCMD_TASK_INIT_RESPONSE = "task_init_response"
SIMCMD_TASK_TERMINATE_REQUEST = "task_terminate_request"
SIMCMD_TASK_TERMINATE_RESPONSE = "task_terminate_response"
SIMCMD_TICK_CMD_REQUEST = "tick_cmd_request"
SIMCMD_TICK_CMD_RESPONSE = "tick_cmd_response"
SIMCMD_TIME_SERIES_CALCULATION_REQUEST = "calculation_request"
SIMCMD_TIME_SERIES_CALCULATION_RESPONSE = "calculation_response"
SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST = "time_series_data_update_request"
SIMCMD_OUTFLOW_TIME_SERIES_REQUEST = "outflow_time_series_request"


class HydroCmd(HydroBaseModel):
    command_id: str


class SimCommand(HydroCmd):
    command_type: str
    context_ref: TaskContextRef
    broadcast: bool = False


class SimCoordinationRequest(SimCommand):
    pass


class SimCoordinationResponse(SimCommand):
    command_status: Optional[CommandStatus] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    source_agent_instance_ref: AgentInstanceRef


class SimTaskInitRequest(SimCoordinationRequest):
    command_type: Literal["task_init_request"] = SIMCMD_TASK_INIT_REQUEST
    agent_definition_refs: List[AgentDefinitionRef]
    biz_scene_configuration_url: Optional[str] = None


class SimTaskInitResponse(SimCoordinationResponse):
    command_type: Literal["task_init_response"] = SIMCMD_TASK_INIT_RESPONSE
    created_agent_instances: List[AgentInstanceRef]
    managed_top_objects: Dict[str, List[TopHydroObject]]


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


class TimeSeriesCalculationRequest(SimCoordinationRequest):
    command_type: Literal["calculation_request"] = SIMCMD_TIME_SERIES_CALCULATION_REQUEST
    target_agent_instance_ref: AgentInstanceRef
    hydro_event: HydroEvent


class TimeSeriesCalculationResponse(SimCoordinationResponse):
    command_type: Literal["calculation_response"] = SIMCMD_TIME_SERIES_CALCULATION_RESPONSE
    hydro_event: HydroEvent
    object_time_series_list: List[ObjectTimeSeries]


class TimeSeriesDataUpdateRequest(SimCoordinationRequest):
    command_type: Literal["time_series_data_update_request"] = SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST
    time_series_data_changed_event: TimeSeriesDataChangedEvent


class OutflowTimeSeriesRequest(SimCoordinationRequest):
    command_type: Literal["outflow_time_series_request"] = SIMCMD_OUTFLOW_TIME_SERIES_REQUEST
    target_agent_instance_ref: AgentInstanceRef
    hydro_event: HydroEvent


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
    OutflowTimeSeriesRequest,
]


def _full_command_union():
    """Lazy union including reports, to avoid circular imports."""
    from hydros_agent_sdk.contract.v1.reports import (
        AgentInstanceStatusReport,
        HydroAlertUpdatedReport,
        ParameterIdentifiedReport,
    )
    return Union[
        SimTaskInitRequest,
        SimTaskInitResponse,
        SimTaskTerminateRequest,
        SimTaskTerminateResponse,
        TickCmdRequest,
        TickCmdResponse,
        TimeSeriesCalculationRequest,
        TimeSeriesCalculationResponse,
        TimeSeriesDataUpdateRequest,
        OutflowTimeSeriesRequest,
        AgentInstanceStatusReport,
        ParameterIdentifiedReport,
        HydroAlertUpdatedReport,
    ]


FullCommandUnion = _full_command_union()


class SimCommandEnvelope(HydroBaseModel):
    command: FullCommandUnion = Field(discriminator="command_type")
