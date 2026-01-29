# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Hydros Python SDK is an official Python SDK for the Hydros ecosystem, providing simulation agent coordination and MQTT protocol support. It enables Python developers to build distributed simulation agents that communicate via MQTT and coordinate through a centralized system.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in editable mode with dependencies
pip install -e .

# Install development tools
pip install pytest build twine
```

### Testing
```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run specific test file
pytest tests/test_specific.py
```

### Building and Deployment
```bash
# Build package (creates dist/ directory with .tar.gz and .whl)
python -m build

# Deploy to registry (maintainers only)
./deploy.sh
```

## Architecture Overview

### Core Components

**1. SimCoordinationClient** (`coordination_client.py`)
- High-level client that encapsulates MQTT logic and message handling
- Manages connection, subscriptions, message routing, and retry logic
- Uses callback-based architecture similar to Java's SimCoordinationSlave
- Handles automatic message filtering and routing to callbacks
- Thread-safe with separate threads for MQTT loop and outgoing message queue

**2. SimCoordinationCallback** (`callback.py`)
- Abstract base class defining callback interface for business logic
- Developers implement this to handle coordination commands
- Key methods: `on_sim_task_init()`, `on_tick()`, `on_terminate()`, `on_time_series_calculation()`, `on_time_series_data_update()`
- Separates business logic from infrastructure concerns

**3. AgentStateManager** (`state_manager.py`)
- Unified state management for multi-task agent services
- Tracks active simulation contexts (multi-task isolation via `biz_scene_instance_id`)
- Manages agent instances and their lifecycle (INITIALIZING → ACTIVE → TERMINATING → TERMINATED)
- Distinguishes between local and remote agents based on node ID
- Thread-safe for concurrent access

**4. MessageFilter** (`message_filter.py`)
- Filters incoming MQTT messages based on agent context and message type
- Implements Java logic from `SimCoordinationSlave.messageArrived()` and `isActiveToTaskSimCommand()`
- Always accepts `SimTaskInitRequest` messages
- Filters messages based on active contexts (only processes messages for active tasks)
- Filters responses based on local/remote agent distinction

**5. HydrosMqttClient** (`mqtt.py`)
- Lower-level MQTT client wrapper using paho-mqtt
- Provides CommandDispatcher for routing messages to handlers
- Used internally by SimCoordinationClient

**6. Protocol Models** (`protocol/`)
- `models.py`: Core data models (SimulationContext, HydroAgent, HydroAgentInstance, etc.)
- `commands.py`: Command definitions (SimTaskInitRequest/Response, TickCmdRequest/Response, etc.)
- `events.py`: Event definitions (HydroEvent, TimeSeriesDataChangedEvent)
- `base.py`: HydroBaseModel with snake_case field naming convention
- All models use Pydantic v2 for validation and serialization

**7. AgentConfigLoader** (`agent_config.py`)
- Loads and parses agent configuration YAML files from URLs or local files
- Provides Pydantic models for configuration structure (AgentConfiguration, AgentProperties, etc.)
- Handles URL encoding for non-ASCII characters (e.g., Chinese characters in URLs)
- Offers convenience methods for accessing common configuration values
- Supports loading from URL, file, YAML string, or dictionary

**8. HydroObjectUtilsV2** (`utils/hydro_object_utils.py`)
- Utility class for loading and parsing water network topology objects from YAML
- Python equivalent of Java `com.hydros.agent.common.utils.HydroObjectUtilsV2`
- Loads complex water network topology with objects, cross-sections, and connections
- Supports parameter filtering (load only specific parameters like `max_opening`)
- Generates metrics codes for child objects (water level, flow, gate opening)
- Builds topology indices for child-to-parent, upstream, and downstream relationships
- Provides object caching for fast O(1) lookups by ID
- See `docs/HYDRO_OBJECT_UTILS.md` for detailed documentation

### Key Design Patterns

**Multi-Task Isolation**
- Each simulation task has a unique `biz_scene_instance_id` in its SimulationContext
- AgentStateManager tracks active contexts to filter messages
- Agents only process messages for their active contexts
- Supports running multiple independent simulation tasks simultaneously

**Agent Lifecycle**
- Task Init: Create agent instance, register context as active
- Tick: Process simulation steps
- Terminate: Clean up resources, remove context from active set
- Each agent instance corresponds to one simulation task

**Local vs Remote Agents**
- Local agents: Running on the same node (same `hydros_node_id`)
- Remote agents: Running on different nodes
- MessageFilter uses this distinction to filter responses and status reports
- Only process responses from remote agents to avoid duplicate handling

**Factory Pattern** (see `examples/agent_example.py`)
- AgentFactory creates agent instances for each simulation context
- MultiAgentCoordinationCallback manages multiple agent instances
- Each context gets its own agent instance with required dependencies

### Field Naming Convention

The SDK uses **snake_case** for all field names (Python convention), which are automatically converted to/from camelCase when serializing/deserializing JSON messages (Java convention). This is handled by `HydroBaseModel` using Pydantic's `alias_generator=to_snake`.

Example:
- Python: `biz_scene_instance_id`, `agent_biz_status`, `hydros_node_id`
- JSON: `bizSceneInstanceId`, `agentBizStatus`, `hydrosNodeId`

### Enumerations

The SDK defines several enums matching the Java implementation:
- `AgentBizStatus`: INIT, IDLE, ACTIVE, FAILED
- `AgentDriveMode`: SIM_TICK_DRIVEN, EVENT_DRIVEN, PROACTIVE
- `CommandStatus`: INIT, PROCESSING, SUCCEED, FAILED
- `TaskStatus`: INITIALIZING, ACTIVE, TERMINATING, TERMINATED

## Implementation Guidelines

### Creating a New Agent

1. Implement `SimCoordinationCallback` or extend the base `HydroAgent` class
2. Implement required methods: `on_sim_task_init()`, `on_tick()`, `on_terminate()`
3. Create `SimCoordinationClient` with your callback
4. Call `client.start()` to begin listening for commands

See `examples/agent_example.py` for a complete working example with factory pattern.

### Loading Agent Configuration

Agents can externalize their configuration using YAML files loaded from URLs or local files:

```python
from hydros_agent_sdk.agent_config import AgentConfigLoader

# Load configuration from URL
config = AgentConfigLoader.from_url("http://example.com/agent_config.yaml")

# Access configuration values
agent_code = config.get_agent_code()
modeling_url = config.get_hydros_objects_modeling_url()
step_resolution = config.get_property('step_resolution', 60)

# Use in agent initialization
class MyAgent(HydroAgent):
    def __init__(self, config):
        super().__init__(
            agent_code=config.get_agent_code(),
            agent_type=config.agent_type,
            agent_name=config.agent_name,
        )
        self.modeling_url = config.get_hydros_objects_modeling_url()
```

**Key Methods:**
- `AgentConfigLoader.from_url(url)`: Load from HTTP/HTTPS URL
- `AgentConfigLoader.from_file(path)`: Load from local file
- `AgentConfigLoader.from_yaml_string(yaml)`: Parse YAML string
- `config.get_agent_code()`: Get agent code
- `config.get_hydros_objects_modeling_url()`: Get modeling URL
- `config.get_property(key, default)`: Get any property with default

See `examples/configurable_agent.py` for a complete example and `docs/AGENT_CONFIG.md` for detailed documentation.

### Loading Water Network Topology

Agents can load complex water network topology objects from YAML files using `HydroObjectUtilsV2`:

```python
from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.utils import HydroObjectUtilsV2

# Load agent configuration
config = AgentConfigLoader.from_url("http://example.com/agent_config.yaml")

# Get modeling URL from configuration
modeling_url = config.get_property('hydros_objects_modeling_url')

# Load water network topology with specific parameters
param_keys = {'max_opening', 'min_opening', 'interpolate_cross_section_count'}
topology = HydroObjectUtilsV2.build_waterway_topology(
    modeling_yml_uri=modeling_url,
    param_keys=param_keys,
    with_metrics_code=True
)

# Access topology information
for obj in topology.top_objects:
    print(f"Object: {obj.object_name} ({obj.object_type})")
    print(f"  Children: {len(obj.children)}")

    for child in obj.children:
        print(f"  - {child.object_name}: metrics={child.metrics}")

# Query topology relationships
neighbors = topology.find_neighbors(object_id)
parent = topology.get_top_object_by_child_id(child_id)
```

**Key Methods:**
- `HydroObjectUtilsV2.from_url(url)`: Load topology with default settings
- `HydroObjectUtilsV2.build_waterway_topology(url, param_keys, with_metrics_code)`: Load with options
- `topology.get_object(object_id)`: Get any object by ID with caching
- `topology.find_neighbors(object_id)`: Get upstream/downstream neighbors
- `topology.get_objects(managed_ids, child_types)`: Filter objects by criteria

See `examples/hydro_object_utils_example.py` for a complete example and `docs/HYDRO_OBJECT_UTILS.md` for detailed documentation.

### Message Flow

**Incoming Messages:**
1. MQTT message arrives → `_on_message()` callback
2. Parse JSON → Pydantic model (using `SimCommandEnvelope`)
3. Apply filters → `MessageFilter.should_process_message()`
4. Route to handler → `_handle_incoming_message()`
5. Call appropriate callback method on user's callback implementation

**Outgoing Messages:**
1. Create command object (e.g., `SimTaskInitResponse`)
2. Call `client.enqueue(command)` for async send or `client.send_command(command)` for sync
3. Queue thread processes message with retry logic
4. Serialize to JSON and publish via MQTT

### Thread Safety

- `AgentStateManager` uses internal locking for thread-safe state access
- `SimCoordinationClient` uses separate threads for MQTT loop and message queue
- Callback methods are called from MQTT thread - keep them fast or delegate to worker threads

### Error Handling

- Set `command_status=CommandStatus.FAILED` in responses when errors occur
- Include `error_code` and `error_message` in response objects
- Log errors with context (command_id, context_id, etc.)

## Testing Notes

The test directory contains test files for various components:
- `tests/test_agent_config.py`: Tests for agent configuration loading
- Place new test files in `tests/` directory
- Name test files with `test_*.py` prefix
- Tests can run with pytest or standalone: `python tests/test_agent_config.py`
- Use pytest fixtures for common setup (MQTT broker, mock clients, etc.)
- Test message filtering logic, state management, and callback routing
- Consider integration tests with a local MQTT broker (e.g., Mosquitto)

## Dependencies

- `paho-mqtt>=1.6.1`: MQTT client library
- `pydantic>=2.0.0`: Data validation and serialization
- `pyyaml>=6.0`: YAML parsing for agent configuration
- Python 3.9+ required

## Common Pitfalls

1. **Forgetting to activate contexts**: Always call `state_manager.add_active_context()` during task init
2. **Not removing contexts on terminate**: Call `state_manager.remove_active_context()` to prevent memory leaks
3. **Blocking in callbacks**: Keep callback methods fast; use threads for long-running operations
4. **Field naming confusion**: Remember Python uses snake_case, JSON uses camelCase (automatic conversion)
5. **Not setting node_id**: Set `state_manager.set_node_id()` for proper local/remote agent filtering
