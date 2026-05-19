"""
Agent runtime context.

AgentContext is a small facade over runtime services that agents commonly need.
It lets new code depend on a stable context object while existing agents can
continue to use sim_coordination_client, state_manager, and properties directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydros_agent_sdk.base_agent import BaseHydroAgent
    from hydros_agent_sdk.coordination_client import SimCoordinationClient
    from hydros_agent_sdk.state_manager import AgentStateManager


class AgentContext:
    """
    Lightweight runtime facade exposed to agent implementations.

    This is intentionally narrow in Phase 2. More runtime services can be added
    here later without forcing agent code to depend on concrete MQTT/client
    internals.
    """

    def __init__(
        self,
        client: "SimCoordinationClient",
        state_manager: "AgentStateManager",
        agent: "BaseHydroAgent",
    ):
        self.client = client
        self.state_manager = state_manager
        self.agent = agent

    @property
    def logger(self) -> logging.Logger:
        """Logger scoped to the current agent code."""
        return logging.getLogger(self.agent.agent_code)

    @property
    def config(self) -> Any:
        """Agent configuration properties."""
        return self.agent.properties

    @property
    def context(self):
        """Simulation context for this agent instance."""
        return self.agent.context

    def send_response(self, response) -> None:
        """Send a response through the coordination client queue."""
        self.client.enqueue(response)
