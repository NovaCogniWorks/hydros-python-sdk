# Hydros Logging Configuration

This document describes the custom logging format used in the Hydros Python SDK, which matches the Java logback pattern used in hydros-data.

## Overview

The Hydros SDK provides a custom logging formatter that produces structured logs matching the Java implementation:

```
DATA|2026-01-30 08:56:34|INFO|TASK202601282328VG3IE7H3CA0F|SimCoordinator|||h.a.coordination_client|Processing command
```

### Format Breakdown

The log format consists of 9 pipe-separated fields:

| Field | Description | Example | Default |
|-------|-------------|---------|---------|
| 1. Node ID | `hydros_node_id` identifying the agent node | `DATA` | `"DATA"` |
| 2. Timestamp | Date and time in `yyyy-MM-dd HH:mm:ss` format | `2026-01-30 08:56:34` | Current time |
| 3. Level | Log level (5 chars, left-aligned) | `INFO ` | - |
| 4. Task ID | `biz_scene_instance_id` for the simulation task | `TASK202601282328VG3IE7H3CA0F` | `"System"` |
| 5. Component | `agent_code` identifying the agent | `SimCoordinator` | `"Common"` |
| 6. Type | Optional log type field | - | `""` |
| 7. Content | Optional log content field | - | `""` |
| 8. Logger | Abbreviated logger name | `h.a.coordination_client` | - |
| 9. Message | The actual log message | `Processing command` | - |

## Quick Start

### Basic Setup

```python
from hydros_agent_sdk import setup_logging

# Configure logging with Hydros formatter
setup_logging(
    level=logging.INFO,
    node_id="DATA",  # Your hydros_node_id
    console=True,
    log_file="logs/hydros-agent.log"  # Optional: log to file
)
```

### Using Log Context

```python
from hydros_agent_sdk import LogContext, set_task_id, set_biz_component
import logging

logger = logging.getLogger(__name__)

# Method 1: Using context manager (recommended)
with LogContext(
    task_id="TASK202601282328VG3IE7H3CA0F",
    biz_component="SimCoordinator"
):
    logger.info("Processing simulation task")
    # Output: DATA|2026-01-30 08:56:34|INFO|TASK202601282328VG3IE7H3CA0F|SimCoordinator|||__main__|Processing simulation task

# Method 2: Using setter functions
set_task_id("TASK202601282328VG3IE7H3CA0F")
set_biz_component("SimCoordinator")
logger.info("Processing simulation task")
```

## Automatic Context in SimCoordinationClient

The `SimCoordinationClient` automatically sets the logging context when processing commands, so all logs within your callback methods will include the correct context:

```python
from hydros_agent_sdk import SimCoordinationClient, SimCoordinationCallback, setup_logging
import logging

# Configure logging
setup_logging(level=logging.INFO, node_id="AGENT_NODE_01")

logger = logging.getLogger(__name__)

class MyCallback(SimCoordinationCallback):
    def get_component(self):
        return "MyAgent"

    def on_sim_task_init(self, request):
        # Logging context is automatically set:
        # - task_id = request.context.biz_scene_instance_id
        # - biz_component = "MyAgent"
        # - node_id = "AGENT_NODE_01"
        logger.info("Initializing agent instance")
        # Output: AGENT_NODE_01|2026-01-30 08:56:34|INFO|TASK123...|MyAgent|||__main__|Initializing agent instance

    def on_tick(self, request):
        logger.info(f"Processing tick {request.step}")
        # Context is automatically set for each command

# Create client
client = SimCoordinationClient(
    broker_url="tcp://192.168.1.24",
    broker_port=1883,
    topic="/hydros/commands/coordination/cluster",
    callback=MyCallback()
)
client.start()
```

## API Reference

### Setup Function

#### `setup_logging(level, node_id, log_file, console)`

Configure logging with Hydros formatter.

**Parameters:**
- `level` (int): Logging level (default: `logging.INFO`)
- `node_id` (str): Default node ID for logs (default: `"DATA"`)
- `log_file` (str, optional): Path to log file
- `console` (bool): Whether to log to console (default: `True`)

**Example:**
```python
setup_logging(
    level=logging.DEBUG,
    node_id="AGENT_NODE_01",
    log_file="logs/agent.log",
    console=True
)
```

### Context Management

#### `LogContext(task_id, biz_component, log_type, log_content, node_id)`

Context manager for setting logging context.

**Parameters:**
- `task_id` (str, optional): Task ID (`biz_scene_instance_id`)
- `biz_component` (str, optional): Business component (`agent_code`)
- `log_type` (str, optional): Log type
- `log_content` (str, optional): Log content
- `node_id` (str, optional): Node ID (`hydros_node_id`)

**Example:**
```python
with LogContext(task_id="TASK123", biz_component="MyAgent"):
    logger.info("Processing")
```

#### Setter Functions

Set individual context values:

```python
set_task_id(task_id: Optional[str])
set_biz_component(biz_component: Optional[str])
set_log_type(log_type: Optional[str])
set_log_content(log_content: Optional[str])
set_node_id(node_id: Optional[str])
```

#### Getter Functions

Get current context values:

```python
get_task_id() -> Optional[str]
get_biz_component() -> Optional[str]
get_log_type() -> Optional[str]
get_log_content() -> Optional[str]
get_node_id() -> Optional[str]
```

### Custom Formatter

#### `HydrosFormatter(default_node_id, logger_max_length)`

Custom formatter that matches the Java logback pattern.

**Parameters:**
- `default_node_id` (str): Default node ID if not set in context (default: `"DATA"`)
- `logger_max_length` (int): Maximum length for logger name abbreviation (default: `36`)

**Example:**
```python
import logging
from hydros_agent_sdk import HydrosFormatter

formatter = HydrosFormatter(default_node_id="CUSTOM_NODE", logger_max_length=50)
handler = logging.StreamHandler()
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.addHandler(handler)
```

## Advanced Usage

### Nested Contexts

Contexts can be nested, with inner contexts overriding outer ones:

```python
with LogContext(task_id="OUTER", biz_component="OuterAgent"):
    logger.info("Outer context")
    # Output: DATA|...|INFO|OUTER|OuterAgent|...

    with LogContext(task_id="INNER", biz_component="InnerAgent"):
        logger.info("Inner context")
        # Output: DATA|...|INFO|INNER|InnerAgent|...

    logger.info("Back to outer")
    # Output: DATA|...|INFO|OUTER|OuterAgent|...
```

### Exception Logging

Exceptions are automatically formatted with traceback:

```python
try:
    result = 1 / 0
except Exception as e:
    logger.error(f"Error: {e}", exc_info=True)
    # Output includes full traceback after the message
```

### Logger Name Abbreviation

Long logger names are automatically abbreviated to fit within the configured length:

```python
# Original: com.hydros.coordination.service.BaseCoordinatorMqttService
# Abbreviated: c.h.c.s.BaseCoordinatorMqttService

# Original: hydros_agent_sdk.coordination_client
# Abbreviated: h.a.coordination_client
```

### Custom Log File Rotation

For production deployments, consider using `RotatingFileHandler` or `TimedRotatingFileHandler`:

```python
import logging
from logging.handlers import TimedRotatingFileHandler
from hydros_agent_sdk import HydrosFormatter

# Create formatter
formatter = HydrosFormatter(default_node_id="PROD_NODE")

# Create rotating file handler (daily rotation, keep 30 days)
handler = TimedRotatingFileHandler(
    filename="logs/hydros-agent.log",
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8"
)
handler.setFormatter(formatter)

# Configure root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)
```

## Best Practices

1. **Set node_id early**: Configure the node ID when your application starts:
   ```python
   setup_logging(node_id=os.getenv("HYDROS_NODE_ID", "DATA"))
   ```

2. **Use context managers**: Prefer `LogContext` over setter functions for automatic cleanup:
   ```python
   # Good
   with LogContext(task_id=task_id):
       process_task()

   # Less ideal (requires manual cleanup)
   set_task_id(task_id)
   process_task()
   set_task_id(None)  # Don't forget to clean up!
   ```

3. **Let SimCoordinationClient handle context**: When using the coordination client, the context is set automatically - you don't need to set it manually in your callbacks.

4. **Use structured messages**: Include key information in log messages:
   ```python
   logger.info(f"发布协调指令成功,commandId={cmd_id},commandType={cmd_type} 到MQTT Topic={topic}")
   ```

5. **Configure appropriate log levels**:
   - `DEBUG`: Detailed diagnostic information
   - `INFO`: General informational messages (default)
   - `WARNING`: Warning messages for potentially harmful situations
   - `ERROR`: Error messages for serious problems

## Comparison with Java Implementation

The Python implementation closely matches the Java logback configuration:

**Java (logback.xml):**
```xml
<property name="LOG_PATTERN" value="DATA|%d{yyyy-MM-dd HH:mm:ss}|%-5level|%X{taskId:-System}|%X{bizComponent:-Common}|%X{type:-}|%X{content:-}|%logger{36}|%msg%n" />
```

**Python equivalent:**
```python
setup_logging(node_id="DATA")
with LogContext(task_id="TASK123", biz_component="MyAgent"):
    logger.info("Message")
```

**Key differences:**
- Python uses `contextvars` instead of MDC (Mapped Diagnostic Context)
- Python's context is thread-safe and works with async code
- Field names use snake_case in Python (e.g., `task_id` vs `taskId`)

## Troubleshooting

### Logs not showing context

Make sure you've configured logging with `setup_logging()` before creating loggers:

```python
# Wrong order
logger = logging.getLogger(__name__)
setup_logging()  # Too late!

# Correct order
setup_logging()
logger = logging.getLogger(__name__)
```

### Context not persisting across threads

Context is thread-local by design. Set context in each thread:

```python
def worker_thread():
    set_task_id("TASK123")
    logger.info("Worker processing")

thread = Thread(target=worker_thread)
thread.start()
```

### File not found error

Create the log directory before writing:

```python
import os
os.makedirs("logs", exist_ok=True)
setup_logging(log_file="logs/agent.log")
```

## Examples

See the following examples for complete working code:
- `examples/logging_example.py` - Basic logging examples
- `examples/agent_example.py` - Logging with SimCoordinationClient
- `tests/test_logging_config.py` - Unit tests demonstrating all features
