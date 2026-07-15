"""Minimal composition-based Hydros Agent template for SDK developers."""

import logging

from hydros_agent_sdk import CustomAgent, AgentExecutionContext
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskTerminateRequest,
    TickCmdRequest,
)

logger = logging.getLogger(__name__)


class TemplateAgent(CustomAgent):
    """Smallest useful time-step driven Agent implementation."""

    def on_init(self, runtime: AgentExecutionContext, request: SimTaskInitRequest) -> None:
        logger.info("Initializing template agent: %s", runtime.agent.agent_id)

    def on_tick(self, runtime: AgentExecutionContext, request: TickCmdRequest) -> None:
        logger.info("Template tick: step=%s, command_id=%s", request.step, request.command_id)

    def on_terminate(self, runtime: AgentExecutionContext, request: SimTaskTerminateRequest) -> None:
        logger.info("Terminating template agent: %s", runtime.agent.agent_id)
