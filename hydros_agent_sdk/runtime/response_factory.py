"""
Factories for standard coordination responses.

The factory centralizes the repeated response construction pattern used by
agents and runtime error handling. It does not send responses; callers still
decide whether to return or enqueue them.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from hydros_agent_sdk.protocol.commands import (
    SimTaskInitResponse,
    TickCmdResponse,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateResponse,
    TimeSeriesCalculationResponse,
)
from hydros_agent_sdk.protocol.models import (
    CommandStatus,
    HydroAgentInstance,
    ObjectTimeSeries,
    TopHydroObject,
)


class ResponseFactory:
    """Create standard success and failure response DTOs."""

    @staticmethod
    def init_succeed(
        agent: HydroAgentInstance,
        request,
        created_agent_instances: Optional[List[HydroAgentInstance]] = None,
        managed_top_objects: Optional[Dict[str, List[TopHydroObject]]] = None,
    ) -> SimTaskInitResponse:
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=agent,
            created_agent_instances=created_agent_instances if created_agent_instances is not None else [agent],
            managed_top_objects=managed_top_objects if managed_top_objects is not None else {},
            broadcast=False,
        )

    @staticmethod
    def init_failed(
        agent: HydroAgentInstance,
        request,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> SimTaskInitResponse:
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            source_agent_instance=agent,
            created_agent_instances=[],
            managed_top_objects={},
            broadcast=False,
        )

    @staticmethod
    def tick_succeed(agent: HydroAgentInstance, request) -> TickCmdResponse:
        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=agent,
            broadcast=False,
        )

    @staticmethod
    def tick_failed(
        agent: HydroAgentInstance,
        request,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TickCmdResponse:
        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            source_agent_instance=agent,
            broadcast=False,
        )

    @staticmethod
    def terminate_succeed(agent: HydroAgentInstance, request) -> SimTaskTerminateResponse:
        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=agent,
            broadcast=False,
        )

    @staticmethod
    def terminate_failed(
        agent: HydroAgentInstance,
        request,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> SimTaskTerminateResponse:
        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            source_agent_instance=agent,
            broadcast=False,
        )

    @staticmethod
    def time_series_data_update_succeed(agent: HydroAgentInstance, request) -> TimeSeriesDataUpdateResponse:
        return TimeSeriesDataUpdateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=agent,
            broadcast=False,
        )

    @staticmethod
    def time_series_data_update_failed(
        agent: HydroAgentInstance,
        request,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TimeSeriesDataUpdateResponse:
        return TimeSeriesDataUpdateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            source_agent_instance=agent,
            broadcast=False,
        )

    @staticmethod
    def time_series_calculation_failed(
        agent: HydroAgentInstance,
        request,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        object_time_series_list: Optional[List[ObjectTimeSeries]] = None,
    ) -> TimeSeriesCalculationResponse:
        return TimeSeriesCalculationResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            source_agent_instance=agent,
            hydro_event=request.hydro_event,
            object_time_series_list=object_time_series_list if object_time_series_list is not None else [],
            broadcast=False,
        )
