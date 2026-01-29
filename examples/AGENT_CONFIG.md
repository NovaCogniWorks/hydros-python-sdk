# Agent Configuration Guide

This guide explains how to configure the Hydro Agent using the `agent.properties` file.

## Configuration File Location

The default configuration file is located at:
```
examples/agent.properties
```

## Configuration Properties

### Required Properties

| Property | Description | Example |
|----------|-------------|---------|
| `agent_code` | Unique code identifying the agent type | `TWINS_SIMULATION_AGENT` |
| `agent_type` | Type classification of the agent | `TWINS_SIMULATION_AGENT` |
| `agent_name` | Human-readable name for the agent | `Twins Simulation Agent` |
| `agent_configuration_url` | URL to the agent's detailed configuration | `http://example.com/config/twins-agent.yaml` |

### Optional Properties

| Property | Description | Default | Valid Values |
|----------|-------------|---------|--------------|
| `drive_mode` | How the agent responds to simulation control | `SIM_TICK_DRIVEN` | `SIM_TICK_DRIVEN`, `EVENT_DRIVEN`, `PROACTIVE` |
| `hydros_cluster_id` | Cluster identifier | `default_cluster` | Any string |
| `hydros_node_id` | Node identifier | `default_central` | Any string |

## Drive Modes Explained

- **SIM_TICK_DRIVEN**: Agent responds to clock ticks and executes simulation steps synchronously
- **EVENT_DRIVEN**: Agent responds to specific events and executes processing logic asynchronously
- **PROACTIVE**: Agent runs in on-site deployment mode, not managed by coordinator

## Example Configuration

```properties
# Hydro Agent Configuration
# This file contains the configuration for the sample agent

# Agent identification
agent_code=TWINS_SIMULATION_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Twins Simulation Agent

# Agent configuration URL
agent_configuration_url=http://example.com/config/twins-agent.yaml

# Agent drive mode (SIM_TICK_DRIVEN, EVENT_DRIVEN, PROACTIVE)
drive_mode=SIM_TICK_DRIVEN

# Cluster and node configuration
hydros_cluster_id=default_cluster
hydros_node_id=default_central
```

## Using Custom Configuration Files

You can specify a custom configuration file path when creating the agent factory:

```python
# Create agent factory with custom config file
agent_factory = MySampleAgentFactory(
    component_name=COMPONENT_NAME,
    node_id=NODE_ID,
    config_file="path/to/your/custom-agent.properties"
)
```

## Configuration Loading Behavior

1. If the configuration file is found, properties are loaded from it
2. If a property is missing, a default value is used
3. If the configuration file is not found, all default values are used
4. Configuration is loaded when each agent instance is created

## Testing Configuration

To verify your configuration file is valid, run:

```bash
python3 examples/test_config.py
```

This will check that all required properties are present and display their values.

## Default Values

If properties are not specified in the configuration file, the following defaults are used:

- `agent_code`: Value of `component_name` parameter
- `agent_type`: Value of `component_name` parameter
- `agent_name`: `"{component_name} Instance"`
- `agent_configuration_url`: `"http://example.com/config.yaml"`
- `drive_mode`: `"SIM_TICK_DRIVEN"`
