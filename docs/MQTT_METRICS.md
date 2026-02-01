# MQTT Metrics Documentation

This document describes the MQTT metrics functionality in the Hydros Python SDK, which enables agents to send metrics data via MQTT for water network objects.

## Overview

The MQTT metrics module (`hydros_agent_sdk.utils.mqtt_metrics`) provides utilities for creating and sending metrics data via MQTT. It matches the Java implementation in `com.hydros.agent.edge.channel.biz.model.MqttMetrics`.

## MqttMetrics Model

The `MqttMetrics` class is a Pydantic model that represents metrics data for water network objects.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | `str` | Source identifier (e.g., agent code like "TWINS_SIMULATION_AGENT") |
| `job_instance_id` | `str` | Job instance ID (typically the `biz_scene_instance_id`) |
| `object_id` | `int` | Water network object ID |
| `object_name` | `str` | Water network object name |
| `step_index` | `int` | Simulation step index |
| `source_timestamp_ms` | `int` | Source timestamp in milliseconds |
| `metrics_code` | `str` | Metrics code (e.g., "water_level", "flow_rate", "gate_opening") |
| `value` | `float` | Metrics value |

### Example

```python
from hydros_agent_sdk.utils import MqttMetrics

metrics = MqttMetrics(
    source_id="TWINS_SIMULATION_AGENT",
    job_instance_id="task_123",
    object_id=1001,
    object_name="Gate_01",
    step_index=10,
    source_timestamp_ms=1706601234567,
    metrics_code="gate_opening",
    value=0.75
)
```

## Utility Functions

### create_mock_metrics()

Creates a mock metrics object for testing or simulation.

**Parameters:**
- `source_id` (str): Source identifier
- `job_instance_id` (str): Job instance ID
- `object_id` (int): Water network object ID
- `object_name` (str): Water network object name
- `step_index` (int): Simulation step index
- `metrics_code` (str): Metrics code
- `value` (float): Metrics value
- `timestamp_ms` (int, optional): Timestamp in milliseconds (defaults to current time)

**Returns:** `MqttMetrics` object

**Example:**
```python
from hydros_agent_sdk.utils import create_mock_metrics

metrics = create_mock_metrics(
    source_id="TWINS_SIMULATION_AGENT",
    job_instance_id="task_123",
    object_id=1001,
    object_name="Gate_01",
    step_index=10,
    metrics_code="gate_opening",
    value=0.75
)
```

### send_metrics()

Sends a single metrics message via MQTT.

**Parameters:**
- `mqtt_client`: MQTT client instance (paho.mqtt.client.Client)
- `topic` (str): MQTT topic to publish to
- `metrics` (MqttMetrics): Metrics object to send
- `qos` (int, optional): Quality of Service level (0, 1, or 2), defaults to 0

**Returns:** `bool` - True if successful, False otherwise

**Example:**
```python
from hydros_agent_sdk.utils import create_mock_metrics, send_metrics

metrics = create_mock_metrics(
    source_id="TWINS_SIMULATION_AGENT",
    job_instance_id="task_123",
    object_id=1001,
    object_name="Gate_01",
    step_index=10,
    metrics_code="gate_opening",
    value=0.75
)

# Send via MQTT
send_metrics(
    mqtt_client=sim_coordination_client.mqtt_client,
    topic="hydros/metrics",
    metrics=metrics,
    qos=0
)
```

### send_metrics_batch()

Sends multiple metrics messages via MQTT.

**Parameters:**
- `mqtt_client`: MQTT client instance
- `topic` (str): MQTT topic to publish to
- `metrics_list` (List[MqttMetrics]): List of metrics objects to send
- `qos` (int, optional): Quality of Service level, defaults to 0

**Returns:** `int` - Number of messages sent successfully

**Example:**
```python
from hydros_agent_sdk.utils import create_mock_metrics, send_metrics_batch

metrics_list = [
    create_mock_metrics(
        source_id="TWINS_SIMULATION_AGENT",
        job_instance_id="task_123",
        object_id=1001,
        object_name="Gate_01",
        step_index=10,
        metrics_code="gate_opening",
        value=0.80
    ),
    create_mock_metrics(
        source_id="TWINS_SIMULATION_AGENT",
        job_instance_id="task_123",
        object_id=1002,
        object_name="Pump_01",
        step_index=10,
        metrics_code="flow_rate",
        value=150.25
    ),
]

# Send batch via MQTT
success_count = send_metrics_batch(
    mqtt_client=sim_coordination_client.mqtt_client,
    topic="hydros/metrics",
    metrics_list=metrics_list,
    qos=0
)
print(f"Sent {success_count}/{len(metrics_list)} metrics")
```

## Integration with Agents

### Sending Metrics in on_tick()

The most common use case is sending metrics during simulation ticks. Here's how to integrate metrics sending in your agent's `on_tick()` method:

```python
from hydros_agent_sdk.utils import create_mock_metrics, send_metrics

class MySampleHydroAgent(HydroAgent):
    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """Handle simulation tick and send metrics."""
        logger.info(f"Processing step {request.step}")

        # Create metrics for this simulation step
        metrics = create_mock_metrics(
            source_id=self.config['agent_code'],
            job_instance_id=self.biz_scene_instance_id,
            object_id=1001,
            object_name="Gate_01",
            step_index=request.step,
            metrics_code="gate_opening",
            value=0.75 + (request.step % 10) * 0.01
        )

        # Send metrics via MQTT
        metrics_topic = f"{self.sim_coordination_client.topic}/metrics"
        send_metrics(
            mqtt_client=self.sim_coordination_client.mqtt_client,
            topic=metrics_topic,
            metrics=metrics,
            qos=0
        )

        logger.info(f"Sent metrics: {metrics.metrics_code}={metrics.value}")

        # Create and return response
        response = TickCmdResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.hydro_agent_instance,
            broadcast=False
        )

        return response
```

### Sending Multiple Metrics

For agents managing multiple water network objects, you can send batch metrics:

```python
def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
    """Handle simulation tick and send metrics for multiple objects."""

    # Create metrics for multiple objects
    metrics_list = []

    for obj in self.managed_objects:
        metrics = create_mock_metrics(
            source_id=self.config['agent_code'],
            job_instance_id=self.biz_scene_instance_id,
            object_id=obj.object_id,
            object_name=obj.object_name,
            step_index=request.step,
            metrics_code=obj.metrics_code,
            value=obj.get_current_value()
        )
        metrics_list.append(metrics)

    # Send all metrics in batch
    metrics_topic = f"{self.sim_coordination_client.topic}/metrics"
    success_count = send_metrics_batch(
        mqtt_client=self.sim_coordination_client.mqtt_client,
        topic=metrics_topic,
        metrics_list=metrics_list,
        qos=0
    )

    logger.info(f"Sent {success_count}/{len(metrics_list)} metrics")

    # ... rest of tick handling
```

## JSON Format

Metrics are serialized to JSON before being sent via MQTT. The JSON format matches the Java implementation:

```json
{
  "source_id": "TWINS_SIMULATION_AGENT",
  "job_instance_id": "task_123",
  "object_id": 1001,
  "object_name": "Gate_01",
  "step_index": 10,
  "source_timestamp_ms": 1706601234567,
  "metrics_code": "gate_opening",
  "value": 0.75
}
```

## Common Metrics Codes

Common metrics codes used in water network simulations:

| Metrics Code | Description | Typical Objects |
|--------------|-------------|-----------------|
| `gate_opening` | Gate opening percentage (0.0-1.0) | Gates, Sluices |
| `water_level` | Water level in meters | Reservoirs, Channels |
| `flow_rate` | Flow rate in m³/s | Pumps, Pipes, Gates |
| `pump_status` | Pump on/off status (0 or 1) | Pumps |
| `pressure` | Water pressure in kPa | Pipes, Junctions |
| `velocity` | Water velocity in m/s | Pipes, Channels |

## Examples

See the following example files for complete demonstrations:

- **`examples/mqtt_metrics_example.py`**: Comprehensive examples of creating and sending metrics
- **`examples/agent_example.py`**: Integration with agent's `on_tick()` method (line 392)

## Testing

The module includes comprehensive unit tests in `tests/test_mqtt_metrics.py`:

```bash
# Run tests
python tests/test_mqtt_metrics.py

# Or with pytest
pytest tests/test_mqtt_metrics.py -v
```

## Best Practices

1. **Use Descriptive Metrics Codes**: Choose clear, standardized metrics codes that describe what is being measured.

2. **Send Metrics at Appropriate Intervals**: Typically send metrics once per simulation step in `on_tick()`.

3. **Batch Multiple Metrics**: When sending metrics for multiple objects, use `send_metrics_batch()` for better performance.

4. **Include Timestamp**: Always include accurate timestamps to enable time-series analysis.

5. **Handle Errors Gracefully**: Check return values from `send_metrics()` and log failures appropriately.

6. **Use Appropriate QoS**:
   - QoS 0: Fire and forget (fastest, no guarantee)
   - QoS 1: At least once delivery (recommended for metrics)
   - QoS 2: Exactly once delivery (slowest, highest guarantee)

7. **Topic Naming Convention**: Use a consistent topic naming pattern, e.g., `{base_topic}/metrics` or `{base_topic}/metrics/{agent_code}`.

## Troubleshooting

### Metrics Not Being Sent

1. **Check MQTT Connection**: Ensure the MQTT client is connected before sending metrics.
2. **Verify Topic**: Confirm the topic name is correct and the broker allows publishing to it.
3. **Check Logs**: Enable debug logging to see detailed error messages.

### Performance Issues

1. **Use Batch Sending**: For multiple metrics, use `send_metrics_batch()` instead of multiple `send_metrics()` calls.
2. **Reduce QoS**: If delivery guarantees aren't critical, use QoS 0 for better performance.
3. **Limit Metrics Frequency**: Avoid sending metrics too frequently; once per simulation step is usually sufficient.

## API Reference

### MqttMetrics

```python
class MqttMetrics(BaseModel):
    source_id: str
    job_instance_id: str
    object_id: int
    object_name: str
    step_index: int
    source_timestamp_ms: int
    metrics_code: str
    value: float
```

### Functions

```python
def create_mock_metrics(
    source_id: str,
    job_instance_id: str,
    object_id: int,
    object_name: str,
    step_index: int,
    metrics_code: str,
    value: float,
    timestamp_ms: Optional[int] = None
) -> MqttMetrics

def send_metrics(
    mqtt_client,
    topic: str,
    metrics: MqttMetrics,
    qos: int = 0
) -> bool

def send_metrics_batch(
    mqtt_client,
    topic: str,
    metrics_list: List[MqttMetrics],
    qos: int = 0
) -> int
```

## See Also

- [Agent Configuration](AGENT_CONFIG.md)
- [Hydro Object Utils](HYDRO_OBJECT_UTILS.md)
- [Logging Configuration](LOGGING.md)
