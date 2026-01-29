# Agent Configuration Loading

The Hydros Python SDK provides comprehensive functionality to load and parse agent configuration YAML files from URLs or local files. This feature enables agents to externalize their configuration and load it dynamically at runtime.

## Features

- **Load from URL**: Fetch configuration from HTTP/HTTPS URLs with proper encoding for non-ASCII characters (e.g., Chinese characters)
- **Load from File**: Read configuration from local YAML files
- **Load from String**: Parse YAML content directly from strings
- **Type-Safe Models**: Pydantic-based models with automatic validation
- **Convenience Methods**: Easy access to commonly used configuration values
- **Snake Case Convention**: Python-friendly field names with automatic camelCase conversion for JSON

## Installation

The agent configuration feature requires PyYAML:

```bash
pip install hydros-agent-sdk
# PyYAML is automatically installed as a dependency
```

## Quick Start

### Basic Usage

```python
from hydros_agent_sdk.agent_config import AgentConfigLoader

# Load from URL
config = AgentConfigLoader.from_url(
    "http://example.com/agent_config.yaml"
)

# Access configuration values
agent_code = config.get_agent_code()
modeling_url = config.get_hydros_objects_modeling_url()

print(f"Agent: {agent_code}")
print(f"Modeling URL: {modeling_url}")
```

### Load from Local File

```python
# Load from local file
config = AgentConfigLoader.from_file("config/agent_config.yaml")

# Access properties
print(f"Step Resolution: {config.properties.step_resolution}")
print(f"Total Steps: {config.properties.total_steps}")
```

### Load from YAML String

```python
yaml_content = """
agent_code: MY_AGENT
agent_type: SIMULATION_AGENT
agent_name: My Agent
version: v1.0.0
release_at: 2026/01/01
author:
  user_name: Developer Name
description: Agent description
waterway:
  waterway_id: 1
  waterway_name: Test Waterway
properties:
  hydros_objects_modeling_url: http://example.com/objects.yaml
"""

config = AgentConfigLoader.from_yaml_string(yaml_content)
```

## Configuration Structure

### Complete YAML Example

```yaml
agent_code: TWINS_SIMULATION_AGENT
agent_type: TWINS_SIMULATION_AGENT
agent_name: 孪生智能体
agent_configuration_url: http://example.com/agent_config.yaml
version: v0.0.1
release_at: 2026/01/01
author:
  user_name: 曹国军/黄志峰
description: 孪生仿真，积分延迟零模型
waterway:
  waterway_id: 50
  waterway_name: 京石段
properties:
  biz_start_time: 2025/01/01 00:00:00
  step_resolution: 60
  total_steps: 4320
  driven_by_coordinator: true
  hydro_environment_type: NORMAL
  hydros_objects_modeling_url: http://example.com/objects.yaml
  idz_config_url: http://example.com/idz_config.yml
  time_series_config_url: http://example.com/time_series.yaml
  output_config:
    output_mode: MQTT
    mqtt_broker:
      mqtt_host: 192.168.1.24
      mqtt_port: 1883
      server_uri: tcp://192.168.1.24:1883
    mqtt_topic: +/hydros/simulation/jobs/+/twins/objects
```

## API Reference

### AgentConfigLoader

Static methods for loading configurations:

#### `from_url(url: str, timeout: int = 30) -> AgentConfiguration`

Load configuration from a URL.

**Parameters:**
- `url`: The URL to fetch the YAML configuration from
- `timeout`: Request timeout in seconds (default: 30)

**Returns:** `AgentConfiguration` object

**Raises:**
- `ImportError`: If PyYAML is not installed
- `URLError`: If the URL cannot be accessed
- `HTTPError`: If the HTTP request fails
- `ValueError`: If the YAML content is invalid

#### `from_file(file_path: str) -> AgentConfiguration`

Load configuration from a local file.

**Parameters:**
- `file_path`: Path to the YAML configuration file

**Returns:** `AgentConfiguration` object

**Raises:**
- `ImportError`: If PyYAML is not installed
- `FileNotFoundError`: If the file does not exist
- `ValueError`: If the YAML content is invalid

#### `from_yaml_string(yaml_content: str) -> AgentConfiguration`

Parse configuration from a YAML string.

**Parameters:**
- `yaml_content`: YAML content as a string

**Returns:** `AgentConfiguration` object

**Raises:**
- `ImportError`: If PyYAML is not installed
- `ValueError`: If the YAML content is invalid

#### `from_dict(data: Dict[str, Any]) -> AgentConfiguration`

Create configuration from a dictionary.

**Parameters:**
- `data`: Dictionary containing configuration data

**Returns:** `AgentConfiguration` object

### AgentConfiguration

The main configuration model with convenience methods:

#### Convenience Methods

- **`get_agent_code() -> str`**: Get the agent code
- **`get_hydros_objects_modeling_url() -> Optional[str]`**: Get the Hydros objects modeling URL
- **`get_idz_config_url() -> Optional[str]`**: Get the IDZ configuration URL
- **`get_time_series_config_url() -> Optional[str]`**: Get the time series configuration URL
- **`get_mqtt_broker_config() -> Optional[MqttBroker]`**: Get the MQTT broker configuration
- **`get_property(key: str, default: Any = None) -> Any`**: Get a property value by key with optional default

#### Direct Property Access

```python
# Basic properties
config.agent_code
config.agent_type
config.agent_name
config.version
config.release_at
config.description

# Author information
config.author.user_name

# Waterway information
config.waterway.waterway_id
config.waterway.waterway_name

# Agent properties
config.properties.biz_start_time
config.properties.step_resolution
config.properties.total_steps
config.properties.driven_by_coordinator
config.properties.hydro_environment_type

# Output configuration
config.properties.output_config.output_mode
config.properties.output_config.mqtt_broker.mqtt_host
config.properties.output_config.mqtt_broker.mqtt_port
config.properties.output_config.mqtt_topic
```

## Integration with SimCoordinationClient

### Example: Configurable Agent

```python
from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.models import HydroAgent

class ConfigurableAgent(HydroAgent):
    def __init__(self, config):
        super().__init__(
            agent_code=config.get_agent_code(),
            agent_type=config.agent_type,
            agent_name=config.agent_name,
        )
        self.config = config
        self.modeling_url = config.get_hydros_objects_modeling_url()
        self.step_resolution = config.get_property('step_resolution', 60)

    def initialize(self, context):
        # Load modeling data from URL
        print(f"Loading models from: {self.modeling_url}")
        # ... initialization logic
        return True

class AgentCallback(SimCoordinationCallback):
    def __init__(self, config):
        self.config = config
        self.agents = {}

    def on_sim_task_init(self, request):
        agent = ConfigurableAgent(self.config)
        agent.initialize(request.simulation_context)
        # ... return response

# Main application
config = AgentConfigLoader.from_url("http://example.com/config.yaml")

# Use MQTT config from agent configuration
mqtt_broker = config.get_mqtt_broker_config()
client = SimCoordinationClient(
    mqtt_host=mqtt_broker.mqtt_host if mqtt_broker else "localhost",
    mqtt_port=mqtt_broker.mqtt_port if mqtt_broker else 1883,
    callback=AgentCallback(config)
)

client.start()
```

## Advanced Usage

### Custom Properties

The `AgentProperties` model allows additional properties not explicitly defined:

```python
# Access custom properties using get_property
custom_value = config.get_property('custom_field', 'default_value')

# Or access directly if you know the field exists
if hasattr(config.properties, 'custom_field'):
    value = config.properties.custom_field
```

### Error Handling

```python
try:
    config = AgentConfigLoader.from_url(config_url)
except ImportError:
    print("PyYAML is not installed")
except HTTPError as e:
    print(f"HTTP error: {e.code} {e.reason}")
except URLError as e:
    print(f"URL error: {e.reason}")
except ValueError as e:
    print(f"Invalid configuration: {e}")
```

### URL Encoding

The loader automatically handles URLs with non-ASCII characters (e.g., Chinese characters):

```python
# This URL contains Chinese characters and will be properly encoded
config = AgentConfigLoader.from_url(
    "http://example.com/京石段/agent_config.yaml"
)
```

## Examples

See the `examples/` directory for complete working examples:

- **`load_agent_config.py`**: Basic configuration loading examples
- **`configurable_agent.py`**: Full agent implementation with configuration loading

Run examples:

```bash
python examples/load_agent_config.py
python examples/configurable_agent.py
```

## Testing

Run the test suite:

```bash
# With pytest
pytest tests/test_agent_config.py

# Without pytest (standalone)
python tests/test_agent_config.py
```

## Field Naming Convention

The SDK uses **snake_case** for all field names (Python convention), which are automatically converted to/from camelCase when serializing/deserializing JSON messages (Java convention).

**Python (snake_case):**
```python
config.properties.biz_start_time
config.properties.hydros_objects_modeling_url
```

**YAML/JSON (camelCase):**
```yaml
properties:
  bizStartTime: 2025/01/01 00:00:00
  hydrosObjectsModelingUrl: http://example.com/objects.yaml
```

This conversion is handled automatically by `HydroBaseModel` using Pydantic's `alias_generator`.

## Best Practices

1. **Externalize Configuration**: Store agent configurations in external YAML files for easy updates without code changes

2. **Use Environment Variables**: Load configuration URLs from environment variables for different environments:
   ```python
   import os
   config_url = os.getenv('AGENT_CONFIG_URL', 'http://default.com/config.yaml')
   config = AgentConfigLoader.from_url(config_url)
   ```

3. **Validate Configuration**: Check for required properties after loading:
   ```python
   config = AgentConfigLoader.from_url(config_url)
   if not config.get_hydros_objects_modeling_url():
       raise ValueError("Missing required modeling URL")
   ```

4. **Cache Configuration**: Load configuration once at startup and reuse:
   ```python
   # At application startup
   global_config = AgentConfigLoader.from_url(config_url)

   # Reuse throughout application
   agent = ConfigurableAgent(global_config)
   ```

5. **Handle Errors Gracefully**: Always wrap configuration loading in try-except blocks

## Troubleshooting

### PyYAML Not Installed

```
ImportError: PyYAML is required to load agent configurations
```

**Solution:** Install PyYAML:
```bash
pip install pyyaml
```

### URL Encoding Issues

```
URLError: 'ascii' codec can't encode characters
```

**Solution:** The loader automatically handles URL encoding. If you still encounter issues, ensure you're using the latest version of the SDK.

### Invalid YAML

```
ValueError: Invalid YAML content
```

**Solution:** Validate your YAML syntax using an online YAML validator or:
```bash
python -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

### Missing Required Fields

```
ValueError: Field required
```

**Solution:** Ensure all required fields are present in your YAML:
- agent_code
- agent_type
- agent_name
- version
- release_at
- author (with user_name)
- description
- waterway (with waterway_id and waterway_name)
- properties

## License

MIT License - see LICENSE file for details.
