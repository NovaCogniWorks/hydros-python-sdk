"""
Central Scheduling Power Agent

This agent implements Model Predictive Control (MPC) optimization for power systems.
It inherits from CentralSchedulingAgent and provides optimization logic for power
generation and distribution scheduling.

The agent:
1. Loads power system topology
2. Initializes optimization model for power scheduling
3. Subscribes to field metrics (power generation, consumption, etc.)
4. Executes MPC optimization at specified horizon
5. Sends control commands to power system components
"""

import logging
import os
import sys
import time
from typing import Optional, List, Dict, Any
import json

# Add current directory to Python path for potential power_solver import
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
from hydros_agent_sdk.agents import CentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    ObjectTimeSeries,
    CommandStatus,
)
from hydros_agent_sdk.utils import HydroObjectUtilsV2
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics

# Try to import power optimization solver if available
try:
    from power_solver import PowerOptimizationSolver
    HAS_POWER_SOLVER = True
except ImportError:
    HAS_POWER_SOLVER = False
    PowerOptimizationSolver = None

# Configure logging (only when running as main script)
# When imported by multi_agent_launcher, logging is already configured
if __name__ == "__main__":
    # Get the project directory (two levels up from this script)
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    EXAMPLES_DIR = os.path.join(PROJECT_DIR, "examples")
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
        log_file=os.path.join(LOG_DIR, "hydros.log"),
        use_rolling=True
    )

logger = logging.getLogger(__name__)


class PowerSchedulingAgent(CentralSchedulingAgent):
    """
    Concrete implementation of central scheduling agent for power systems.

    This agent:
    1. Loads power system topology
    2. Initializes power optimization model
    3. Subscribes to field metrics (power generation, load, etc.)
    4. Executes MPC optimization for power scheduling
    5. Sends control commands to generators and loads
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
        optimization_horizon: int = 10,
        **kwargs
    ):
        """Initialize power scheduling agent."""
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            optimization_horizon=optimization_horizon,
            **kwargs
        )

        # Power optimization solver
        self._power_solver: Optional[PowerOptimizationSolver] = None

        # Power system topology
        self._topology = None

        # Optimization parameters
        self._optimization_params = {}

        logger.info(f"PowerSchedulingAgent created: {agent_id}")
        logger.info(f"Optimization horizon: {optimization_horizon} ticks")

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize power scheduling agent with error handling.

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        logger.info("Initializing power scheduling agent...")

        # 1. Load agent configuration (skip if not in agent_list)
        self.load_agent_configuration(request)

        # 2. Load power system topology if configured
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        if topology_url:
            logger.info(f"Loading power system topology from: {topology_url}")

            success, topology, error_msg = safe_execute(
                HydroObjectUtilsV2.build_waterway_topology,
                ErrorCodes.TOPOLOGY_LOAD_FAILURE,
                self.agent_code,
                topology_url
            )

            if success:
                self._topology = topology
                logger.info(f"Power system topology loaded: {len(topology.top_objects)} top objects")
            else:
                logger.warning(f"Failed to load topology: {error_msg}")
                logger.warning("Continuing without topology...")

        # 3. Initialize power optimization solver
        logger.info("Initializing power optimization solver...")

        if HAS_POWER_SOLVER:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code
            ) as ctx:
                self._power_solver = PowerOptimizationSolver()
                if self._topology:
                    self._power_solver.initialize(self._topology)

            if ctx.has_error:
                logger.error(f"Failed to initialize power solver: {ctx.error_message}")
                # Continue without solver, will use dummy optimization
                self._power_solver = None
            else:
                logger.info("Power optimization solver initialized")
        else:
            logger.warning("PowerOptimizationSolver not available, using dummy optimization")

        # 4. Load optimization parameters
        self._optimization_params = {
            'time_horizon': self.properties.get_property('optimization_time_horizon', 24),  # hours
            'time_step': self.properties.get_property('optimization_time_step', 1),  # hour
            'objective': self.properties.get_property('optimization_objective', 'minimize_cost'),
            'constraints': self.properties.get_property('optimization_constraints', []),
        }
        logger.info(f"Optimization parameters: {self._optimization_params}")

        # 5. Subscribe to field metrics for real-time power data
        metrics_topic = self.properties.get_property(
            'field_metrics_topic',
            f"/hydros/metrics/power/{self.hydros_cluster_id}"
        )

        try:
            self.subscribe_to_field_metrics(metrics_topic)
            logger.info(f"Subscribed to field metrics: {metrics_topic}")
        except Exception as e:
            logger.warning(f"Failed to subscribe to metrics topic: {e}")

        # 6. Register with state manager
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        logger.info("Power scheduling agent initialized successfully")

        # 7. Return initialization response
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status="SUCCESS",
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={}
        )

    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        """
        Execute MPC optimization for power scheduling.

        This method implements the core optimization logic:
        1. Collect current system state (loads, generation, constraints)
        2. Gather field metrics (real-time measurements)
        3. Run optimization model
        4. Generate control commands for power system components

        Args:
            step: Current simulation step

        Returns:
            List of control commands to send to power system agents
        """
        logger.info(f"Executing power scheduling optimization at step {step}")

        # 1. Collect system state
        system_state = self._collect_system_state(step)
        logger.info(
            f"System state collected: {len(system_state.get('loads', []))} loads, "
            f"{len(system_state.get('generators', []))} generators"
        )

        # 2. Gather field metrics
        field_metrics = self._collect_field_metrics()
        logger.debug(f"Field metrics collected: {len(field_metrics)} measurements")

        # 3. Run optimization
        optimization_results = self._run_optimization(step, system_state, field_metrics)

        # 4. Generate control commands
        control_commands = self._generate_control_commands(optimization_results)

        logger.info(f"Optimization completed: {len(control_commands)} control commands generated")

        return control_commands

    def _collect_system_state(self, step: int) -> Dict[str, Any]:
        """
        Collect current power system state.

        Args:
            step: Current simulation step

        Returns:
            Dictionary containing system state information
        """
        system_state = {
            'step': step,
            'loads': [],
            'generators': [],
            'storage': [],
            'constraints': {},
        }

        # Extract information from topology if available
        if self._topology:
            for top_obj in self._topology.top_objects:
                for child in top_obj.children:
                    # Classify objects by type
                    if 'load' in child.object_name.lower() or 'demand' in child.object_name.lower():
                        system_state['loads'].append({
                            'id': child.object_id,
                            'name': child.object_name,
                            'type': 'load',
                        })
                    elif 'gen' in child.object_name.lower() or 'generator' in child.object_name.lower():
                        system_state['generators'].append({
                            'id': child.object_id,
                            'name': child.object_name,
                            'type': 'generator',
                        })
                    elif 'storage' in child.object_name.lower() or 'battery' in child.object_name.lower():
                        system_state['storage'].append({
                            'id': child.object_id,
                            'name': child.object_name,
                            'type': 'storage',
                        })

        # Add boundary conditions as constraints
        constraints = self._collect_boundary_constraints(step)
        if constraints:
            system_state['constraints'] = constraints

        return system_state

    def _collect_boundary_constraints(self, step: int) -> Dict[str, Any]:
        """
        Collect boundary constraints for optimization.

        Args:
            step: Current simulation step

        Returns:
            Dictionary of constraints
        """
        constraints = {}

        # Example: get time series data for constraints
        # This would be populated from time_series_cache
        constraint_metrics = ['max_generation', 'min_generation', 'max_load', 'min_load']

        for metric in constraint_metrics:
            # This is a placeholder - actual implementation would query time series cache
            constraints[metric] = None

        return constraints

    def _collect_field_metrics(self) -> Dict[str, float]:
        """
        Collect field metrics from cache.

        Returns:
            Dictionary of field metrics {object_id_metric: value}
        """
        field_metrics = {}

        # Get metrics from field metrics cache (populated by MQTT subscription)
        for cache_key, metrics_data in self._field_metrics_cache.items():
            field_metrics[cache_key] = metrics_data.get('value')

        return field_metrics

    def _run_optimization(
        self,
        step: int,
        system_state: Dict[str, Any],
        field_metrics: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Run power optimization.

        Args:
            step: Current simulation step
            system_state: Current system state
            field_metrics: Field measurements

        Returns:
            Optimization results
        """
        # Use power solver if available
        if self._power_solver and HAS_POWER_SOLVER:
            try:
                logger.info("Running optimization with PowerOptimizationSolver")

                with AgentErrorContext(
                    ErrorCodes.SIMULATION_EXECUTION_FAILURE,
                    agent_name=self.agent_code
                ) as ctx:
                    results = self._power_solver.optimize(
                        step=step,
                        system_state=system_state,
                        field_metrics=field_metrics,
                        horizon=self._optimization_horizon,
                        params=self._optimization_params
                    )

                if ctx.has_error:
                    logger.error(f"Optimization solver failed: {ctx.error_message}")
                    # Fall back to dummy optimization
                    return self._dummy_optimization(step, system_state, field_metrics)

                return results

            except Exception as e:
                logger.error(f"Error in optimization solver: {e}", exc_info=True)
                return self._dummy_optimization(step, system_state, field_metrics)
        else:
            # Use dummy optimization
            logger.info("Using dummy optimization (no solver available)")
            return self._dummy_optimization(step, system_state, field_metrics)

    def _dummy_optimization(
        self,
        step: int,
        system_state: Dict[str, Any],
        field_metrics: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Dummy optimization for demonstration purposes.

        Args:
            step: Current simulation step
            system_state: Current system state
            field_metrics: Field measurements

        Returns:
            Dummy optimization results
        """
        logger.debug("Running dummy optimization")

        # Simple rule-based scheduling
        results = {
            'step': step,
            'schedule': {},
            'total_cost': 0.0,
            'constraints_violated': False,
        }

        # Generate simple schedule
        for generator in system_state.get('generators', []):
            gen_id = generator['id']
            results['schedule'][gen_id] = {
                'power_output': 50.0,  # MW
                'cost': 45.0,  # $/MWh
                'status': 'online',
            }

        for load in system_state.get('loads', []):
            load_id = load['id']
            results['schedule'][load_id] = {
                'power_demand': 30.0,  # MW
                'priority': 'normal',
                'sheddable': True,
            }

        results['total_cost'] = len(system_state.get('generators', [])) * 50.0 * 45.0

        return results

    def _generate_control_commands(
        self,
        optimization_results: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate control commands from optimization results.

        Args:
            optimization_results: Optimization results

        Returns:
            List of control commands
        """
        control_commands = []

        schedule = optimization_results.get('schedule', {})

        # Generate commands for generators
        for object_id, schedule_info in schedule.items():
            if 'power_output' in schedule_info:
                # Generator control command
                command = {
                    'target_agent': f"GENERATOR_AGENT_{object_id}",
                    'command_type': 'SET_POWER_OUTPUT',
                    'parameters': {
                        'object_id': object_id,
                        'power_output': schedule_info['power_output'],
                        'step': optimization_results.get('step', 0),
                        'duration': self._optimization_horizon,
                    }
                }
                control_commands.append(command)

            elif 'power_demand' in schedule_info:
                # Load control command
                command = {
                    'target_agent': f"LOAD_AGENT_{object_id}",
                    'command_type': 'SET_POWER_DEMAND',
                    'parameters': {
                        'object_id': object_id,
                        'power_demand': schedule_info['power_demand'],
                        'step': optimization_results.get('step', 0),
                        'sheddable': schedule_info.get('sheddable', False),
                    }
                }
                control_commands.append(command)

        logger.debug(f"Generated {len(control_commands)} control commands")

        return control_commands

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        Handle boundary condition updates for power optimization.

        Args:
            time_series_list: List of updated time series data
        """
        logger.info(f"Updating power optimization with {len(time_series_list)} boundary conditions")

        for time_series in time_series_list:
            try:
                logger.info(
                    f"Power boundary condition update: "
                    f"object={time_series.object_name}, "
                    f"metrics={time_series.metrics_code}, "
                    f"values={len(time_series.time_series)}"
                )

                # Update optimization model constraints if solver exists
                if self._power_solver:
                    self._power_solver.update_constraints(
                        object_id=time_series.object_id,
                        metrics_code=time_series.metrics_code,
                        time_series=time_series.time_series
                    )

            except Exception as e:
                logger.error(
                    f"Error updating boundary condition for {time_series.object_name}: {e}",
                    exc_info=True
                )

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the power scheduling agent.

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        logger.info("Terminating power scheduling agent...")

        # 1. Clean up power solver
        if self._power_solver:
            logger.info("Cleaning up power solver...")

        # 2. Clean up state manager
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        # 3. Return termination response
        logger.info("Power scheduling agent termination complete")

        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status="SUCCESS",
            source_agent_instance=self
        )


def main():
    """
    Main entry point for power scheduling agent service.
    """
    # Get script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load environment configuration (with fallback to shared config)
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
        agent_class=PowerSchedulingAgent,
        config_file=CONFIG_FILE,
        env_config=env_config
    )

    # Create unified callback
    callback = MultiAgentCallback(node_id=os.getenv("HYDROS_NODE_ID", "LOCAL"))
    callback.register_agent_factory("CENTRAL_SCHEDULING_AGENT_POWER01", agent_factory)

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
        logger.info("=" * 70)
        logger.info("Starting Power Scheduling Agent Service")
        logger.info("=" * 70)
        logger.info(f"Environment config: {ENV_FILE}")
        logger.info(f"Agent config: {CONFIG_FILE}")
        logger.info(f"MQTT Broker: {BROKER_URL}:{BROKER_PORT}")
        logger.info(f"MQTT Topic: {TOPIC}")
        logger.info("=" * 70)

        sim_coordination_client.start()

        logger.info("Service started successfully!")
        logger.info("Ready to create power scheduling agent instances for incoming tasks...")
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
