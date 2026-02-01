"""
Base agent implementation for Hydros agents.

This module provides the BaseHydroAgent class which inherits from HydroAgentInstance
and adds behavioral methods for handling simulation lifecycle.
"""

import logging
from typing import Optional, TYPE_CHECKING
from abc import ABC, abstractmethod
from pydantic import ConfigDict, Field

from hydros_agent_sdk.protocol.models import HydroAgentInstance, SimulationContext, AgentBizStatus, AgentDriveMode
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    TimeSeriesCalculationRequest,
)
from hydros_agent_sdk.protocol.models import CommandStatus
from hydros_agent_sdk.agent_properties import AgentProperties

# Import for type checking only to avoid runtime circular imports
if TYPE_CHECKING:
    from hydros_agent_sdk.coordination_client import SimCoordinationClient
    from hydros_agent_sdk.state_manager import AgentStateManager

logger = logging.getLogger(__name__)


class BaseHydroAgent(HydroAgentInstance, ABC):
    """
    Base class for Hydro agents with improved inheritance design.

    Inheritance hierarchy:
        HydroBaseModel (Pydantic base)
            ↓
        HydroAgent (agent definition)
            - agent_code, agent_type, agent_name, agent_configuration_url
            ↓
        HydroAgentInstance (running instance)
            - agent_id, biz_scene_instance_id, hydros_cluster_id, hydros_node_id
            - context, agent_biz_status, drive_mode
            ↓
        BaseHydroAgent (behavioral base class)
            - Adds lifecycle methods: on_init(), on_tick(), on_terminate()
            - Adds non-Pydantic attributes: sim_coordination_client, state_manager, properties

    Key features:
    1. Inherits from HydroAgentInstance for all agent instance properties
    2. No duplicate attributes - all inherited from parent classes
    3. sim_coordination_client is required in constructor (non-null)
    4. Clear lifecycle: created on task init, destroyed on terminate
    5. Each agent instance corresponds to one simulation task
    6. properties: AgentProperties dictionary for flexible configuration

    Non-Pydantic attributes (set dynamically, not serialized):
    - sim_coordination_client: The coordination client instance
    - state_manager: Reference to the state manager
    - properties: AgentProperties dictionary with typed accessors

    Attributes:
        sim_coordination_client: MQTT coordination client for sending commands
        state_manager: Agent state manager for tracking active contexts
        properties: AgentProperties dictionary with typed accessors
    """

    # Configure Pydantic to allow extra fields for non-model attributes
    model_config = ConfigDict(extra='allow', arbitrary_types_allowed=True)

    # Type hints for dynamically set attributes (set via object.__setattr__)
    # Using Field(exclude=True) to prevent Pydantic from treating these as model fields
    # Using TYPE_CHECKING to provide proper types for IDE without affecting runtime
    if TYPE_CHECKING:
        sim_coordination_client: 'SimCoordinationClient'
        state_manager: 'AgentStateManager'
        properties: AgentProperties

    # Runtime field definitions (excluded from Pydantic validation)
    # Using type: ignore to avoid type checking errors with None default
    sim_coordination_client: 'SimCoordinationClient' = Field(default=None, exclude=True)  # type: ignore[assignment]
    state_manager: 'AgentStateManager' = Field(default=None, exclude=True)  # type: ignore[assignment]
    properties: AgentProperties = Field(default=None, exclude=True)  # type: ignore[assignment]

    def __init__(
        self,
        sim_coordination_client,  # Type hint removed to avoid circular import
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        agent_biz_status: AgentBizStatus = AgentBizStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize agent instance.

        Args:
            sim_coordination_client: Required MQTT client (non-null)
            agent_id: Unique agent instance ID
            agent_code: Agent code (e.g., "TWINS_SIMULATION_AGENT")
            agent_type: Agent type (e.g., "TWINS_SIMULATION_AGENT")
            agent_name: Agent name (e.g., "Twins Simulation Agent")
            context: Simulation context for this agent
            hydros_cluster_id: Cluster ID where this agent runs
            hydros_node_id: Node ID where this agent runs
            agent_biz_status: Initial business status (default: INIT)
            drive_mode: Agent drive mode (default: SIM_TICK_DRIVEN)
            agent_configuration_url: Optional URL to agent configuration (will be loaded from SimTaskInitRequest if not provided)
            **kwargs: Additional keyword arguments for HydroAgentInstance
        """
        # Required parameters validation
        if sim_coordination_client is None:
            raise ValueError("sim_coordination_client is required")
        if context is None:
            raise ValueError("context is required")

        # Initialize parent HydroAgentInstance with all required fields
        super().__init__(
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            agent_configuration_url=agent_configuration_url or "",
            biz_scene_instance_id=context.biz_scene_instance_id,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            context=context,
            agent_biz_status=agent_biz_status,
            drive_mode=drive_mode,
            **kwargs
        )

        # Store non-Pydantic attributes (not serialized)
        # These are stored as extra fields due to model_config extra='allow'
        object.__setattr__(self, 'sim_coordination_client', sim_coordination_client)
        object.__setattr__(self, 'state_manager', sim_coordination_client.state_manager)
        object.__setattr__(self, 'properties', AgentProperties())

        # Note: Logging context (task_id, biz_component) is automatically set by
        # SimCoordinationClient when processing commands, so all logs in callbacks
        # will include the correct context information
        logger.info(f"Created agent instance: {self.agent_id}")
        logger.info(f"  - Agent Code: {self.agent_code}")
        logger.info(f"  - Agent Name: {self.agent_name}")
        logger.info(f"  - Agent Type: {self.agent_type}")
        logger.info(f"  - Context: {self.biz_scene_instance_id}")
        logger.info(f"  - Status: {self.agent_biz_status}")
        logger.info(f"  - Drive Mode: {self.drive_mode}")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the agent and create HydroAgentInstance.

        This is called when the task is initialized.

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        pass

    @abstractmethod
    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        Handle simulation tick.

        This is called for each simulation step.

        Args:
            request: Tick command request

        Returns:
            Tick command response
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the agent and clean up resources.

        This is called when the task is terminated.

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        pass

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        Handle time series data update.

        Default implementation. Override if needed.

        Args:
            request: Time series data update request

        Returns:
            Time series data update response
        """
        logger.info(f"Time series data update: {request.command_id}")

        return TimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,  # self is already a HydroAgentInstance
            broadcast=False
        )

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        Handle time series calculation.

        Default implementation. Override if needed.

        Args:
            request: Time series calculation request
        """
        logger.info(f"Time series calculation: {request.command_id}")

    def send_response(self, response):
        """
        Send a response via the coordination client.

        Args:
            response: Response to send
        """
        self.sim_coordination_client.enqueue(response)

    def load_agent_configuration(self, request: SimTaskInitRequest) -> None:
        """
        Load agent configuration from SimTaskInitRequest.

        This method:
        1. Extracts agent_configuration_url from request.agent_list matching this agent's agent_code
        2. Loads the YAML configuration from the URL
        3. Validates that the agent_code in YAML matches this agent's agent_code
        4. Sets the properties from YAML to self.properties

        Args:
            request: SimTaskInitRequest containing agent_list with configuration URLs

        Raises:
            ValueError: If agent not found in agent_list or agent_code mismatch
            Exception: If configuration loading fails
        """
        from hydros_agent_sdk.agent_config import AgentConfigLoader

        # Find matching agent in agent_list
        matching_agent = None
        for agent in request.agent_list:
            if agent.agent_code == self.agent_code:
                matching_agent = agent
                break

        if matching_agent is None:
            raise ValueError(
                f"Agent with code '{self.agent_code}' not found in SimTaskInitRequest.agent_list"
            )

        if not matching_agent.agent_configuration_url:
            logger.warning(f"No agent_configuration_url provided for agent '{self.agent_code}'")
            return

        agent_config_url = matching_agent.agent_configuration_url
        logger.info(f"Loading agent configuration from: {agent_config_url}")

        try:
            # Load configuration from URL
            agent_config = AgentConfigLoader.from_url(agent_config_url)

            # Validate agent_code matches
            if agent_config.agent_code != self.agent_code:
                raise ValueError(
                    f"Agent code mismatch: expected '{self.agent_code}', "
                    f"but YAML contains '{agent_config.agent_code}'. "
                    f"Please check the agent_configuration_url: {agent_config_url}"
                )

            logger.info(f"Agent configuration validated successfully for '{self.agent_code}'")

            # Set properties from YAML
            if agent_config.properties:
                # Convert Pydantic model to dict and update AgentProperties
                properties_dict = agent_config.properties.model_dump(exclude_none=True)
                self.properties.update(properties_dict)
                logger.info(f"Loaded {len(self.properties)} properties from configuration")
                logger.debug(f"Properties: {list(self.properties.keys())}")

            # Update agent_configuration_url
            object.__setattr__(self, 'agent_configuration_url', agent_config_url)

        except Exception as e:
            logger.error(f"Failed to load agent configuration from {agent_config_url}: {e}")
            raise
