# Outflow Plan Agent Example

This example demonstrates how to implement an outflow plan agent using the `OutflowPlanAgent` base class.

## Overview

The Outflow Plan Agent is an event-driven agent that:
- Responds to `OutflowTimeSeriesRequest` events from the coordinator
- Executes outflow planning logic based on hydro events
- Generates time series data for planned outflows
- Supports topology-based planning for water network objects

## Files

- `outflow_plan_agent.py` - Main agent implementation
- `agent.properties` - Agent configuration (agent_code, agent_type, etc.)
- `env.properties` - MQTT broker configuration

## Configuration

### agent.properties

```properties
agent_code=OUTFLOW_PLAN_AGENT
agent_type=OUTFLOW_PLAN_AGENT
agent_name=Outflow Plan Agent
drive_mode=EVENT_DRIVEN
hydros_cluster_id=default_cluster
hydros_node_id=outflow_plan_node_01
```

### env.properties

```properties
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/default_cluster
```

## Running the Agent

1. Update `env.properties` with your MQTT broker details
2. Run the agent:

```bash
cd examples/agents/outflowplan
python outflow_plan_agent.py
```

## Agent Lifecycle

### 1. Initialization (`on_init`)

When the coordinator sends a `SimTaskInitRequest`:
- Loads agent configuration from URL
- Loads water network topology
- Initializes planning models
- Registers with state manager
- Returns `SimTaskInitResponse`

### 2. Outflow Planning (`on_outflow_time_series`)

When the coordinator sends an `OutflowTimeSeriesRequest`:
- Extracts hydro event information
- Executes outflow planning algorithm
- Generates `ObjectTimeSeries` with planned outflows
- Sends results back to coordinator

### 3. Termination (`on_terminate`)

When the coordinator sends a `SimTaskTerminateRequest`:
- Cleans up planning resources
- Unregisters from state manager
- Returns `SimTaskTerminateResponse`

## Implementing Custom Planning Logic

To implement your own outflow planning logic, override the `_execute_outflow_planning` method:

```python
def _execute_outflow_planning(self, hydro_event) -> List[ObjectTimeSeries]:
    """
    Execute your custom outflow planning logic.

    Args:
        hydro_event: Event that triggered the planning

    Returns:
        List of ObjectTimeSeries containing outflow plans
    """
    # Your planning algorithm here
    # Examples:
    # - Optimization-based planning (MPC, LP, etc.)
    # - Rule-based planning
    # - Machine learning-based forecasting
    # - Hybrid approaches

    outflow_plans = []
    # ... generate plans ...
    return outflow_plans
```

## Error Handling

The agent uses the SDK's error handling mechanism with decorators:

```python
@handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
    # Initialization logic
    pass

@handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
    # Planning logic
    pass
```

Any exceptions are automatically caught and converted to appropriate error responses.

## Integration with Coordinator

The agent integrates with the Hydros coordinator through MQTT:

1. **Incoming**: Coordinator sends `OutflowTimeSeriesRequest` via MQTT
2. **Processing**: Agent executes planning logic
3. **Outgoing**: Agent sends results back via MQTT (if protocol requires response)

## Example Planning Scenarios

### Scenario 1: Reservoir Outflow Planning
- Input: Inflow forecasts, water level targets
- Output: Optimal outflow schedule for next 24 hours

### Scenario 2: Gate Operation Planning
- Input: Downstream flow requirements, upstream conditions
- Output: Gate opening schedule to meet flow targets

### Scenario 3: Multi-Reservoir Coordination
- Input: System-wide constraints, demand forecasts
- Output: Coordinated outflow plans for multiple reservoirs

## Notes

- This is an event-driven agent (not tick-driven)
- The agent does not respond to `TickCmdRequest`
- Planning is triggered by `OutflowTimeSeriesRequest` events
- Results can be sent back to coordinator or published to metrics topic
