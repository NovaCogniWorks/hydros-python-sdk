"""
Outflow Plan Agent Example

This example demonstrates how to implement a concrete outflow plan agent
using the OutflowPlanAgent base class.

The agent performs outflow planning in response to hydro events.
"""

import logging
import os
import sys
from typing import Optional, List

# Add current directory to Python path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    setup_logging,
    SimCoordinationClient,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
    load_agent_config,
    ErrorCodes,
    handle_agent_errors,
)
from hydros_agent_sdk.agents import OutflowPlanAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    OutflowTimeSeriesRequest,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    ObjectTimeSeries,
    TimeSeriesValue,
)

# Configure logging (only when running as main script)
if __name__ == "__main__":
    EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    try:
        env_config = load_env_config()
        hydros_cluster_id = env_config.get('hydros_cluster_id', 'default_cluster')
        hydros_node_id = env_config.get('hydros_node_id', 'LOCAL')
    except Exception:
        hydros_cluster_id = 'default_cluster'
        hydros_node_id = os.getenv("HYDROS_NODE_ID", "LOCAL")

    setup_logging(
        level=logging.INFO,
        hydros_cluster_id=hydros_cluster_id,
        hydros_node_id=hydros_node_id,
        console=True,
        log_file=os.path.join(LOG_DIR, "hydros.log"),
        use_rolling=True
    )

logger = logging.getLogger(__name__)


class MyOutflowPlanAgent(OutflowPlanAgent):
    """
    Concrete implementation of outflow plan agent.

    This agent:
    1. Loads water network topology
    2. Initializes outflow planning models
    3. Responds to outflow time series requests
    4. Generates outflow plans based on hydro events
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
        **kwargs
    ):
        """Initialize outflow plan agent."""
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            **kwargs
        )

        # Topology
        self._topology = None

        logger.info(f"MyOutflowPlanAgent created: {agent_id}")

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        Handle outflow time series request.

        This method:
        1. Extracts event information from request
        2. Executes outflow planning logic
        3. Generates ObjectTimeSeries results
        4. Sends response back to coordinator
        """
        logger.info(f"Received OutflowTimeSeriesRequest, commandId={request.command_id}")
        logger.info(f"Event: {request.hydro_event}")

        try:
            # Execute outflow planning
            outflow_plans = self._execute_outflow_planning(request.hydro_event)

            logger.info(f"Outflow planning completed, produced {len(outflow_plans)} time series")

            # Create response (if needed - depends on protocol design)
            # For now, just log the results
            for plan in outflow_plans:
                logger.info(f"Outflow plan for {plan.object_name}: {len(plan.time_series)} steps")

        except Exception as e:
            logger.error(f"Error in outflow planning: {e}", exc_info=True)
            raise

    def _execute_outflow_planning(self, hydro_event) -> List[ObjectTimeSeries]:
        """
        Execute outflow planning logic.

        This is where you implement your specific outflow planning algorithm.

        Args:
            hydro_event: Event that triggered the planning

        Returns:
            List of ObjectTimeSeries containing outflow plans
        """
        logger.info("Executing outflow planning...")

        # Example: Generate mock outflow plans
        outflow_plans = []

        # Get planning horizon from configuration
        planning_horizon = self.properties.get_property('planning_horizon', 24)

        # Generate outflow plan for each relevant object
        if self._topology:
            for top_obj in self._topology.top_objects[:3]:  # Example: first 3 objects
                time_series_values = []

                for step in range(planning_horizon):
                    # Your planning logic here
                    # For example: optimization, forecasting, rule-based planning, etc.
                    planned_outflow = self._calculate_planned_outflow(top_obj, step, hydro_event)

                    time_series_values.append(
                        TimeSeriesValue(
                            step=step,
                            value=planned_outflow
                        )
                    )

                # Create ObjectTimeSeries
                outflow_plan = ObjectTimeSeries(
                    time_series_name=f"{top_obj.object_name}_outflow_plan",
                    object_id=top_obj.object_id,
                    object_type=top_obj.object_type,
                    object_name=top_obj.object_name,
                    metrics_code="planned_outflow",
                    time_series=time_series_values
                )

                outflow_plans.append(outflow_plan)

        logger.info(f"Generated {len(outflow_plans)} outflow plans")
        return outflow_plans

    def _calculate_planned_outflow(self, hydro_object, step: int, hydro_event) -> float:
        """
        Calculate planned outflow for a specific object and time step.

        This is a placeholder - implement your actual planning algorithm here.
        """
        # Example: Simple rule-based planning
        base_outflow = 100.0
        variation = step * 5.0

        return base_outflow + variation

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the outflow plan agent.

        This method:
        1. Cleans up planning resources
        2. Unregisters from state manager
        3. Returns termination response
        """
        logger.info(f"Terminating outflow plan agent: {self.agent_id}")

        # Clean up resources
        self._topology = None
        self._plan_config = {}

        # Unregister from state manager
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        logger.info(f"Outflow plan agent terminated: {self.agent_id}")

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False
        )


# ============================================================================
# Agent Factory
# ============================================================================

class OutflowPlanAgentFactory(HydroAgentFactory):
    """Factory for creating outflow plan agent instances."""

    def create_agent(
        self,
        sim_coordination_client: SimCoordinationClient,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        **kwargs
    ):
        """Create a new outflow plan agent instance."""
        return MyOutflowPlanAgent(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            **kwargs
        )


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point for outflow plan agent."""
    logger.info("=" * 80)
    logger.info("Starting Outflow Plan Agent")
    logger.info("=" * 80)

    try:
        # Load configuration
        env_config = load_env_config()
        agent_config = load_agent_config()

        # Extract configuration
        mqtt_broker_url = env_config['mqtt_broker_url']
        mqtt_broker_port = env_config['mqtt_broker_port']
        mqtt_topic = env_config['mqtt_topic']
        hydros_cluster_id = env_config.get('hydros_cluster_id', 'default_cluster')
        hydros_node_id = env_config.get('hydros_node_id', 'LOCAL')

        agent_code = agent_config['agent_code']
        agent_type = agent_config['agent_type']
        agent_name = agent_config['agent_name']

        logger.info(f"Agent Code: {agent_code}")
        logger.info(f"Agent Type: {agent_type}")
        logger.info(f"MQTT Broker: {mqtt_broker_url}:{mqtt_broker_port}")
        logger.info(f"MQTT Topic: {mqtt_topic}")

        # Create factory
        factory = OutflowPlanAgentFactory()

        # Create multi-agent callback
        callback = MultiAgentCallback(factory)

        # Create coordination client
        client = SimCoordinationClient(
            broker_url=mqtt_broker_url,
            broker_port=mqtt_broker_port,
            topic=mqtt_topic,
            callback=callback,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id
        )

        # Connect and start
        client.connect()
        logger.info("Outflow plan agent connected and ready")

        # Keep running
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            client.disconnect()

    except Exception as e:
        logger.error(f"Failed to start outflow plan agent: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
