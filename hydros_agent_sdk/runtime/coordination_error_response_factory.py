"""Factory for coordination failure responses."""

from __future__ import annotations

import logging
import traceback
from typing import Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.error_codes import ErrorCodes
from hydros_agent_sdk.protocol.commands import (
    HydroEventAckResponse,
    HydroEventCommand,
    SimCommand,
    SimCoordinationResponse,
    SimTaskInitRequest,
    SimTaskTerminateRequest,
    TickCmdRequest,
    TimeSeriesCalculationRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.models import CommandStatus, HydroAgentInstance
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.state_manager import AgentStateManager


logger = logging.getLogger(__name__)


class CoordinationErrorResponseFactory:
    """Creates protocol-compatible failure responses for handler exceptions."""

    def __init__(
        self,
        state_manager: AgentStateManager,
        callback: SimCoordinationCallback,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.state_manager = state_manager
        self.callback = callback
        self.logger = log or logger

    def create(self, command: SimCommand, error: Exception) -> Optional[SimCoordinationResponse]:
        source_agent = self.resolve_source_agent(command)
        if source_agent is None:
            self.logger.error(
                "Cannot create error response for command %s (%s): no source agent available",
                command.command_id,
                command.command_type,
            )
            return None

        error_code = ErrorCodes.SYSTEM_ERROR

        if isinstance(command, SimTaskInitRequest):
            error_code = ErrorCodes.AGENT_INIT_FAILURE
            factory_method = ResponseFactory.init_failed
        elif isinstance(command, TickCmdRequest):
            error_code = ErrorCodes.AGENT_TICK_FAILURE
            factory_method = ResponseFactory.tick_failed
        elif isinstance(command, SimTaskTerminateRequest):
            error_code = ErrorCodes.AGENT_TERMINATE_FAILURE
            factory_method = ResponseFactory.terminate_failed
        elif isinstance(command, TimeSeriesDataUpdateRequest):
            error_code = ErrorCodes.TIME_SERIES_UPDATE_FAILURE
            factory_method = ResponseFactory.time_series_data_update_failed
        elif isinstance(command, HydroEventCommand):
            return HydroEventAckResponse(
                context=command.context,
                command_id=command.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=source_agent,
                broadcast=False,
                error_code=ErrorCodes.SYSTEM_ERROR.code,
                error_message=f"{error}\n{traceback.format_exc()}",
            )
        elif isinstance(command, TimeSeriesCalculationRequest):
            error_code = ErrorCodes.TIME_SERIES_CALCULATION_FAILURE
            factory_method = ResponseFactory.time_series_calculation_failed
        else:
            factory_method = None

        if factory_method is None:
            self.logger.debug("No error response mapping for command type: %s", command.command_type)
            return None

        agent_name = getattr(source_agent, "agent_code", self.callback.get_component())
        error_detail = f"{error}\n{traceback.format_exc()}"
        error_message = error_code.format_message(agent_name, error_detail)

        return factory_method(
            source_agent,
            command,
            error_code=error_code.code,
            error_message=error_message,
        )

    def resolve_source_agent(self, command: SimCommand) -> Optional[HydroAgentInstance]:
        target_agent = getattr(command, "target_agent_instance", None)
        if target_agent is not None:
            return target_agent

        context = getattr(command, "context", None)
        context_id = getattr(context, "biz_scene_instance_id", None)
        if context_id:
            agents = self.state_manager.get_agents_for_context(context_id)
            if agents:
                return agents[0]

            callback_agents = getattr(self.callback, "agents", None)
            if isinstance(callback_agents, dict):
                context_agents = callback_agents.get(context_id)
                if isinstance(context_agents, dict) and context_agents:
                    return next(iter(context_agents.values()))

        return None
