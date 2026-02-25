"""
Multi-agent coordination support.

This module provides MultiAgentCallback for handling multiple agent types
in a single process.
"""

import logging
from typing import Dict, Optional, Any

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.models import CommandStatus

logger = logging.getLogger(__name__)


class MultiAgentCallback(SimCoordinationCallback):
    """
    Multi-agent callback that manages multiple agent types in a single process.

    This callback handles SimTaskInitRequest correctly by:
    1. Checking agent_list to determine which agents to instantiate
    2. Creating all matching agent instances
    3. Returning a single SimTaskInitResponse with all created instances

    This is the correct implementation for multi-agent coordination where
    one SimTaskInitRequest can trigger multiple agent instantiations but
    should only return one SimTaskInitResponse.

    Example:
        callback = MultiAgentCallback(node_id="LOCAL")
        callback.register_agent_factory("TWINS_SIMULATION_AGENT", twins_factory)
        callback.register_agent_factory("ONTOLOGY_SIMULATION_AGENT", ontology_factory)
    """

    def __init__(self, node_id: str = "LOCAL"):
        """
        Initialize multi-agent callback.

        Args:
            node_id: Node identifier for this agent host
        """
        self.node_id = node_id
        self.agent_factories: Dict[str, Any] = {}  # {agent_code: factory}
        self.agents: Dict[str, Dict[str, Any]] = {}  # {context_id: {agent_code: agent}}
        self._client: Optional[Any] = None

        logger.info(f"MultiAgentCallback created for node: {node_id}")

    def register_agent_factory(self, agent_code: str, factory: Any):
        """
        Register an agent factory for a specific agent_code.

        Args:
            agent_code: Agent code (e.g., "TWINS_SIMULATION_AGENT")
            factory: Agent factory instance (HydroAgentFactory)
        """
        self.agent_factories[agent_code] = factory
        logger.info(f"Registered agent factory: {agent_code}")

    def set_client(self, client: Any):
        """Set coordination client reference."""
        self._client = client
        logger.info("Coordination client reference set")

    def get_component(self) -> str:
        """
        Get component name.

        For multi-agent callback, we return a generic name since we handle
        multiple agent types. The actual agent_code filtering is done in
        on_sim_task_init based on agent_list.
        """
        return "MULTI_AGENT_COORDINATOR"

    def is_remote_agent(self, agent_instance: Any) -> bool:
        """Check if agent is remote."""
        if self._client:
            return self._client.state_manager.is_remote_agent(agent_instance)
        return False

    def on_sim_task_init(self, request: SimTaskInitRequest):
        """
        Handle task initialization for multiple agents.

        This method:
        1. Iterates through request.agent_list
        2. For each agent_code that has a registered factory, creates an instance
        3. Collects all created agent instances
        4. Returns a single SimTaskInitResponse with all instances
        """
        context_id = request.context.biz_scene_instance_id

        if self._client is None:
            raise RuntimeError("Coordination client not set")

        print(request.biz_scene_configuration_url)
        logger.info(f"Processing SimTaskInitRequest for task: {context_id}")
        logger.info(f"  Requested agents: {[a.agent_code for a in request.agent_list]}")

        # Track agents created in this task
        created_agents = []
        context_agents = {}

        # Process each agent in agent_list
        for agent_def in request.agent_list:
            agent_code = agent_def.agent_code

            # Check if we have a factory for this agent_code
            factory = self.agent_factories.get(agent_code)

            if factory is None:
                logger.debug(f"  No factory registered for {agent_code}, skipping")
                continue

            logger.info(f"  Creating agent: {agent_code}")

            try:
                # Create agent instance
                agent = factory.create_agent(
                    sim_coordination_client=self._client,
                    context=request.context
                )

                # Initialize agent
                response = agent.on_init(request)

                # Collect created agent instance
                if response and hasattr(response, 'source_agent_instance'):
                    created_agents.append(response.source_agent_instance)

                # Store agent
                context_agents[agent_code] = agent

                logger.info(f"  ✓ Agent created and initialized: {agent_code}")

            except Exception as e:
                logger.error(f"  ✗ Failed to create agent {agent_code}: {e}", exc_info=True)
                # Continue with other agents

        # Store agents for this context
        if context_agents:
            self.agents[context_id] = context_agents

        # Return single response with all created instances
        if created_agents:
            # Use the first created agent as source_agent_instance
            # (protocol limitation - should ideally support multiple sources)
            first_agent = created_agents[0]

            # Generate a unique command_id for the response
            import uuid
            command_id = f"RESP_{context_id}_{uuid.uuid4().hex[:8]}"

            response = SimTaskInitResponse(
                command_id=command_id,
                context=request.context,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=first_agent,
                created_agent_instances=created_agents,
                managed_top_objects={}
            )

            # Send response
            self._client.enqueue(response)

            logger.info(f"SimTaskInitResponse sent with {len(created_agents)} agent(s)")
        else:
            logger.warning(f"No agents created for task {context_id}")

    def on_tick(self, request: TickCmdRequest):
        """Handle tick command for all agents in the context."""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return

        # Forward tick to all agents in this context
        for agent_code, agent in context_agents.items():
            try:
                response = agent.on_tick(request)
                if response:
                    agent.send_response(response)
            except Exception as e:
                logger.error(f"Error in tick for {agent_code}: {e}", exc_info=True)

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """Handle task termination for all agents in the context."""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return

        # Terminate all agents in this context
        for agent_code, agent in context_agents.items():
            try:
                response = agent.on_terminate(request)
                if response:
                    agent.send_response(response)
                logger.info(f"Agent terminated: {agent_code}")
            except Exception as e:
                logger.error(f"Error terminating {agent_code}: {e}", exc_info=True)

        # Remove agents from tracking
        del self.agents[context_id]
        logger.info(f"All agents terminated for context: {context_id}")

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        """Handle time series data update for all agents in the context."""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return

        # Forward update to all agents in this context
        for agent_code, agent in context_agents.items():
            try:
                response = agent.on_time_series_data_update(request)
                if response:
                    agent.send_response(response)
            except Exception as e:
                logger.error(f"Error in time series update for {agent_code}: {e}", exc_info=True)
