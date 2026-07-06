"""Minimal TickableAgent template for Hydros Agent SDK developers."""

import logging

from hydros_agent_sdk.agents import TickableAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
)
from hydros_agent_sdk.protocol.models import CommandStatus

logger = logging.getLogger(__name__)


class TemplateAgent(TickableAgent):
    """Smallest useful time-step driven Agent example."""

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initializing template agent: %s", self.agent_id)
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)
        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False,
        )

    def on_tick_simulation(self, request: TickCmdRequest):
        logger.info("Template tick: step=%s, command_id=%s", request.step, request.command_id)
        return []

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("Terminating template agent: %s", self.agent_id)
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )
