# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Hydros Agent SDK** is a Python SDK for building simulation agents in the Hydros ecosystem. It provides:
- MQTT-based coordination between distributed simulation agents
- Protocol definitions matching the Java Hydros coordinator
- Base classes for implementing different types of simulation agents
- Utilities for water network topology modeling and metrics reporting
- **Comprehensive error handling mechanism** with automatic exception-to-response conversion

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .
pip install pyyaml  # Required for agent configuration loading
```

### Testing
```bash
# Run all tests (if pytest is installed)
pytest

# Run specific test file
pytest tests/test_agent_config.py

# Note: Test infrastructure is minimal - tests directory exists but may be empty
```

### Building and Deployment
```bash
# Build package
python -m build

# Deploy to Aliyun registry (requires credentials)
./deploy.sh
```

### Running Examples
```bash
# Run the main agent example
cd examples
python agent_example.py

# Run specialized agent examples
cd examples/agents/twins
python twins_agent.py

cd examples/agents/ontology
python ontology_agent.py
```

## Architecture

### Core Components

**SimCoordinationClient** (`coordination_client.py`)
- High-level MQTT client that encapsulates all coordination logic
- Handles message routing, filtering, and retry logic
- Manages connection lifecycle and outgoing message queue
- Routes incoming commands to callback methods

**BaseHydroAgent** (`base_agent.py`)
- Abstract base class for all agent implementations
- Inherits from `HydroAgentInstance` (Pydantic model)
- Provides lifecycle methods: `on_init()`, `on_tick()`, `on_terminate()`
- Includes `load_agent_configuration()` for loading YAML configs from URLs
- Non-Pydantic attributes: `sim_coordination_client`, `state_manager`, `properties`

**Specialized Agent Types** (`agents/`)
- `TickableAgent`: Base for tick-driven simulation agents
- `OntologySimulationAgent`: Ontology-based simulation
- `TwinsSimulationAgent`: Digital twins high-fidelity simulation
- `ModelCalculationAgent`: Event-driven model calculation
- `CentralSchedulingAgent`: Central scheduling with MPC optimization

**Protocol Models** (`protocol/`)
- `models.py`: Core data models (SimulationContext, HydroAgentInstance, etc.)
- `commands.py`: Command/response definitions (SimTaskInitRequest, TickCmdRequest, etc.)
- `events.py`: Event definitions (TimeSeriesDataChangedEvent, etc.)
- All models use Pydantic for validation and serialization

**State Management** (`state_manager.py`)
- Tracks active simulation contexts and agent instances
- Distinguishes between local and remote agents
- Manages task lifecycle (init, active, terminate)

**Configuration** (`agent_config.py`)
- `AgentConfigLoader`: Loads YAML configuration from URLs or files
- `AgentConfiguration`: Pydantic model for agent config structure
- Supports nested properties (waterway, output_config, mqtt_broker, etc.)

**Utilities** (`utils/`)
- `HydroObjectUtilsV2`: Load and parse water network topology from YAML
- `MqttMetrics`: Send metrics data via MQTT
- `WaterwayTopology`: Represents water network structure

**Logging** (`logging_config.py`)
- Custom formatter matching Java logback pattern
- Format: `NODE_ID|TIMESTAMP|LEVEL|TASK_ID|BIZ_COMPONENT|TYPE|CONTENT|LOGGER|MESSAGE`
- Context variables for MDC-like functionality (task_id, biz_component, node_id)

### Agent Lifecycle

1. **Initialization**: Coordinator sends `SimTaskInitRequest`
   - Agent factory creates new agent instance
   - Agent calls `load_agent_configuration(request)` to load YAML config
   - Agent loads topology, initializes state
   - Agent registers with state manager
   - Agent returns `SimTaskInitResponse`

2. **Execution**: Coordinator sends `TickCmdRequest` for each simulation step
   - Agent executes simulation logic
   - Agent sends metrics via MQTT
   - Agent returns `TickCmdResponse`

3. **Termination**: Coordinator sends `SimTaskTerminateRequest`
   - Agent cleans up resources
   - Agent unregisters from state manager
   - Agent returns `SimTaskTerminateResponse`

### Configuration Files

**agent.properties** (Agent metadata)
```properties
agent_code=TWINS_SIMULATION_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Twins Simulation Agent
drive_mode=SIM_TICK_DRIVEN
hydros_cluster_id=default_cluster
hydros_node_id=default_node
```

**env.properties** (MQTT connection)
```properties
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/cluster_name
```

**Agent Configuration YAML** (Loaded from URL in SimTaskInitRequest)
- Contains business logic configuration
- Includes topology URLs, time series configs, output settings
- Loaded via `AgentConfigLoader.from_url()`
- Accessed via `self.properties.get_property(key)`

### Multi-Agent Deployment

The SDK supports running multiple agent instances in separate directories:
```
agent001/
  ├── agent.properties  (agent_code=AGENT_001)
  ├── env.properties
  └── run.py
agent002/
  ├── agent.properties  (agent_code=AGENT_002)
  ├── env.properties
  └── run.py
```

Each agent instance:
- Has its own configuration files
- Connects to the same MQTT broker
- Handles multiple simulation tasks (contexts) independently
- Uses factory pattern to create agent instances per task

### Key Design Patterns

**Factory Pattern**: `AgentFactory` creates agent instances for each simulation task
- Each `SimulationContext` gets its own agent instance
- Instances are created on task init, destroyed on terminate
- Callback routes messages to correct agent instance by context ID

**Callback Pattern**: `SimCoordinationCallback` provides business logic
- `on_sim_task_init()`: Handle task initialization
- `on_tick()`: Handle simulation tick
- `on_task_terminate()`: Handle task termination
- `on_time_series_data_update()`: Handle boundary condition updates

**Inheritance Hierarchy**:
```
HydroBaseModel (Pydantic)
  ↓
HydroAgent (agent definition)
  ↓
HydroAgentInstance (running instance)
  ↓
BaseHydroAgent (behavioral base class)
  ↓
TickableAgent (tick-driven base)
  ↓
[OntologySimulationAgent, TwinsSimulationAgent, etc.]
```

## Important Implementation Notes

### Pydantic and Dynamic Attributes

BaseHydroAgent uses Pydantic but has non-serialized attributes:
- `sim_coordination_client`, `state_manager`, `properties` are set via `object.__setattr__()`
- These are marked with `Field(exclude=True)` to prevent Pydantic validation
- Use `model_config = ConfigDict(extra='allow', arbitrary_types_allowed=True)`

### Logging Context

Logging context is automatically set by `SimCoordinationClient`:
- `task_id` = `context.biz_scene_instance_id`
- `biz_component` = agent code
- `node_id` = from state manager
- All logs in callbacks include this context automatically

### MQTT Message Flow

**Incoming**: MQTT → `_on_message()` → filter → route to handler → callback
**Outgoing**: `enqueue()` → queue thread → `_should_send()` → `_send_with_retry()` → MQTT

Only responses and reports from local agents are sent (not requests).

### Agent Configuration Loading

Agent configuration is loaded in two stages:
1. **agent.properties**: Loaded in agent constructor (agent_code, agent_type, etc.)
2. **YAML config**: Loaded in `on_init()` via `load_agent_configuration(request)`
   - Extracts `agent_configuration_url` from `SimTaskInitRequest.agent_list`
   - Validates `agent_code` matches
   - Sets `self.properties` with typed accessors

### Time Series Data

Time series data (boundary conditions) flow:
1. Coordinator sends `TimeSeriesDataUpdateRequest`
2. Agent caches data in `_time_series_cache`
3. Agent calls `on_boundary_condition_update()` for subclass handling
4. Agent can query cached values via `get_time_series_value(object_id, metrics_code, step)`

## Common Patterns

### Creating a New Agent Type

```python
from hydros_agent_sdk.agents import TickableAgent

class MyCustomAgent(TickableAgent):
    def on_init(self, request):
        # Load configuration
        self.load_agent_configuration(request)

        # Load topology if needed
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        if topology_url:
            from hydros_agent_sdk.utils import HydroObjectUtilsV2
            self.topology = HydroObjectUtilsV2.build_waterway_topology(topology_url)

        # Register with state manager
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        # Return response
        return SimTaskInitResponse(...)

    def on_tick_simulation(self, request):
        # Your simulation logic here
        metrics_list = []
        # ... compute metrics ...
        return metrics_list

    def on_terminate(self, request):
        # Clean up
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)
        return SimTaskTerminateResponse(...)
```

### Sending Metrics

```python
from hydros_agent_sdk.utils import create_mock_metrics, send_metrics

metrics = create_mock_metrics(
    source_id=self.agent_code,
    job_instance_id=self.biz_scene_instance_id,
    object_id=1001,
    object_name="Gate_01",
    step_index=current_step,
    metrics_code="gate_opening",
    value=0.75
)

metrics_topic = f"{self.sim_coordination_client.topic}/metrics"
send_metrics(
    mqtt_client=self.sim_coordination_client.mqtt_client,
    topic=metrics_topic,
    metrics=metrics,
    qos=0
)
```

### Using Logging Context

```python
from hydros_agent_sdk.logging_config import set_task_id, set_biz_component

# Context is automatically set by SimCoordinationClient in callbacks
# Manual setting (if needed outside callbacks):
set_task_id("TASK202601282328VG3IE7H3CA0F")
set_biz_component("MyAgent")
logger.info("Processing task")  # Will include context in log output
```

## File Structure

```
hydros_agent_sdk/
├── __init__.py              # Public API exports
├── base_agent.py            # BaseHydroAgent abstract class
├── coordination_client.py   # SimCoordinationClient
├── coordination_callback.py # SimCoordinationCallback interface
├── state_manager.py         # AgentStateManager
├── message_filter.py        # MessageFilter
├── mqtt.py                  # Low-level MQTT client wrapper
├── agent_config.py          # Configuration loading
├── agent_properties.py      # AgentProperties dictionary
├── logging_config.py        # Logging configuration
├── protocol/
│   ├── base.py             # HydroBaseModel
│   ├── models.py           # Core data models
│   ├── commands.py         # Command/response definitions
│   └── events.py           # Event definitions
├── agents/
│   ├── tickable_agent.py           # TickableAgent base
│   ├── ontology_simulation_agent.py
│   ├── twins_simulation_agent.py
│   ├── model_calculation_agent.py
│   └── central_scheduling_agent.py
└── utils/
    ├── hydro_object_utils.py  # Topology utilities
    └── mqtt_metrics.py        # Metrics utilities

examples/
├── agent_example.py         # Main example with factory pattern
├── agent.properties         # Agent configuration
├── env.properties           # MQTT configuration
└── agents/                  # Specialized agent examples
    ├── twins/
    ├── ontology/
    └── centralscheduling/
```

## Dependencies

- **paho-mqtt**: MQTT client library
- **pydantic**: Data validation and serialization
- **pyyaml**: YAML configuration parsing (optional but recommended)

## Notes

- The SDK is designed to match the Java Hydros coordinator protocol
- All timestamps and IDs follow Java conventions
- MQTT topics follow pattern: `/hydros/commands/coordination/{cluster_id}`
- Metrics topics follow pattern: `/hydros/commands/coordination/{cluster_id}/metrics`
- Agent instances are stateful and tied to simulation contexts
- Each simulation task (context) gets its own agent instance
- The SDK supports both tick-driven and event-driven agent modes

## Error Handling

### Overview

The SDK provides a comprehensive error handling mechanism that automatically converts exceptions to appropriate error responses for the coordinator.

**Key Components:**
- `ErrorCodes`: Error code definitions (matching Java implementation)
- `@handle_agent_errors`: Decorator for automatic error handling
- `safe_execute()`: Utility for safe function execution
- `AgentErrorContext`: Context manager for code block error handling

### Error Codes

Located in `hydros_agent_sdk/error_codes.py`, matching Java `com.hydros.common.ErrorCodes`:

**Core Error Codes:**
- `SYSTEM_ERROR` - Unknown system failures
- `INVALID_PARAMS` - Invalid parameters
- `CONFIGURATION_LOAD_FAILURE` - Configuration loading failures

**Agent Error Codes:**
- `AGENT_INIT_FAILURE` - Agent initialization failures
- `AGENT_TICK_FAILURE` - Agent tick execution failures
- `AGENT_TERMINATE_FAILURE` - Agent termination failures
- `TIME_SERIES_UPDATE_FAILURE` - Time series data update failures

**Simulation Error Codes:**
- `TOPOLOGY_LOAD_FAILURE` - Topology loading failures
- `SIMULATION_EXECUTION_FAILURE` - Simulation execution failures
- `MODEL_INITIALIZATION_FAILURE` - Model initialization failures
- `BOUNDARY_CONDITION_ERROR` - Boundary condition errors
- `METRICS_GENERATION_FAILURE` - Metrics generation failures

### Usage Patterns

#### Pattern 1: Decorator (Recommended for Lifecycle Methods)

```python
from hydros_agent_sdk import TwinsSimulationAgent, ErrorCodes, handle_agent_errors

class MyAgent(TwinsSimulationAgent):
    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request):
        # Any exception will be caught and converted to error response
        self.load_agent_configuration(request)
        self._initialize_model()
        return SimTaskInitResponse(...)

    @handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
    def on_tick(self, request):
        # Automatic error handling
        metrics = self._execute_simulation(request.step)
        return TickCmdResponse(...)
```

#### Pattern 2: safe_execute() (For Individual Operations)

```python
from hydros_agent_sdk import safe_execute, ErrorCodes

success, topology, error_msg = safe_execute(
    HydroObjectUtilsV2.build_waterway_topology,
    ErrorCodes.TOPOLOGY_LOAD_FAILURE,
    self.agent_code,
    topology_url
)

if not success:
    logger.error(f"Failed to load topology: {error_msg}")
    raise RuntimeError(error_msg)
```

#### Pattern 3: AgentErrorContext (For Code Blocks)

```python
from hydros_agent_sdk import AgentErrorContext, ErrorCodes

with AgentErrorContext(ErrorCodes.SIMULATION_EXECUTION_FAILURE, self.agent_code) as ctx:
    results = self._run_simulation(step, boundary_conditions)

if ctx.has_error:
    logger.error(f"Simulation failed: {ctx.error_message}")
    return []
```

### Error Response Format

When an error occurs, the response includes:

```python
{
    "command_status": "FAILED",
    "error_code": "AGENT_INIT_FAILURE",
    "error_message": "Agent initialization failed: MyAgent, detail: Failed to load topology\nTraceback:\n...",
    ...
}
```

### Documentation

- **Full Guide**: `docs/ERROR_HANDLING.md`
- **Summary**: `ERROR_HANDLING_SUMMARY.md`
- **Example**: `examples/error_handling_example.py`
- **Agent Example**: `examples/agents/twins/twins_agent_with_error_handling.py`

