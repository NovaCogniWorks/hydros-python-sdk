"""
Outflow plan agent for event-driven outflow planning.

This module provides the OutflowPlanAgent class which extends BaseHydroAgent
with event-driven outflow planning capabilities.
"""

import logging
from typing import Optional, List
from abc import abstractmethod

from .tickable_agent import TickableAgent, MqttMetrics
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    OutflowTimeSeriesRequest, OutflowTimeSeriesResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

from hydros_agent_sdk.utils import HydroObjectUtilsV2

logger = logging.getLogger(__name__)


class OutflowPlanAgent(TickableAgent):
    """
    Event-driven outflow plan agent.

    This agent performs outflow planning in response to events:
    1. Receives OutflowTimeSeriesRequest from coordinator
    2. Executes outflow planning logic
    3. Produces ObjectTimeSeries results for outflow plans
    4. Returns response to coordinator

    Key features:
    - Event-driven execution (not tick-driven)
    - Outflow planning based on hydro events
    - Time series output for planned outflows

    Usage example:
        ```python
        agent = OutflowPlanAgent(
            sim_coordination_client=client,
            agent_id="OUTFLOW_PLAN_001",
            agent_code="OUTFLOW_PLAN_AGENT",
            agent_type="OUTFLOW_PLAN_AGENT",
            agent_name="Outflow Plan Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01",
            drive_mode=AgentDriveMode.EVENT_DRIVEN
        )
        ```

    Subclasses must implement:
    - on_init(): Initialize agent and load configuration
    - on_outflow_time_series(): Execute outflow planning logic
    - on_terminate(): Clean up resources
    """

    def __init__(
        self,
        sim_coordination_client,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        agent_biz_status: AgentBizStatus = AgentBizStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.EVENT_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize outflow plan agent.

        Args:
            sim_coordination_client: Required MQTT client
            agent_id: Unique agent instance ID
            agent_code: Agent code
            agent_type: Agent type
            agent_name: Agent name
            context: Simulation context
            hydros_cluster_id: Cluster ID
            hydros_node_id: Node ID
            agent_biz_status: Initial business status
            drive_mode: Agent drive mode (default: EVENT_DRIVEN)
            agent_configuration_url: Optional configuration URL
            **kwargs: Additional keyword arguments
        """
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            agent_biz_status=agent_biz_status,
            drive_mode=drive_mode,
            agent_configuration_url=agent_configuration_url,
            **kwargs
        )

        # Outflow plan state
        self._plan_config = {}

        self._topology = None

        logger.info(f"OutflowPlanAgent initialized: {self.agent_id}")

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the outflow plan agent.

        Subclasses should:
        1. Load agent configuration using self.load_agent_configuration(request)
        2. Load topology and initialize planning models
        3. Register with state manager
        4. Return SimTaskInitResponse

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        logger.info(f"Initializing outflow plan agent: {self.agent_id}")

        # Load agent configuration
        self.load_agent_configuration(request)

        # Load topology if configured
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        if topology_url:
            logger.info(f"Loading topology from: {topology_url}")
            self._topology = HydroObjectUtilsV2.build_waterway_topology(topology_url)
            logger.info(f"Topology loaded: {len(self._topology.top_objects)} top objects")

        # Initialize planning models
        self._initialize_planning_models()

        # Register with state manager
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        logger.info(f"Outflow plan agent initialized successfully: {self.agent_id}")

        # Update agent status to ACTIVE
        object.__setattr__(self, 'agent_biz_status', AgentBizStatus.ACTIVE)

        # Return response
        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False
        )

    def _initialize_planning_models(self):
        """Initialize outflow planning models."""
        logger.info("Initializing outflow planning models...")

        # Load planning configuration
        planning_config = self.properties.get_property('planning_config', {})

        # Initialize your planning models here
        # For example: optimization models, forecasting models, etc.

        logger.info("Planning models initialized")

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        Execute ontology-based simulation step.

        Args:
            request: Tick command request

        Returns:
            List of MqttMetrics objects to send via MQTT
        """
        return None

    @abstractmethod
    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        Handle outflow time series request.

        Subclasses must implement this method to perform outflow planning logic.
        This method should:
        1. Extract event information from request
        2. Execute outflow planning calculations
        3. Generate ObjectTimeSeries results
        4. Send response back to coordinator

        Args:
            request: Outflow time series request containing hydro event
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the outflow plan agent.

        Subclasses should:
        1. Clean up planning resources
        2. Unregister from state manager
        3. Return SimTaskTerminateResponse

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        pass
