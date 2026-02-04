"""
Digital Twins Simulation Agent with Error Handling

This example demonstrates how to use error handling in a twins simulation agent.
"""

import logging
import os
import sys
from typing import Optional, List, Dict, Any

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
    ErrorCodes,
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
)
from hydros_agent_sdk.agents import TwinsSimulationAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    ObjectTimeSeries,
)
from hydros_agent_sdk.utils import HydroObjectUtilsV2

# Import hydraulic solver
from hydraulic_solver import HydraulicSolver

logger = logging.getLogger(__name__)


class TwinsAgentWithErrorHandling(TwinsSimulationAgent):
    """
    Twins simulation agent with comprehensive error handling.

    This agent demonstrates best practices for error handling:
    1. Use @handle_agent_errors for lifecycle methods
    2. Use safe_execute() for individual operations
    3. Use AgentErrorContext for code blocks
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hydraulic_solver: Optional[HydraulicSolver] = None

    # ========== Lifecycle Methods with Error Handling ==========

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize agent with automatic error handling.

        Any exception will be caught and converted to SimTaskInitResponse
        with FAILED status and appropriate error code/message.
        """
        logger.info("Initializing twins agent with error handling...")

        # Load configuration (may raise exception)
        self.load_agent_configuration(request)

        # Load topology with safe_execute
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        if topology_url:
            success, topology, error_msg = safe_execute(
                HydroObjectUtilsV2.build_waterway_topology,
                ErrorCodes.TOPOLOGY_LOAD_FAILURE,
                self.agent_code,
                topology_url
            )

            if not success:
                logger.error(f"Failed to load topology: {error_msg}")
                raise RuntimeError(f"Topology load failed: {error_msg}")

            self._topology = topology
            logger.info(f"Topology loaded: {len(self._topology.top_objects)} top objects")

        # Register with state manager
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        # Initialize twins model
        self._initialize_twins_model()

        logger.info("Twins agent initialized successfully")

        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={}
        )

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate agent with automatic error handling.
        """
        logger.info("Terminating twins agent...")

        # Clean up resources
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        logger.info("Twins agent terminated successfully")

        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self
        )

    # ========== Model Initialization with Error Handling ==========

    def _initialize_twins_model(self):
        """
        Initialize twins model with error handling.

        This method demonstrates using AgentErrorContext for code blocks.
        """
        logger.info("Initializing twins model...")

        # Create hydraulic solver with error context
        with AgentErrorContext(
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            self._hydraulic_solver = HydraulicSolver()

        if ctx.has_error:
            logger.error(f"Failed to create solver: {ctx.error_message}")
            raise RuntimeError(f"Solver creation failed: {ctx.error_message}")

        # Initialize solver with topology
        if self._topology:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code
            ) as ctx:
                self._hydraulic_solver.initialize(self._topology)

            if ctx.has_error:
                logger.error(f"Failed to initialize solver: {ctx.error_message}")
                raise RuntimeError(f"Solver initialization failed: {ctx.error_message}")

            logger.info("Hydraulic solver initialized with topology")

        # Load solver parameters
        self._load_solver_parameters()

        logger.info("Twins model initialized successfully")

    def _load_solver_parameters(self):
        """Load solver parameters with error handling."""
        with AgentErrorContext(
            ErrorCodes.CONFIGURATION_LOAD_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            solver_params = {
                'time_step': self.properties.get_property('time_step', 60),
                'convergence_tolerance': self.properties.get_property('convergence_tolerance', 1e-6),
                'max_iterations': self.properties.get_property('max_iterations', 100),
            }

        if ctx.has_error:
            logger.warning(f"Failed to load parameters, using defaults: {ctx.error_message}")
            solver_params = {
                'time_step': 60,
                'convergence_tolerance': 1e-6,
                'max_iterations': 100,
            }

        logger.info(f"Solver parameters: {solver_params}")

    # ========== Simulation Execution with Error Handling ==========

    def _execute_twins_simulation(self, step: int) -> List[Dict[str, Any]]:
        """
        Execute twins simulation with comprehensive error handling.

        This method demonstrates using AgentErrorContext for different
        stages of simulation execution.
        """
        logger.info(f"Executing twins simulation for step {step}")

        if not self._hydraulic_solver:
            logger.error("Hydraulic solver not initialized")
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

        # Execute hydraulic solver with error handling
        with AgentErrorContext(
            ErrorCodes.SIMULATION_EXECUTION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            results = self._hydraulic_solver.solve_step(step, boundary_conditions)

        if ctx.has_error:
            logger.error(f"Hydraulic solver failed: {ctx.error_message}")
            return []

        logger.info(f"Hydraulic solver completed for step {step}")

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

        This method may raise exceptions if data is corrupted or missing.
        """
        boundary_conditions = 

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
        Convert solver results to metrics list.

        This method may raise exceptions if results are invalid.
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

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        Handle boundary condition updates with error handling.
        """
        logger.info(f"Updating twins with {len(time_series_list)} boundary conditions")

        for time_series in time_series_list:
            try:
                logger.info(
                    f"Boundary condition update: "
                    f"object={time_series.object_name}, "
                    f"metrics={time_series.metrics_code}, "
                    f"values={len(time_series.time_series)}"
                )

                # Update simulation state
                if self._simulation_state and time_series.object_id:
                    state_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._simulation_state[state_key] = time_series
                    logger.debug(f"Updated simulation state: {state_key}")

            except Exception as e:
                logger.error(
                    f"Error updating boundary condition for {time_series.object_name}: {e}",
                    exc_info=True
                )
                # Continue with other updates


# Example usage
if __name__ == "__main__":
    print("This is an example agent with error handling.")
    print("Use it as a template for your own agents.")
    print("\nKey features:")
    print("  1. @handle_agent_errors decorator for lifecycle methods")
    print("  2. safe_execute() for individual operations")
    print("  3. AgentErrorContext for code blocks")
    print("  4. Comprehensive error logging")
    print("\nSee ERROR_HANDLING_SUMMARY.md for full documentation.")
