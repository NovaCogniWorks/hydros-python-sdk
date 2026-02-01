"""
Example demonstrating logging with SimCoordinationClient.

This example shows how the logging context is automatically set when using
SimCoordinationClient, producing logs that match the Java logback pattern.
"""

import logging
import time
from hydros_agent_sdk import (
    SimCoordinationClient,
    SimCoordinationCallback,
    setup_logging,
    AgentStateManager,
)
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    CommandStatus,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    HydroAgent,
    HydroAgentInstance,
    AgentBizStatus,
    AgentDriveMode,
)

# Configure logging with Hydros formatter
setup_logging(
    level=logging.INFO,
    node_id="DATA",  # This will appear in the first field of each log line
    console=True,
    log_file="logs/coordination-client-example.log"
)

logger = logging.getLogger(__name__)


class ExampleAgentCallback(SimCoordinationCallback):
    """
    Example callback that demonstrates automatic logging context.

    The SimCoordinationClient automatically sets the logging context before
    calling these methods, so all logs will include:
    - node_id: From state_manager
    - task_id: From command.context.biz_scene_instance_id
    - biz_component: From get_component()
    """

    def __init__(self):
        self.agent_instance = None
        self.tick_count = 0

    def get_component(self) -> str:
        """Return the agent component name (used in logging context)."""
        return "ExampleAgent"

    def is_remote_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """Check if an agent instance is remote."""
        return agent_instance.hydros_node_id != "DATA"

    def on_agent_instance_sibling_created(self, response):
        """Handle sibling agent creation."""
        logger.info(f"Sibling agent created: {response.source_agent_instance.agent_code}")

    def on_agent_instance_sibling_status_updated(self, report):
        """Handle sibling agent status update."""
        logger.info(f"Sibling agent status updated: {report.source_agent_instance.agent_code}")

    def on_time_series_calculation(self, request):
        """Handle time series calculation request."""
        logger.info(f"Time series calculation requested")

    def on_time_series_data_update(self, request):
        """Handle time series data update."""
        logger.info(f"Time series data updated")

    def on_sim_task_init(self, request: SimTaskInitRequest):
        """
        Handle task initialization.

        Logging context is automatically set:
        - task_id = request.context.biz_scene_instance_id
        - biz_component = "ExampleAgent"
        - node_id = "DATA"
        """
        logger.info(f"Received SimTaskInitRequest, commandId={request.command_id}")

        # Simulate initialization work
        logger.info("Initializing agent instance")
        logger.info("Loading configuration")
        logger.info("Connecting to data sources")

        # Create agent instance
        self.agent_instance = HydroAgentInstance(
            agent_code="EXAMPLE_AGENT_001",
            agent_type="EXAMPLE",
            agent_name="Example Agent Instance",
            agent_configuration_url="http://example.com/config.yaml",
            agent_id="AGENT_INST_001",
            biz_scene_instance_id=request.context.biz_scene_instance_id,
            hydros_cluster_id="CLUSTER_01",
            hydros_node_id="DATA",
            context=request.context,
            agent_biz_status=AgentBizStatus.ACTIVE,
            drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
        )

        logger.info(f"Agent instance created: {self.agent_instance.agent_code}")

        # Create response
        response = SimTaskInitResponse(
            command_id=f"RESP_{request.command_id}",
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.agent_instance,
            created_agent_instances=[self.agent_instance],
            managed_top_objects={},
        )

        # Log successful response (matching Java format)
        logger.info(
            f"发布协调指令成功,commandId={response.command_id},"
            f"commandType=sim_task_init_response 到MQTT Topic=/hydros/commands/coordination/example"
        )

        return response

    def on_tick(self, request: TickCmdRequest):
        """
        Handle tick command.

        Logging context is automatically set for each tick.
        """
        self.tick_count += 1

        logger.info(f"Received TickCmdRequest, step={request.step}, commandId={request.command_id}")
        logger.info(f"Processing simulation step {request.step}")

        # Simulate some work
        logger.info(f"Calculating water levels for step {request.step}")
        logger.info(f"Updating gate positions for step {request.step}")
        logger.info(f"Publishing results for step {request.step}")

        # Create response
        response = TickCmdResponse(
            command_id=f"RESP_{request.command_id}",
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.agent_instance,
        )

        logger.info(
            f"发布协调指令成功,commandId={response.command_id},"
            f"commandType=tick_cmd_response 到MQTT Topic=/hydros/commands/coordination/example"
        )

        return response

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """
        Handle task termination.

        Logging context is automatically set.
        """
        logger.info(f"Received SimTaskTerminateRequest, commandId={request.command_id}")
        logger.info(f"Reason: {request.reason or 'Normal termination'}")

        # Cleanup
        logger.info("Cleaning up agent instance")
        logger.info("Closing connections")
        logger.info("Releasing resources")

        logger.info(f"Agent instance terminated after {self.tick_count} ticks")

        self.agent_instance = None
        self.tick_count = 0


def simulate_coordination_workflow():
    """
    Simulate a typical coordination workflow to demonstrate logging.

    This simulates what would happen when the agent receives commands from
    the coordinator via MQTT.
    """
    logger.info("=" * 80)
    logger.info("Starting coordination client example")
    logger.info("=" * 80)

    # Create callback
    callback = ExampleAgentCallback()

    # Create state manager and set node ID
    state_manager = AgentStateManager()
    state_manager.set_node_id("DATA")

    # Create simulation context
    context = SimulationContext(
        biz_scene_instance_id="TASK202601301600EXAMPLE001",
        biz_scene_id="SCENE_001",
        biz_scene_name="Example Simulation",
        start_time="2026-01-30T16:00:00",
        end_time="2026-01-30T17:00:00",
        step_resolution=60,
    )

    logger.info(f"Created simulation context: {context.biz_scene_instance_id}")

    # Simulate task init
    logger.info("\n--- Simulating Task Init ---")
    init_request = SimTaskInitRequest(
        command_id="SIMCMD202601301600INIT001",
        context=context,
        agent_list=[
            HydroAgent(
                agent_code="EXAMPLE_AGENT_001",
                agent_type="EXAMPLE",
                agent_name="Example Agent",
                agent_configuration_url="http://example.com/config.yaml",
            )
        ],
    )

    # Manually set logging context (normally done by SimCoordinationClient)
    from hydros_agent_sdk.logging_config import set_task_id, set_biz_component, set_node_id
    set_node_id("DATA")
    set_task_id(context.biz_scene_instance_id)
    set_biz_component(callback.get_component())

    init_response = callback.on_sim_task_init(init_request)

    # Simulate tick commands
    logger.info("\n--- Simulating Tick Commands ---")
    for step in range(1, 4):
        tick_request = TickCmdRequest(
            command_id=f"SIMCMD20260130160{step}TICK00{step}",
            context=context,
            step=step,
        )

        tick_response = callback.on_tick(tick_request)
        time.sleep(0.1)  # Small delay between ticks

    # Simulate termination
    logger.info("\n--- Simulating Task Termination ---")
    terminate_request = SimTaskTerminateRequest(
        command_id="SIMCMD202601301603TERM001",
        context=context,
        reason="Simulation completed successfully",
    )

    callback.on_task_terminate(terminate_request)

    # Clear context
    set_task_id(None)
    set_biz_component(None)

    logger.info("\n" + "=" * 80)
    logger.info("Coordination client example completed")
    logger.info("=" * 80)


def demonstrate_error_logging():
    """Demonstrate error logging with context."""
    from hydros_agent_sdk.logging_config import LogContext

    logger.info("\n--- Demonstrating Error Logging ---")

    with LogContext(
        task_id="TASK_ERROR_DEMO",
        biz_component="ErrorDemoAgent",
        node_id="DATA"
    ):
        try:
            # Simulate an error
            logger.info("Attempting to process invalid data")
            result = 1 / 0
        except Exception as e:
            logger.error(
                f"Error processing command: {e}",
                exc_info=True  # Include full traceback
            )


if __name__ == "__main__":
    print("\nHydros Logging with SimCoordinationClient Example")
    print("=" * 80)
    print("\nThis example demonstrates how logging context is automatically set")
    print("when using SimCoordinationClient. All logs will include:")
    print("  - node_id: From state_manager")
    print("  - task_id: From command.context.biz_scene_instance_id")
    print("  - biz_component: From callback.get_component()")
    print("\nExpected log format:")
    print("NODE_ID|TIMESTAMP|LEVEL|TASK_ID|BIZ_COMPONENT|TYPE|CONTENT|LOGGER|MESSAGE")
    print("=" * 80)
    print()

    # Run the simulation
    simulate_coordination_workflow()

    # Demonstrate error logging
    demonstrate_error_logging()

    print("\n" + "=" * 80)
    print("Check the console output above and logs/coordination-client-example.log")
    print("to see the structured log format in action.")
    print("=" * 80)
