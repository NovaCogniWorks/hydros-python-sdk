"""
Example demonstrating the Hydros logging format.

This example shows how to configure and use the custom logging format
that matches the Java logback pattern used in hydros-data.
"""

import logging
from hydros_agent_sdk.logging_config import (
    setup_logging,
    LogContext,
    set_task_id,
    set_biz_component,
    set_node_id,
)

# Configure logging with Hydros formatter
setup_logging(
    level=logging.INFO,
    node_id="DATA",  # Your hydros_node_id
    console=True,
    log_file="logs/hydros-agent.log"  # Optional: log to file
)

logger = logging.getLogger(__name__)


def example_basic_logging():
    """Example 1: Basic logging without context."""
    print("\n=== Example 1: Basic logging (no context) ===")
    logger.info("This is a basic log message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")


def example_with_context_manager():
    """Example 2: Using LogContext context manager."""
    print("\n=== Example 2: Using LogContext context manager ===")

    with LogContext(
        task_id="TASK202601282328VG3IE7H3CA0F",
        biz_component="SimCoordinator"
    ):
        logger.info("SimCoordinator 发布协调指令成功,commandId=SIMCMD202601282329SHOFBOURP4DE,commandType=tick_cmd_request 到MQTT Topic=/hydros/commands/coordination/weijiahao")
        logger.info("Processing tick command")

    # Context is cleared after exiting the with block
    logger.info("Context cleared after with block")


def example_with_setter_functions():
    """Example 3: Using setter functions."""
    print("\n=== Example 3: Using setter functions ===")

    # Set context using setter functions
    set_node_id("AGENT_NODE_01")
    set_task_id("TASK202601301234ABCDEFGH")
    set_biz_component("WaterLevelAgent")

    logger.info("Agent initialized successfully")
    logger.info("Starting simulation task")

    # Update context
    set_task_id("TASK202601301235IJKLMNOP")
    logger.info("Switched to new task")


def example_nested_contexts():
    """Example 4: Nested contexts."""
    print("\n=== Example 4: Nested contexts ===")

    with LogContext(task_id="TASK_OUTER", biz_component="OuterAgent"):
        logger.info("Outer context")

        with LogContext(task_id="TASK_INNER", biz_component="InnerAgent"):
            logger.info("Inner context (overrides outer)")

        logger.info("Back to outer context")


def example_simulation_workflow():
    """Example 5: Simulating a typical agent workflow."""
    print("\n=== Example 5: Simulating agent workflow ===")

    # Agent initialization
    set_node_id("DATA")
    set_biz_component("FloodControlAgent")
    logger.info("Agent service started")

    # Receive task init request
    task_id = "TASK202601301500FLOOD001"
    set_task_id(task_id)
    logger.info(f"Received SimTaskInitRequest, taskId={task_id}")

    # Process initialization
    logger.info("Initializing agent instance")
    logger.info("Loading water network topology")
    logger.info("Agent instance initialized successfully")

    # Send response
    logger.info(f"发布协调指令成功,commandId=SIMCMD202601301501RESP001,commandType=sim_task_init_response 到MQTT Topic=/hydros/commands/coordination/cluster01")

    # Process tick commands
    for tick in range(1, 4):
        with LogContext(task_id=task_id):
            logger.info(f"Received TickCmdRequest, tick={tick}")
            logger.info(f"Processing simulation step {tick}")
            logger.info(f"发布协调指令成功,commandId=SIMCMD20260130150{tick}TICK00{tick},commandType=tick_cmd_response 到MQTT Topic=/hydros/commands/coordination/cluster01")

    # Terminate
    with LogContext(task_id=task_id):
        logger.info("Received SimTaskTerminateRequest")
        logger.info("Cleaning up agent instance")
        logger.info("Agent instance terminated successfully")


def example_with_exception():
    """Example 6: Logging with exception."""
    print("\n=== Example 6: Logging with exception ===")

    with LogContext(task_id="TASK_ERROR", biz_component="ErrorAgent"):
        try:
            # Simulate an error
            result = 1 / 0
        except Exception as e:
            logger.error(f"Error processing command: {e}", exc_info=True)


if __name__ == "__main__":
    print("Hydros Logging Format Examples")
    print("=" * 80)
    print("\nExpected format:")
    print("NODE_ID|TIMESTAMP|LEVEL|TASK_ID|BIZ_COMPONENT|TYPE|CONTENT|LOGGER|MESSAGE")
    print("=" * 80)

    example_basic_logging()
    example_with_context_manager()
    example_with_setter_functions()
    example_nested_contexts()
    example_simulation_workflow()
    example_with_exception()

    print("\n" + "=" * 80)
    print("Examples completed!")
