"""Coordination command routing to callback methods."""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import (
    AgentInstanceStatusReport,
    HydroEventAckResponse,
    HydroEventCommand,
    MpcPredictionResultReport,
    MpcExecutionStatusReport,
    EdgeControlExecutionReport,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
    OutflowTimeSeriesRequest,
    SimCommand,
    SimCoordinationResponse,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    TickCmdRequest,
    TimeSeriesCalculationRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    SIMCMD_AGENT_INSTANCE_STATUS_REPORT,
    SIMCMD_HYDRO_EVENT_COMMAND,
    SIMCMD_MPC_PREDICTION_RESULT_REPORT,
    SIMCMD_MPC_EXECUTION_STATUS_REPORT,
    SIMCMD_EDGE_CONTROL_EXECUTION_REPORT,
    SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST,
    SIMCMD_OUTFLOW_TIME_SERIES_REQUEST,
    SIMCMD_TASK_INIT_REQUEST,
    SIMCMD_TASK_INIT_RESPONSE,
    SIMCMD_TASK_TERMINATE_REQUEST,
    SIMCMD_TICK_CMD_REQUEST,
    SIMCMD_TIME_SERIES_CALCULATION_REQUEST,
    SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST,
)
from hydros_agent_sdk.protocol.events import (
    OutflowTimeSeriesDataChangedEvent,
    OutflowTimeSeriesEvent,
    TimeSeriesDataChangedEvent,
)


logger = logging.getLogger(__name__)


class CoordinationCommandRouter:
    """Routes parsed coordination commands to the configured callback."""

    def __init__(
        self,
        callback: SimCoordinationCallback,
        context_id_getter: Optional[Callable[[SimCommand], Optional[str]]] = None,
        event_type_getter: Optional[Callable[[SimCommand], Optional[str]]] = None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.callback = callback
        self.context_id_getter = context_id_getter or (lambda _command: None)
        self.event_type_getter = event_type_getter or (lambda _command: None)
        self.logger = log or logger
        self.handlers: Dict[str, Callable[[SimCommand], object]] = self._build_handlers()

    def _build_handlers(self) -> Dict[str, Callable[[SimCommand], object]]:
        return {
            SIMCMD_TASK_INIT_REQUEST: self.handle_task_init,
            SIMCMD_TASK_INIT_RESPONSE: self.handle_task_init_response,
            SIMCMD_TICK_CMD_REQUEST: self.handle_tick,
            SIMCMD_TASK_TERMINATE_REQUEST: self.handle_task_terminate,
            SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST: self.handle_time_series_data_update,
            SIMCMD_HYDRO_EVENT_COMMAND: self.handle_hydro_event_command,
            SIMCMD_TIME_SERIES_CALCULATION_REQUEST: self.handle_time_series_calculation,
            SIMCMD_AGENT_INSTANCE_STATUS_REPORT: self.handle_agent_status_report,
            SIMCMD_MPC_PREDICTION_RESULT_REPORT: self.handle_mpc_prediction_result_report,
            SIMCMD_MPC_EXECUTION_STATUS_REPORT: self.handle_mpc_execution_status_report,
            SIMCMD_EDGE_CONTROL_EXECUTION_REPORT: self.handle_station_control_execution_report,
            SIMCMD_OUTFLOW_TIME_SERIES_REQUEST: self.handle_outflow_time_series_request,
            SIMCMD_OUTFLOW_TIME_SERIES_DATA_UPDATE_REQUEST: self.handle_outflow_time_series_data_update,
        }

    def dispatch(self, command: SimCommand):
        handler = self.handlers.get(command.command_type)
        if handler is None:
            self.logger.warning("No handler registered for command type: %s", command.command_type)
            return None

        self.logger.debug(
            "MQTT command accepted: type=%s, id=%s, context=%s, eventType=%s, handler=%s",
            command.command_type,
            command.command_id,
            self.context_id_getter(command),
            self.event_type_getter(command),
            getattr(handler, "__name__", str(handler)),
        )
        result = handler(command)
        pending_reports = self._consume_callback_pending_reports(
            self.context_id_getter(command)
        )
        if not pending_reports:
            return result
        if result is None:
            return pending_reports
        if isinstance(result, list):
            return [*result, *pending_reports]
        if isinstance(result, tuple):
            return [*result, *pending_reports]
        return [result, *pending_reports]

    def _consume_callback_pending_reports(self, context_id: Optional[str]):
        consumer = getattr(self.callback, "consume_pending_status_reports", None)
        if not callable(consumer) or not context_id:
            return []
        reports = consumer(context_id)
        return list(reports or [])

    def handle_task_init(self, command: SimCommand):
        request = command
        assert isinstance(request, SimTaskInitRequest)
        return self.callback.on_sim_task_init(request)

    def handle_task_init_response(self, command: SimCommand):
        response = command
        assert isinstance(response, SimTaskInitResponse)
        if self.callback.is_remote_agent(response.source_agent_instance):
            return self.callback.on_agent_instance_sibling_created(response)
        return None

    def handle_tick(self, command: SimCommand):
        request = command
        assert isinstance(request, TickCmdRequest)
        return self.callback.on_tick(request)

    def handle_task_terminate(self, command: SimCommand):
        request = command
        assert isinstance(request, SimTaskTerminateRequest)
        return self.callback.on_task_terminate(request)

    def handle_time_series_data_update(self, command: SimCommand):
        request = command
        assert isinstance(request, TimeSeriesDataUpdateRequest)
        return self.callback.on_time_series_data_update(request)

    def handle_hydro_event_command(self, command: SimCommand):
        request = command
        assert isinstance(request, HydroEventCommand)
        payload = request.payload

        if isinstance(payload, TimeSeriesDataChangedEvent):
            update_request = TimeSeriesDataUpdateRequest(
                command_id=request.command_id,
                context=request.context,
                broadcast=request.broadcast,
                time_series_data_changed_event=payload,
            )
            result = self.callback.on_time_series_data_update(update_request)
            return self.to_hydro_event_ack_response(request, result)

        if isinstance(payload, OutflowTimeSeriesDataChangedEvent):
            update_request = OutflowTimeSeriesDataUpdateRequest(
                command_id=request.command_id,
                context=request.context,
                broadcast=request.broadcast,
                outflow_time_series_data_changed_event=payload,
            )
            result = self.callback.on_outflow_time_series_data_update(update_request)
            return self.to_hydro_event_ack_response(request, result)

        if isinstance(payload, OutflowTimeSeriesEvent):
            if request.target_agent_instance is None:
                self.logger.warning(
                    "Ignoring outflow hydro_event_command without target_agent_instance: id=%s",
                    request.command_id,
                )
                return None
            outflow_request = OutflowTimeSeriesRequest(
                command_id=request.command_id,
                context=request.context,
                broadcast=request.broadcast,
                target_agent_instance=request.target_agent_instance,
                hydro_event=payload,
            )
            return self.callback.on_outflow_time_series(outflow_request)

        self.logger.warning(
            "Ignoring unsupported hydro_event_command payload: id=%s, eventType=%s",
            request.command_id,
            getattr(payload, "hydro_event_type", None),
        )
        return None

    def to_hydro_event_ack_response(self, request: HydroEventCommand, result):
        if result is None:
            return None

        if isinstance(result, HydroEventAckResponse):
            return result

        if isinstance(result, (TimeSeriesDataUpdateResponse, OutflowTimeSeriesDataUpdateResponse)):
            return self.build_hydro_event_ack_response(request, result)

        if isinstance(result, list):
            responses = []
            for item in result:
                if isinstance(item, HydroEventAckResponse):
                    responses.append(item)
                elif isinstance(item, (TimeSeriesDataUpdateResponse, OutflowTimeSeriesDataUpdateResponse)):
                    responses.append(self.build_hydro_event_ack_response(request, item))
            return responses

        return None

    @staticmethod
    def build_hydro_event_ack_response(
        request: HydroEventCommand,
        response: SimCoordinationResponse,
    ) -> HydroEventAckResponse:
        return HydroEventAckResponse(
            context=request.context,
            command_id=request.command_id,
            command_status=response.command_status,
            source_agent_instance=response.source_agent_instance,
            broadcast=False,
            error_code=response.error_code,
            error_message=response.error_message,
        )

    def handle_outflow_time_series_data_update(self, command: SimCommand):
        request = command
        assert isinstance(request, OutflowTimeSeriesDataUpdateRequest)
        return self.callback.on_outflow_time_series_data_update(request)

    def handle_time_series_calculation(self, command: SimCommand):
        request = command
        assert isinstance(request, TimeSeriesCalculationRequest)
        return self.callback.on_time_series_calculation(request)

    def handle_agent_status_report(self, command: SimCommand):
        report = command
        assert isinstance(report, AgentInstanceStatusReport)
        if self.callback.is_remote_agent(report.source_agent_instance):
            return self.callback.on_agent_instance_sibling_status_updated(report)
        return None

    def handle_mpc_prediction_result_report(self, command: SimCommand):
        report = command
        assert isinstance(report, MpcPredictionResultReport)
        if self.callback.is_remote_agent(report.source_agent_instance):
            return self.callback.on_mpc_prediction_result(report)
        return None

    def handle_mpc_execution_status_report(self, command: SimCommand):
        report = command
        assert isinstance(report, MpcExecutionStatusReport)
        if self.callback.is_remote_agent(report.source_agent_instance):
            return self.callback.on_mpc_execution_status(report)
        return None

    def handle_station_control_execution_report(self, command: SimCommand):
        report = command
        assert isinstance(report, EdgeControlExecutionReport)
        if self.callback.is_remote_agent(report.source_agent_instance):
            return self.callback.on_station_control_execution(report)
        return None

    def handle_outflow_time_series_request(self, command: SimCommand):
        request = command
        assert isinstance(request, OutflowTimeSeriesRequest)
        return self.callback.on_outflow_time_series(request)
