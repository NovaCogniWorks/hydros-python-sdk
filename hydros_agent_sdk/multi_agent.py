"""
Multi-agent coordination support.

This module provides MultiAgentCallback for handling multiple agent types
in a single process.
"""

import logging
from typing import Dict, Optional, Any

from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesRequest,
)
from hydros_agent_sdk.protocol.models import AgentInstanceStatus, CommandStatus, HydroAgent
from hydros_agent_sdk.runtime.agent_instance_status_support import AgentInstanceStatusSupport
from hydros_agent_sdk.agent_constants import (
    CENTRAL_SCHEDULING_AGENT_TYPE,
    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
)

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
        self.agent_factory_types: Dict[str, str] = {}  # {agent_code: agent_type}
        self.agents: Dict[str, Dict[str, Any]] = {}  # {context_id: {agent_code: agent}}
        self._client: Optional[Any] = None
        self._status_support: Optional[AgentInstanceStatusSupport] = None

        logger.info(f"MultiAgentCallback created for node: {node_id}")

    def register_agent_factory(self, agent_code: str, factory: Any, agent_type: Optional[str] = None):
        """
        Register an agent factory for a specific agent_code.

        Args:
            agent_code: Agent code (e.g., "TWINS_SIMULATION_AGENT")
            factory: Agent factory instance (HydroAgentFactory)
            agent_type: Optional agent type. When omitted, it is inferred from
                the factory config where possible.
        """
        self.agent_factories[agent_code] = factory
        self.agent_factory_types[agent_code] = agent_type or self._infer_factory_agent_type(agent_code, factory)
        logger.info(f"Registered agent factory: {agent_code}")

    def register_system_default_central_scheduling_agent(self, env_config: Optional[Dict[str, str]] = None):
        """注册系统默认中央调度智能体，已注册时不覆盖。"""
        if SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE in self.agent_factories:
            return

        from hydros_agent_sdk.factory import SystemCentralSchedulingAgentFactory

        self.register_agent_factory(
            SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
            SystemCentralSchedulingAgentFactory(env_config=env_config),
            agent_type=CENTRAL_SCHEDULING_AGENT_TYPE,
        )

    def _infer_factory_agent_type(self, agent_code: str, factory: Any) -> str:
        """尽量从 factory 配置里拿 agent_type，拿不到就退回 agent_code。"""
        for attr_name in ("agent_type", "_agent_type"):
            agent_type = getattr(factory, attr_name, None)
            if agent_type:
                return str(agent_type)

        config_file = getattr(factory, "config_file", None)
        load_config = getattr(factory, "_load_config", None)
        if config_file and callable(load_config):
            try:
                config = load_config(config_file)
                agent_type = config.get("agent_type")
                if agent_type:
                    return str(agent_type)
            except Exception:
                logger.debug("Could not infer agent_type for factory %s", agent_code, exc_info=True)

        return agent_code

    def _is_central_scheduling_agent_def(self, agent_def: Any) -> bool:
        agent_code = getattr(agent_def, "agent_code", None)
        agent_type = getattr(agent_def, "agent_type", None)
        return (
            agent_type == CENTRAL_SCHEDULING_AGENT_TYPE
            or agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
        )

    def _is_central_scheduling_factory(self, agent_code: str, agent_type: Optional[str]) -> bool:
        return (
            agent_type == CENTRAL_SCHEDULING_AGENT_TYPE
            or agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
            or agent_code.startswith(f"{SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE}_")
        )

    def _has_custom_central_scheduling_factory(self) -> bool:
        for agent_code, agent_type in self.agent_factory_types.items():
            if agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE:
                continue
            if self._is_central_scheduling_factory(agent_code, agent_type):
                return True
        return False

    def _resolve_agent_factory(self, agent_def: Any):
        """解析 task init 中某个 agent 应该使用的 factory。"""
        agent_code = agent_def.agent_code

        factory = self.agent_factories.get(agent_code)
        if factory is not None:
            return agent_code, factory

        if not self._is_central_scheduling_agent_def(agent_def):
            return agent_code, None

        system_factory = self.agent_factories.get(SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE)
        if system_factory is None:
            return agent_code, None

        if self._has_custom_central_scheduling_factory():
            logger.debug(
                "Central scheduling custom route requires exact agent_code: requested=%s",
                agent_code,
            )
            return agent_code, None

        return SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE, system_factory

    def set_client(self, client: Any):
        """Set coordination client reference."""
        self._client = client
        self._status_support = AgentInstanceStatusSupport(sim_coordination_client=client)
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

    def _execute_with_status(
        self,
        agent,
        action,
        phase: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if self._status_support is None:
            return action()

        return self._status_support.execute_with_status(
            agent,
            action,
            phase=phase,
            metadata=metadata,
        )

    def _transition_status(
        self,
        agent,
        status: AgentInstanceStatus,
        phase: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if self._status_support is None:
            return None

        try:
            return self._status_support.transition_status(
                agent,
                status,
                phase=phase,
                metadata=metadata,
            )
        except Exception:
            logger.warning(
                "Failed to transition agent instance status: agentCode=%s, status=%s, phase=%s",
                getattr(agent, "agent_code", None),
                status,
                phase,
                exc_info=True,
            )
            return None

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

        logger.debug("Task configuration URL: %s", request.biz_scene_configuration_url)
        logger.info(f"Processing SimTaskInitRequest for task: {context_id}")
        logger.info(f"  Requested agents: {[a.agent_code for a in request.agent_list]}")

        try:
            ContextManager.create_from_init_request(request)
        except Exception:
            logger.warning(
                "Failed to initialize hydro model context from scenario config: %s",
                request.biz_scene_configuration_url,
                exc_info=True,
            )

        # Track agents created in this task
        created_agents = []
        context_agents = {}
        routed_agent_codes = set()

        # Process each agent in agent_list
        for agent_def in request.agent_list:
            agent_code = agent_def.agent_code

            # Check if we have a factory for this agent_code or the system default central agent.
            routed_agent_code, factory = self._resolve_agent_factory(agent_def)

            if factory is None:
                logger.debug(f"  No factory registered for {agent_code}, skipping")
                continue

            if routed_agent_code in routed_agent_codes:
                logger.debug(f"  Agent route already handled for {routed_agent_code}, skipping duplicate")
                continue
            routed_agent_codes.add(routed_agent_code)

            logger.info(f"  Creating agent: {routed_agent_code} (requested: {agent_code})")

            try:
                # Create agent instance
                agent = factory.create_agent(
                    sim_coordination_client=self._client,
                    context=request.context
                )
                should_sync_identity = routed_agent_code == agent_code
                if should_sync_identity:
                    self._sync_agent_definition_from_request(agent, agent_def)

                # Initialize agent
                response = agent.on_init(request)
                created_agent_code = getattr(agent, "agent_code", routed_agent_code)

                # Collect created agent instance
                if response and hasattr(response, 'source_agent_instance'):
                    if should_sync_identity:
                        self._sync_init_response_agent_definition(response, agent_def)
                    created_agents.append(response.source_agent_instance)
                    self._transition_status(
                        response.source_agent_instance,
                        AgentInstanceStatus.WAITING,
                        phase="TASK_INITIALIZED",
                        metadata={
                            "command_id": request.command_id,
                            "agent_code": created_agent_code,
                            "requested_agent_code": agent_code,
                            "biz_scene_instance_id": context_id,
                        },
                    )

                # Store agent
                context_agents[created_agent_code] = agent

                logger.info(f"  ✓ Agent created and initialized: {created_agent_code}")

            except Exception as e:
                logger.error(f"  ✗ Failed to create agent {routed_agent_code}: {e}", exc_info=True)
                # Continue with other agents

        # Store agents for this context
        if context_agents:
            self.agents[context_id] = context_agents

        # Return single response with all created instances
        if created_agents:
            # Use the first created agent as source_agent_instance
            # (protocol limitation - should ideally support multiple sources)
            first_agent = created_agents[0]

            response = SimTaskInitResponse(
                command_id=request.command_id,
                context=request.context,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=first_agent,
                created_agent_instances=created_agents,
                managed_top_objects={}
            )

            logger.info(f"SimTaskInitResponse created with {len(created_agents)} agent(s)")
            return response
        else:
            logger.warning(f"No agents created for task {context_id}")
            return None

    @staticmethod
    def _sync_agent_definition_from_request(agent: Any, agent_def: HydroAgent) -> None:
        """Keep runtime routing/config aligned without overriding local display name."""
        if getattr(agent_def, "agent_type", None):
            object.__setattr__(agent, "agent_type", agent_def.agent_type)
        if getattr(agent_def, "agent_configuration_url", None):
            object.__setattr__(
                agent,
                "agent_configuration_url",
                agent_def.agent_configuration_url,
            )

    @classmethod
    def _sync_init_response_agent_definition(
        cls,
        response: SimTaskInitResponse,
        agent_def: HydroAgent,
    ) -> None:
        """Keep returned agent instances aligned with the coordinator request."""
        cls._sync_agent_definition_from_request(response.source_agent_instance, agent_def)
        for agent_instance in response.created_agent_instances or []:
            if agent_instance.agent_code == agent_def.agent_code:
                cls._sync_agent_definition_from_request(agent_instance, agent_def)

    def on_tick(self, request: TickCmdRequest):
        """Handle tick command for all agents in the context."""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # Forward tick to all agents in this context
        responses = []
        for agent_code, agent in context_agents.items():
            if not self._supports_tick_command(agent):
                logger.debug("Skipping tick for agent without tick capability: %s", agent_code)
                continue
            try:
                response = self._execute_with_status(
                    agent,
                    lambda agent=agent: agent.on_tick(request),
                    phase="TICK",
                    metadata={
                        "command_id": request.command_id,
                        "step": request.step,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                    },
                )
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Error in tick for {agent_code}: {e}", exc_info=True)
        return responses

    @staticmethod
    def _supports_tick_command(agent: Any) -> bool:
        supports_tick_command = getattr(agent, "supports_tick_command", None)
        if supports_tick_command is None:
            return True
        return bool(supports_tick_command())

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """Handle task termination for all agents in the context."""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # Terminate all agents in this context
        responses = []
        for agent_code, agent in context_agents.items():
            try:
                self._transition_status(
                    agent,
                    AgentInstanceStatus.RUNNING,
                    phase="TASK_TERMINATE_STARTED",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "reason": request.reason,
                    },
                )
                response = agent.on_terminate(request)
                if response:
                    responses.append(response)
                terminal_status = (
                    AgentInstanceStatus.CANCELED
                    if request.reason and "cancel" in request.reason.lower()
                    else AgentInstanceStatus.COMPLETED
                )
                self._transition_status(
                    agent,
                    terminal_status,
                    phase="TASK_TERMINATED",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "reason": request.reason,
                    },
                )
                logger.info(f"Agent terminated: {agent_code}")
            except Exception as e:
                self._transition_status(
                    agent,
                    AgentInstanceStatus.FAILED,
                    phase="TASK_TERMINATE_FAILED",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "reason": request.reason,
                        "error_message": str(e),
                    },
                )
                logger.error(f"Error terminating {agent_code}: {e}", exc_info=True)

        # Remove agents from tracking
        del self.agents[context_id]
        super().on_task_terminate(request)
        logger.info(f"All agents terminated for context: {context_id}")
        return responses

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        """Handle time series data update for all agents in the context."""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # Forward update to all agents in this context
        responses = []
        for agent_code, agent in context_agents.items():
            try:
                event = request.time_series_data_changed_event
                response = self._execute_with_status(
                    agent,
                    lambda agent=agent: agent.on_time_series_data_update(request),
                    phase="TIME_SERIES_DATA_UPDATE",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "auto_schedule_at_step": getattr(event, "auto_schedule_at_step", None),
                        "hydro_event_type": getattr(event, "hydro_event_type", None),
                        "hydro_event_source_type": getattr(event, "hydro_event_source_type", None),
                    },
                )
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Error in time series update for {agent_code}: {e}", exc_info=True)
        return responses

    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest):
        """Handle outflow time series data update for all agents in the context."""
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # Forward update to all agents in this context
        responses = []
        for agent_code, agent in context_agents.items():
            try:
                event = request.outflow_time_series_data_changed_event
                response = self._execute_with_status(
                    agent,
                    lambda agent=agent: agent.on_outflow_time_series_data_update(request),
                    phase="OUTFLOW_TIME_SERIES_DATA_UPDATE",
                    metadata={
                        "command_id": request.command_id,
                        "agent_code": agent_code,
                        "biz_scene_instance_id": context_id,
                        "auto_schedule_at_step": getattr(event, "auto_schedule_at_step", None),
                        "hydro_event_type": getattr(event, "hydro_event_type", None),
                        "hydro_event_source_type": getattr(event, "hydro_event_source_type", None),
                    },
                )
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Error in outflow time series update for {agent_code}: {e}", exc_info=True)
        return responses

    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        Handle outflow time series request for the target agent.

        Unlike on_tick or on_time_series_data_update which broadcast to all agents,
        this method routes the request only to the target agent specified in the request.
        """
        context_id = request.context.biz_scene_instance_id
        context_agents = self.agents.get(context_id)

        if not context_agents:
            logger.error(f"No agents found for context: {context_id}")
            return None

        # Extract target agent code from request
        target_agent_code = request.target_agent_instance.agent_code

        # Find the target agent
        target_agent = context_agents.get(target_agent_code)

        if not target_agent:
            logger.warning(
                f"Target agent '{target_agent_code}' not found in context {context_id}. "
                f"Available agents: {list(context_agents.keys())}"
            )
            return None

        # Forward request to the target agent only
        try:
            logger.debug(f"Routing outflow time series request to agent: {target_agent_code}")
            response = self._execute_with_status(
                target_agent,
                lambda: target_agent.on_outflow_time_series(request),
                phase="OUTFLOW_TIME_SERIES",
                metadata={
                    "command_id": request.command_id,
                    "agent_code": target_agent_code,
                    "biz_scene_instance_id": context_id,
                    "target_agent_id": request.target_agent_instance.agent_id,
                    "target_agent_code": request.target_agent_instance.agent_code,
                },
            )
            return response
        except Exception as e:
            logger.error(
                f"Error in outflow time series for {target_agent_code}: {e}",
                exc_info=True
            )
            return None
