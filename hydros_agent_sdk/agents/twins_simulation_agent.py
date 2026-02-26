"""
Digital twins simulation agent for real-time water network simulation.

This module provides the TwinsSimulationAgent class which extends TickableAgent
with digital twins simulation capabilities.
"""

import logging
from typing import Optional, List

from .tickable_agent import TickableAgent
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics
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


class TwinsSimulationAgent(TickableAgent):
    """
    Digital twins simulation agent.

    This agent performs digital twins-based water network simulation:
    1. Loads water network topology and physical models
    2. Executes high-fidelity simulation steps
    3. Handles real-time boundary condition updates
    4. Outputs detailed metrics data via MQTT

    Key features:
    - High-fidelity physical modeling
    - Real-time simulation synchronization
    - Support for complex hydraulic calculations
    - Boundary condition handling
    - State synchronization with physical system

    Usage example:
        ```python
        agent = TwinsSimulationAgent(
            sim_coordination_client=client,
            agent_id="TWINS_SIM_001",
            agent_code="TWINS_SIMULATION_AGENT",
            agent_type="TWINS_SIMULATION_AGENT",
            agent_name="Digital Twins Simulation Agent",
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
        Initialize digital twins simulation agent.

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

        # Digital twins model and state
        self._twins_model = None
        self._topology = None
        self._simulation_state = {}

        logger.info(f"TwinsSimulationAgent initialized: {self.agent_id}")

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the digital twins simulation agent.

        This method:
        1. Loads agent configuration from SimTaskInitRequest
        2. Loads water network topology and physical models
        3. Initializes simulation state
        4. Registers with state manager

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        logger.info("="*70)
        logger.info(f"INITIALIZING DIGITAL TWINS SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # Load agent configuration
            logger.info("Loading agent configuration...")
            self.load_agent_configuration(request)
            logger.info(f"Configuration loaded with {len(self.properties)} properties")

            # Load water network topology
            hydros_objects_modeling_url = self.properties.get_property('hydros_objects_modeling_url')
            if hydros_objects_modeling_url:
                logger.info("Loading water network topology for digital twins...")
                from hydros_agent_sdk.utils import HydroObjectUtilsV2

                # Load topology with all parameters for high-fidelity simulation
                param_keys = self.properties.get_property(
                    'param_keys',
                    {'max_opening', 'min_opening', 'interpolate_cross_section_count'}
                )
                self._topology = HydroObjectUtilsV2.build_waterway_topology(
                    modeling_yml_uri=hydros_objects_modeling_url,
                    param_keys=param_keys,
                    with_metrics_code=True
                )

                logger.info(f"Loaded topology with {len(self._topology.top_objects)} top-level objects")

                # Initialize digital twins model (subclass-specific)
                self._initialize_twins_model()
            else:
                logger.warning("No hydros_objects_modeling_url configured")

            # Update agent status to ACTIVE
            object.__setattr__(self, 'agent_biz_status', AgentBizStatus.ACTIVE)

            # Register with state manager
            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)

            logger.info(f"Digital twins simulation agent initialized: {self.agent_id}")

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
            logger.error(f"Failed to initialize digital twins simulation agent: {e}", exc_info=True)

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

    def _initialize_twins_model(self):
        """
        Initialize digital twins model.

        Subclasses can override this method to initialize their specific
        digital twins model (e.g., hydraulic solver, state estimator).
        Default implementation does nothing.
        """
        logger.info("Initializing digital twins model...")
        # TODO: Initialize hydraulic solver, state estimator, etc.
        pass

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        Execute digital twins simulation step.

        Args:
            request: Tick command request

        Returns:
            List of MqttMetrics objects to send via MQTT
        """
        logger.info(f"Executing digital twins simulation step {request.step}")

        try:
            metrics_list = self._execute_twins_simulation(request.step)
            logger.info(f"Digital twins simulation step {request.step} completed")
            return metrics_list

        except Exception as e:
            logger.error(f"Error in digital twins simulation step {request.step}: {e}", exc_info=True)
            return None

    def _execute_twins_simulation(self, step: int) -> List[MqttMetrics]:
        """
        Execute digital twins simulation logic.

        Subclasses should override this method to implement their specific
        digital twins simulation logic (e.g., hydraulic calculations).

        Args:
            step: Current simulation step

        Returns:
            List of MqttMetrics objects
        """
        # Default implementation: return mock metrics
        # Subclasses should override this method
        logger.warning("Using default digital twins simulation (mock data)")

        metrics_list = []
        if self._topology:
            for top_obj in self._topology.top_objects[:3]:  # First 3 objects
                for child in top_obj.children[:2]:  # First 2 children
                    if child.metrics:
                        for metrics_code in child.metrics[:1]:  # First metric
                            metrics_list.append(create_mock_metrics(
                                source_id=self.agent_code,
                                job_instance_id=self.biz_scene_instance_id,
                                object_id=child.object_id,
                                object_name=child.object_name,
                                step_index=step,
                                metrics_code=metrics_code,
                                value=0.5 + (step % 10) * 0.05
                            ))

        return metrics_list

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        Handle boundary condition updates for digital twins simulation.

        This method updates the simulation state with new boundary conditions
        for real-time synchronization with the physical system.

        Args:
            time_series_list: List of updated time series data
        """
        logger.info(f"Updating digital twins state with {len(time_series_list)} boundary conditions")

        # Update simulation state with boundary conditions
        for time_series in time_series_list:
            logger.debug(
                f"Boundary condition: object={time_series.object_name}, "
                f"metrics={time_series.metrics_code}"
            )

            # Store in simulation state
            state_key = f"{time_series.object_id}_{time_series.metrics_code}"
            self._simulation_state[state_key] = time_series

            # TODO: Update hydraulic solver boundary conditions

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the digital twins simulation agent.

        This method:
        1. Cleans up digital twins model
        2. Unregisters from state manager
        3. Returns SimTaskTerminateResponse

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        logger.info("="*70)
        logger.info(f"TERMINATING DIGITAL TWINS SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        try:
            # Clean up digital twins model
            self._twins_model = None
            self._topology = None
            self._simulation_state.clear()

            # Unregister from state manager
            self.state_manager.terminate_task(self.context)
            self.state_manager.remove_local_agent(self)

            logger.info(f"Digital twins simulation agent terminated: {self.agent_id}")

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
            logger.error(f"Error terminating digital twins simulation agent: {e}", exc_info=True)

            # Return failed response
            return SimTaskTerminateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                broadcast=False
            )
