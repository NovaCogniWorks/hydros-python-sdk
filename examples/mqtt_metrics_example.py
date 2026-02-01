"""
Example demonstrating MQTT metrics sending functionality.

This example shows how to:
1. Create MqttMetrics objects
2. Send individual metrics via MQTT
3. Send batch metrics via MQTT
4. Use mock metrics for testing

Usage:
    python examples/mqtt_metrics_example.py
"""

import time
import logging
from hydros_agent_sdk.utils import (
    MqttMetrics,
    send_metrics,
    send_metrics_batch,
    create_mock_metrics
)
from hydros_agent_sdk import setup_logging

# Configure logging
setup_logging(
    level=logging.INFO,
    node_id="DATA",
    console=True
)
logger = logging.getLogger(__name__)


def example_create_metrics():
    """Example: Create metrics objects."""
    logger.info("=" * 70)
    logger.info("Example 1: Creating MqttMetrics objects")
    logger.info("=" * 70)

    # Method 1: Create using Pydantic model directly
    metrics1 = MqttMetrics(
        source_id="TWINS_SIMULATION_AGENT",
        job_instance_id="task_123",
        object_id=1001,
        object_name="Gate_01",
        step_index=10,
        source_timestamp_ms=int(time.time() * 1000),
        metrics_code="gate_opening",
        value=0.75
    )
    logger.info(f"Created metrics (direct): {metrics1.model_dump_json(indent=2)}")

    # Method 2: Create using helper function
    metrics2 = create_mock_metrics(
        source_id="TWINS_SIMULATION_AGENT",
        job_instance_id="task_123",
        object_id=1002,
        object_name="Pump_01",
        step_index=10,
        metrics_code="flow_rate",
        value=125.5
    )
    logger.info(f"Created metrics (helper): {metrics2.model_dump_json(indent=2)}")

    return metrics1, metrics2


def example_send_single_metrics():
    """Example: Send a single metrics message."""
    logger.info("=" * 70)
    logger.info("Example 2: Sending single metrics (mock)")
    logger.info("=" * 70)

    # Create mock metrics
    metrics = create_mock_metrics(
        source_id="TWINS_SIMULATION_AGENT",
        job_instance_id="task_456",
        object_id=2001,
        object_name="Reservoir_01",
        step_index=5,
        metrics_code="water_level",
        value=12.34
    )

    logger.info(f"Mock metrics created: {metrics.metrics_code}={metrics.value}")
    logger.info("Note: To actually send, you need an MQTT client connection")
    logger.info("Example usage:")
    logger.info("  send_metrics(mqtt_client, 'hydros/metrics', metrics, qos=0)")

    return metrics


def example_send_batch_metrics():
    """Example: Send multiple metrics messages."""
    logger.info("=" * 70)
    logger.info("Example 3: Sending batch metrics (mock)")
    logger.info("=" * 70)

    # Create multiple metrics for different objects
    metrics_list = [
        create_mock_metrics(
            source_id="TWINS_SIMULATION_AGENT",
            job_instance_id="task_789",
            object_id=3001,
            object_name="Gate_01",
            step_index=15,
            metrics_code="gate_opening",
            value=0.80
        ),
        create_mock_metrics(
            source_id="TWINS_SIMULATION_AGENT",
            job_instance_id="task_789",
            object_id=3002,
            object_name="Gate_02",
            step_index=15,
            metrics_code="gate_opening",
            value=0.65
        ),
        create_mock_metrics(
            source_id="TWINS_SIMULATION_AGENT",
            job_instance_id="task_789",
            object_id=3003,
            object_name="Pump_01",
            step_index=15,
            metrics_code="flow_rate",
            value=150.25
        ),
    ]

    logger.info(f"Created {len(metrics_list)} metrics objects:")
    for m in metrics_list:
        logger.info(f"  - {m.object_name}: {m.metrics_code}={m.value}")

    logger.info("Note: To actually send, you need an MQTT client connection")
    logger.info("Example usage:")
    logger.info("  send_metrics_batch(mqtt_client, 'hydros/metrics', metrics_list, qos=0)")

    return metrics_list


def example_simulation_step():
    """Example: Simulate sending metrics during a simulation step."""
    logger.info("=" * 70)
    logger.info("Example 4: Simulating metrics during simulation steps")
    logger.info("=" * 70)

    job_instance_id = "simulation_task_001"
    source_id = "TWINS_SIMULATION_AGENT"

    # Simulate 5 simulation steps
    for step in range(1, 6):
        logger.info(f"\n--- Step {step} ---")

        # Create metrics for multiple objects at this step
        metrics_list = [
            create_mock_metrics(
                source_id=source_id,
                job_instance_id=job_instance_id,
                object_id=4001,
                object_name="Gate_01",
                step_index=step,
                metrics_code="gate_opening",
                value=0.5 + step * 0.05  # Gradually opening
            ),
            create_mock_metrics(
                source_id=source_id,
                job_instance_id=job_instance_id,
                object_id=4002,
                object_name="Reservoir_01",
                step_index=step,
                metrics_code="water_level",
                value=10.0 + step * 0.2  # Water level rising
            ),
            create_mock_metrics(
                source_id=source_id,
                job_instance_id=job_instance_id,
                object_id=4003,
                object_name="Pump_01",
                step_index=step,
                metrics_code="flow_rate",
                value=100.0 + step * 10.0  # Flow increasing
            ),
        ]

        for m in metrics_list:
            logger.info(f"  {m.object_name}: {m.metrics_code}={m.value:.2f}")

        # In real usage, you would send these via MQTT:
        # send_metrics_batch(mqtt_client, 'hydros/metrics', metrics_list)

        time.sleep(0.5)  # Simulate time between steps


def example_json_serialization():
    """Example: JSON serialization of metrics."""
    logger.info("=" * 70)
    logger.info("Example 5: JSON serialization")
    logger.info("=" * 70)

    metrics = create_mock_metrics(
        source_id="TWINS_SIMULATION_AGENT",
        job_instance_id="task_999",
        object_id=5001,
        object_name="Gate_Main",
        step_index=100,
        metrics_code="gate_opening",
        value=0.95
    )

    # Serialize to JSON string
    json_str = metrics.model_dump_json()
    logger.info(f"JSON string:\n{json_str}")

    # Serialize to dict
    json_dict = metrics.model_dump()
    logger.info(f"\nJSON dict:\n{json_dict}")

    # Pretty print
    json_pretty = metrics.model_dump_json(indent=2)
    logger.info(f"\nJSON pretty:\n{json_pretty}")


def main():
    """Run all examples."""
    logger.info("MQTT Metrics Utility Examples")
    logger.info("=" * 70)

    try:
        # Run examples
        example_create_metrics()
        print()

        example_send_single_metrics()
        print()

        example_send_batch_metrics()
        print()

        example_simulation_step()
        print()

        example_json_serialization()
        print()

        logger.info("=" * 70)
        logger.info("All examples completed successfully!")
        logger.info("=" * 70)
        logger.info("\nIntegration with agent:")
        logger.info("  See examples/agent_example.py on_tick() method for usage")
        logger.info("  The agent sends mock metrics during each simulation tick")

    except Exception as e:
        logger.error(f"Error running examples: {e}", exc_info=True)


if __name__ == "__main__":
    main()
