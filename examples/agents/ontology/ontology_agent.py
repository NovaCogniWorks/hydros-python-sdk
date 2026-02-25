"""
Ontology Simulation Agent Example

This example demonstrates how to implement a concrete ontology-based simulation agent
using the OntologySimulationAgent base class.

The agent performs ontology-based water network simulation with rule-based logic.
"""

import logging
import os
import sys
import time
from typing import Optional, List, Dict, Any

# Add current directory to Python path for ontology_rule_engine import
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    setup_logging,
    SimCoordinationClient,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
    ErrorCodes,
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
)
from hydros_agent_sdk.agents import OntologySimulationAgent
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
)
from hydros_agent_sdk.utils import HydroObjectUtilsV2

# Import example ontology rule engine implementation
from ontology_rule_engine import OntologyRuleEngine

# Configure logging (only when running as main script)
# When imported by multi_agent_launcher, logging is already configured
if __name__ == "__main__":
    # Get the examples directory (two levels up from this script)
    EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    # Load env config to get cluster_id and node_id for logging
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
        log_file=os.path.join(LOG_DIR, "ontology_agent.log")
    )

logger = logging.getLogger(__name__)


class MyOntologySimulationAgent(OntologySimulationAgent):
    """
    Concrete implementation of ontology simulation agent.

    This agent:
    1. Loads water network topology
    2. Initializes ontology rule engine
    3. Executes ontology-based simulation at each tick
    4. Handles boundary condition updates
    5. Outputs metrics via MQTT
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
        """Initialize ontology simulation agent."""
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

        # Ontology rule engine
        self._rule_engine: Optional[OntologyRuleEngine] = None

        logger.info(f"MyOntologySimulationAgent created: {agent_id}")

    def _initialize_ontology_model(self):
        """
        Initialize ontology model with error handling.

        This method initializes the ontology rule engine with the loaded topology.
        """
        logger.info("Initializing ontology model...")

        # Create ontology rule engine with error context
        with AgentErrorContext(
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            self._rule_engine = OntologyRuleEngine()

        if ctx.has_error:
            logger.error(f"Failed to create rule engine: {ctx.error_message}")
            raise RuntimeError(f"Rule engine creation failed: {ctx.error_message}")

        # Load ontology from topology
        if self._topology:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code
            ) as ctx:
                self._rule_engine.load_ontology(self._topology)

            if ctx.has_error:
                logger.error(f"Failed to load ontology: {ctx.error_message}")
                raise RuntimeError(f"Ontology load failed: {ctx.error_message}")

            logger.info("Ontology model initialized with topology")
        else:
            logger.warning("No topology available for ontology model")

        # Load ontology parameters from configuration with error handling
        with AgentErrorContext(
            ErrorCodes.CONFIGURATION_LOAD_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            ontology_params = {
                'reasoning_mode': self.properties.get_property('reasoning_mode', 'forward_chaining'),
                'rule_file': self.properties.get_property('rule_file', None),
                'inference_depth': self.properties.get_property('inference_depth', 3),
            }

        if ctx.has_error:
            logger.warning(f"Failed to load parameters, using defaults: {ctx.error_message}")
            ontology_params = {
                'reasoning_mode': 'forward_chaining',
                'rule_file': None,
                'inference_depth': 3,
            }

        logger.info(f"Ontology parameters: {ontology_params}")

    def _execute_ontology_simulation(self, step: int) -> List[Dict[str, Any]]:
        """
        Execute ontology-based simulation step with comprehensive error handling.

        This method:
        1. Collects boundary conditions from cache
        2. Applies ontology rules
        3. Returns computed metrics

        Args:
            step: Current simulation step

        Returns:
            List of metrics dictionaries
        """
        logger.info(f"Executing ontology simulation for step {step}")

        if not self._rule_engine:
            logger.error("Ontology rule engine not initialized")
            return []

        # Collect boundary conditions with error handling
        with AgentErrorContext(
            ErrorCodes.BOUNDARY_CONDITION_ERROR,
            agent_name=self.agent_code
        ) as ctx:
            boundary_conditions = self._collect_boundary_conditions(step)

        if ctx.has_error:
            logger.error(f"Failed to collect boundary conditions: {ctx.error_message}")
            # Use empty boundary conditions as fallback
            boundary_conditions = {}

        logger.debug(f"Boundary conditions: {len(boundary_conditions)} objects")

        # Apply ontology rules with error handling
        with AgentErrorContext(
            ErrorCodes.SIMULATION_EXECUTION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            results = self._rule_engine.apply_rules(step, boundary_conditions)

        if ctx.has_error:
            logger.error(f"Ontology reasoning failed: {ctx.error_message}")
            return []

        logger.info(f"Ontology reasoning completed for step {step}")

        # Convert results to metrics with error handling
        with AgentErrorContext(
            ErrorCodes.METRICS_GENERATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            metrics_list = self._convert_results_to_metrics(results)

        if ctx.has_error:
            logger.error(f"Failed to convert results: {ctx.error_message}")
            return []

        logger.info(f"Generated {len(metrics_list)} metrics for step {step}")

        return metrics_list

    def _collect_boundary_conditions(self, step: int) -> Dict[int, Dict[str, float]]:
        """
        Collect boundary conditions from time series cache.

        Args:
            step: Current simulation step

        Returns:
            Boundary conditions {object_id: {metrics_code: value}}
        """
        boundary_conditions = {}

        # Get boundary condition metrics codes from configuration
        bc_metrics = self.properties.get_property(
            'boundary_condition_metrics',
            ['inflow', 'upstream_water_level']
        )

        # Collect boundary conditions for all objects
        if self._topology:
            for top_obj in self._topology.top_objects:
                for child in top_obj.children:
                    object_bc = {}

                    for metrics_code in bc_metrics:
                        # Get value from time series cache
                        value = self.get_time_series_value(
                            child.object_id,
                            metrics_code,
                            step
                        )

                        if value is not None:
                            object_bc[metrics_code] = value

                    if object_bc:
                        boundary_conditions[child.object_id] = object_bc

        return boundary_conditions

    def _convert_results_to_metrics(
        self,
        results: Dict[int, Dict[str, float]]
    ) -> List[Dict[str, Any]]:
        """
        Convert reasoning results to metrics list.

        Args:
            results: Reasoning results {object_id: {metrics_code: value}}

        Returns:
            List of metrics dictionaries
        """
        metrics_list = []

        # Get object names from topology
        object_names = {}
        if self._topology:
            for top_obj in self._topology.top_objects:
                for child in top_obj.children:
                    object_names[child.object_id] = child.object_name

        # Convert results to metrics
        for object_id, values in results.items():
            object_name = object_names.get(object_id, f"Object_{object_id}")

            for metrics_code, value in values.items():
                metrics_list.append({
                    'object_id': object_id,
                    'object_name': object_name,
                    'metrics_code': metrics_code,
                    'value': value
                })

        return metrics_list


def main():
    """
    Main entry point for ontology simulation agent service.
    """
    # Get script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load environment configuration
    ENV_FILE = os.path.join(script_dir, "env.properties")
    env_config = load_env_config(ENV_FILE)

    BROKER_URL = env_config['mqtt_broker_url']
    BROKER_PORT = int(env_config['mqtt_broker_port'])
    TOPIC = env_config['mqtt_topic']
    MQTT_USERNAME = env_config.get('mqtt_username')
    MQTT_PASSWORD = env_config.get('mqtt_password')

    # Agent configuration file
    CONFIG_FILE = os.path.join(script_dir, "agent.properties")

    # Create agent factory using generic HydroAgentFactory
    agent_factory = HydroAgentFactory(
        agent_class=MyOntologySimulationAgent,
        config_file=CONFIG_FILE,
        env_config=env_config
    )

    # Create unified callback
    callback = MultiAgentCallback(node_id=os.getenv("HYDROS_NODE_ID", "LOCAL"))
    callback.register_agent_factory("ONTOLOGY_SIMULATION_AGENT", agent_factory)

    # Create coordination client
    sim_coordination_client = SimCoordinationClient(
        broker_url=BROKER_URL,
        broker_port=BROKER_PORT,
        topic=TOPIC,
        sim_coordination_callback=callback,
        mqtt_username=MQTT_USERNAME,
        mqtt_password=MQTT_PASSWORD
    )

    # Set client reference
    callback.set_client(sim_coordination_client)

    # Start service
    try:
        logger.info("="*70)
        logger.info("Starting Ontology Simulation Agent Service")
        logger.info("="*70)
        logger.info(f"Environment config: {ENV_FILE}")
        logger.info(f"Agent config: {CONFIG_FILE}")
        logger.info(f"MQTT Broker: {BROKER_URL}:{BROKER_PORT}")
        logger.info(f"MQTT Topic: {TOPIC}")
        logger.info("="*70)

        sim_coordination_client.start()

        logger.info("Service started successfully!")
        logger.info("Ready to create ontology agent instances for incoming tasks...")
        logger.info("Press Ctrl+C to stop...")

        # Keep running
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Stopping service...")
        sim_coordination_client.stop()
        logger.info("Service stopped")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sim_coordination_client.stop()


if __name__ == "__main__":
    main()
