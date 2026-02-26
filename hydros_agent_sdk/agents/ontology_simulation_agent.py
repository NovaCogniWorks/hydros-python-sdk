"""
Ontology simulation agent for ontology-based water network simulation.

This module provides the OntologySimulationAgent class which extends TickableAgent
with ontology-based simulation capabilities.
"""

import logging
from typing import Optional, List

from .tickable_agent import TickableAgent
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


class OntologySimulationAgent(TickableAgent):
    """
    Ontology-based simulation agent.

    This agent performs ontology-based water network simulation:
    1. Loads water network topology from ontology model
    2. Executes simulation steps based on ontology rules
    3. Handles boundary condition updates
    4. Outputs metrics data via MQTT

    Key features:
    - Ontology-based modeling and simulation
    - Rule-based simulation logic
    - Support for complex water network topology
    - Boundary condition handling

    Usage example:
        ```python
        agent = OntologySimulationAgent(
            sim_coordination_client=client,
            agent_id="ONTOLOGY_SIM_001",
            agent_code="ONTOLOGY_SIMULATION_AGENT",
            agent_type="ONTOLOGY_SIMULATION_AGENT",
            agent_name="Ontology Simulation Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01"
        )
        ```
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
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize ontology simulation agent.

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
            drive_mode: Agent drive mode (default: SIM_TICK_DRIVEN)
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

        # Ontology model and topology
        self._ontology_model = None
        self._topology = None

        logger.info(f"OntologySimulationAgent initialized: {self.agent_id}")

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the ontology simulation agent.

        This method:
        1. Loads agent configuration from SimTaskInitRequest
        2. Loads water network topology from ontology model
        3. Initializes simulation state
        4. Registers with state manager

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        logger.info("="*70)
        logger.info(f"INITIALIZING ONTOLOGY SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # Load agent configuration
            logger.info("Loading agent configuration...")
            self.load_agent_configuration(request)
            logger.info(f"Configuration loaded with {len(self.properties)} properties")

            # Load water network topology from ontology model
            hydros_objects_modeling_url = self.properties.get_property('hydros_objects_modeling_url')
            if hydros_objects_modeling_url:
                logger.info("Loading water network topology from ontology model...")
                from hydros_agent_sdk.utils import HydroObjectUtilsV2

                # Load topology with specific parameters
                param_keys = self.properties.get_property('param_keys', {'max_opening', 'min_opening'})
                self._topology = HydroObjectUtilsV2.build_waterway_topology(
                    modeling_yml_uri=hydros_objects_modeling_url,
                    param_keys=param_keys,
                    with_metrics_code=True
                )

                logger.info(f"Loaded topology with {len(self._topology.top_objects)} top-level objects")

                # Initialize ontology model (subclass-specific)
                self._initialize_ontology_model()
            else:
                logger.warning("No hydros_objects_modeling_url configured")

            # Update agent status to ACTIVE
            object.__setattr__(self, 'agent_biz_status', AgentBizStatus.ACTIVE)

            # Register with state manager
            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)

            logger.info(f"Ontology simulation agent initialized: {self.agent_id}")

            # Create response
            response = SimTaskInitResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                created_agent_instances=[self],
                managed_top_objects={},
                broadcast=False
            )

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=sim_task_init_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Failed to initialize ontology simulation agent: {e}", exc_info=True)

            # Return failed response
            return SimTaskInitResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                created_agent_instances=[],
                managed_top_objects={},
                broadcast=False
            )

    def _initialize_ontology_model(self):
        """
        Initialize ontology model.

        Subclasses can override this method to initialize their specific ontology model.
        Default implementation does nothing.
        """
        logger.info("Initializing ontology model...")
        # TODO: Load ontology rules, constraints, etc.
        pass

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        Execute ontology-based simulation step.

        Args:
            request: Tick command request

        Returns:
            List of MqttMetrics objects to send via MQTT
        """
        logger.info(f"Executing ontology simulation step {request.step}")

        try:
            metrics_list = self._execute_ontology_simulation(request.step)
            logger.info(f"Ontology simulation step {request.step} completed")
            return metrics_list

        except Exception as e:
            logger.error(f"Error in ontology simulation step {request.step}: {e}", exc_info=True)
            return None

    def _execute_ontology_simulation(self, step: int) -> List[MqttMetrics]:
        """
        Execute ontology-based simulation logic.

        Subclasses should override this method to implement their specific
        ontology-based simulation logic.

        Args:
            step: Current simulation step

        Returns:
            List of MqttMetrics objects
        """
        # Default implementation: return empty metrics
        # Subclasses should override this method
        logger.warning("Using default ontology simulation (no-op)")
        return []

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        Handle boundary condition updates for ontology simulation.

        This method updates the ontology model with new boundary conditions.

        Args:
            time_series_list: List of updated time series data
        """
        logger.info(f"Updating ontology model with {len(time_series_list)} boundary conditions")

        # Update ontology model with boundary conditions
        for time_series in time_series_list:
            logger.debug(
                f"Boundary condition: object={time_series.object_name}, "
                f"metrics={time_series.metrics_code}"
            )
            # TODO: Update ontology model state

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the ontology simulation agent.

        This method:
        1. Cleans up ontology model
        2. Unregisters from state manager
        3. Returns SimTaskTerminateResponse

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        logger.info("="*70)
        logger.info(f"TERMINATING ONTOLOGY SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # Clean up ontology model
            self._ontology_model = None
            self._topology = None

            # Unregister from state manager
            self.state_manager.terminate_task(self.context)
            self.state_manager.remove_local_agent(self)

            logger.info(f"Ontology simulation agent terminated: {self.agent_id}")

            # Create response
            response = SimTaskTerminateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                broadcast=False
            )

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=sim_task_terminate_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Error terminating ontology simulation agent: {e}", exc_info=True)

            # Return failed response
            return SimTaskTerminateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                broadcast=False
            )
