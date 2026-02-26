"""
Example demonstrating error handling in Hydros agents.

This example shows how to use the error handling decorators and utilities
to properly handle errors and return error responses to the coordinator.
"""

import logging
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from hydros_agent_sdk import (
    setup_logging,
    TwinsSimulationAgent,
    ErrorCodes,
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
    create_error_response,
)
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import CommandStatus
from hydros_agent_sdk.utils import HydroObjectUtilsV2
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics

# Setup logging
setup_logging(
    level=logging.INFO,
    hydros_cluster_id="test_cluster",
    hydros_node_id="test_node",
    console=True
)

logger = logging.getLogger(__name__)


class ErrorHandlingExampleAgent(TwinsSimulationAgent):
    """
    Example agent demonstrating error handling patterns.

    This agent shows three ways to handle errors:
    1. Using @handle_agent_errors decorator (recommended)
    2. Using safe_execute() utility function
    3. Using AgentErrorContext context manager
    """

    # ========== Method 1: Using @handle_agent_errors decorator ==========

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize agent with automatic error handling.

        The @handle_agent_errors decorator will:
        1. Catch any exception
        2. Format error message with agent name and details
        3. Create SimTaskInitResponse with FAILED status
        4. Log the error
        5. Return error response to coordinator
        """
        logger.info("Initializing agent with error handling...")

        # Load configuration (may raise exception)
        self.load_agent_configuration(request)

        # Load topology (may raise exception)
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        if topology_url:
            # This will raise exception if URL is invalid or file not found
            self._topology = HydroObjectUtilsV2.build_waterway_topology(topology_url)

        # Register with state manager
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        # Initialize twins model (may raise exception)
        self._initialize_twins_model()

        # Return success response
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={}
        )

    # ========== Method 2: Using safe_execute() utility ==========

    def _initialize_twins_model(self):
        """
        Initialize twins model with manual error handling using safe_execute().

        This method shows how to use safe_execute() for fine-grained error handling
        when you need more control than the decorator provides.
        """
        logger.info("Initializing twins model...")

        # Example: Load solver with error handling
        success, solver, error_msg = safe_execute(
            self._create_solver,
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            self.agent_code
        )

        if not success:
            logger.error(f"Failed to create solver: {error_msg}")
            # You can handle the error here or raise it
            raise RuntimeError(f"Solver initialization failed: {error_msg}")

        self._solver = solver
        logger.info("Twins model initialized successfully")

    def _create_solver(self):
        """Create solver instance (may raise exception)."""
        # Simulate solver creation
        logger.info("Creating solver...")
        # In real implementation, this might raise exceptions
        return {"type": "hydraulic_solver", "version": "1.0"}

    # ========== Method 3: Using AgentErrorContext context manager ==========

    @handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
    def _execute_twins_simulation(self, step: int):
        """
        Execute simulation with context manager error handling.

        This method shows how to use AgentErrorContext for handling errors
        in specific code blocks.
        """
        logger.info(f"Executing simulation step {step}...")

        # Use context manager for boundary condition collection
        with AgentErrorContext(
            ErrorCodes.BOUNDARY_CONDITION_ERROR,
            agent_name=self.agent_code
        ) as ctx:
            boundary_conditions = self._collect_boundary_conditions(step)

        if ctx.has_error:
            logger.error(f"Failed to collect boundary conditions: {ctx.error_message}")
            # Return empty results or raise exception
            return []

        # Use context manager for simulation execution
        with AgentErrorContext(
            ErrorCodes.SIMULATION_EXECUTION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            results = self._run_simulation(step, boundary_conditions)

        if ctx.has_error:
            logger.error(f"Failed to run simulation: {ctx.error_message}")
            return []

        # Convert results to metrics
        metrics_list = [
            create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=object_id,
                object_name=f"Object_{object_id}",
                step_index=step,
                metrics_code=metrics_code,
                value=value
            )
            for object_id, values in results.items()
            for metrics_code, value in values.items()
        ]

        return metrics_list

    def _run_simulation(self, step: int, boundary_conditions: dict):
        """Run simulation (may raise exception)."""
        logger.info(f"Running simulation for step {step}...")
        # Simulate calculation
        return {
            1001: {"water_level": 5.0 + step * 0.1, "flow": 10.0},
            1002: {"water_level": 4.5 + step * 0.1, "flow": 8.0},
        }

    # ========== Method 4: Manual error handling with create_error_response ==========

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate agent with manual error handling.

        This method shows how to manually create error responses when you need
        full control over the error handling logic.
        """
        try:
            logger.info("Terminating agent...")

            # Clean up resources
            self.state_manager.terminate_task(self.context)
            self.state_manager.remove_local_agent(self)

            # Return success response
            return SimTaskTerminateResponse(
                command_id=request.command_id,
                context=request.context,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self
            )

        except Exception as e:
            logger.error(f"Error during termination: {e}", exc_info=True)

            # Manually create error response
            return create_error_response(
                SimTaskTerminateResponse,
                ErrorCodes.AGENT_TERMINATE_FAILURE,
                self.agent_code,
                str(e),
                command_id=request.command_id,
                context=request.context,
                source_agent_instance=self
            )


def demonstrate_error_codes():
    """Demonstrate error code usage."""
    print("\n" + "="*70)
    print("Error Code Examples")
    print("="*70 + "\n")

    # Example 1: Format error message
    error_msg = ErrorCodes.SYSTEM_ERROR.format_message("NetworkError", "Connection timeout")
    print(f"1. System Error:\n   {error_msg}\n")

    # Example 2: Configuration error
    error_msg = ErrorCodes.CONFIGURATION_LOAD_FAILURE.format_message(
        "agent.properties",
        "File not found"
    )
    print(f"2. Configuration Error:\n   {error_msg}\n")

    # Example 3: Agent initialization error
    error_msg = ErrorCodes.AGENT_INIT_FAILURE.format_message(
        "MyAgent",
        "Failed to load topology"
    )
    print(f"3. Agent Init Error:\n   {error_msg}\n")

    # Example 4: Topology load error
    error_msg = ErrorCodes.TOPOLOGY_LOAD_FAILURE.format_message(
        "http://example.com/topology.yaml",
        "HTTP 404 Not Found"
    )
    print(f"4. Topology Load Error:\n   {error_msg}\n")

    # Example 5: Simulation execution error
    error_msg = ErrorCodes.SIMULATION_EXECUTION_FAILURE.format_message(
        "TwinsAgent",
        "Division by zero in hydraulic calculation"
    )
    print(f"5. Simulation Error:\n   {error_msg}\n")


def demonstrate_error_handling_patterns():
    """Demonstrate different error handling patterns."""
    print("\n" + "="*70)
    print("Error Handling Patterns")
    print("="*70 + "\n")

    # Pattern 1: Using decorator
    print("Pattern 1: @handle_agent_errors decorator")
    print("  - Automatically catches exceptions")
    print("  - Converts to error response")
    print("  - Logs error with traceback")
    print("  - Best for: Agent lifecycle methods (on_init, on_tick, etc.)\n")

    # Pattern 2: Using safe_execute
    print("Pattern 2: safe_execute() utility")
    print("  - Returns (success, result, error_message) tuple")
    print("  - Allows fine-grained error handling")
    print("  - Best for: Individual operations that might fail\n")

    # Pattern 3: Using context manager
    print("Pattern 3: AgentErrorContext context manager")
    print("  - Catches exceptions in code block")
    print("  - Provides has_error and error_message attributes")
    print("  - Best for: Specific code blocks with error handling\n")

    # Pattern 4: Manual error handling
    print("Pattern 4: Manual with create_error_response()")
    print("  - Full control over error handling")
    print("  - Manually create error responses")
    print("  - Best for: Complex error handling logic\n")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("Hydros Agent SDK - Error Handling Example")
    print("="*70)

    # Demonstrate error codes
    demonstrate_error_codes()

    # Demonstrate error handling patterns
    demonstrate_error_handling_patterns()

    print("\n" + "="*70)
    print("Usage in Your Agent")
    print("="*70 + "\n")

    print("""
# 1. Import error handling utilities
from hydros_agent_sdk import (
    ErrorCodes,
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
    create_error_response,
)

# 2. Use decorator for lifecycle methods
class MyAgent(TwinsSimulationAgent):
    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request):
        # Your initialization logic
        # Any exception will be caught and converted to error response
        pass

    @handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
    def on_tick(self, request):
        # Your tick logic
        pass

# 3. Use safe_execute for individual operations
success, result, error_msg = safe_execute(
    load_topology,
    ErrorCodes.TOPOLOGY_LOAD_FAILURE,
    "MyAgent",
    topology_url
)

if not success:
    logger.error(f"Failed: {error_msg}")
    return create_error_response(...)

# 4. Use context manager for code blocks
with AgentErrorContext(ErrorCodes.SIMULATION_EXECUTION_FAILURE, "MyAgent") as ctx:
    results = run_simulation()

if ctx.has_error:
    logger.error(f"Failed: {ctx.error_message}")
    return create_error_response(...)
""")

    print("\n" + "="*70)
    print("See error_codes.py and error_handling.py for full API")
    print("="*70 + "\n")
