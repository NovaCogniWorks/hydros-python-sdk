# Hydros Agent SDK

The official Python SDK for the Hydros ecosystem. This library provides clients and data models for interacting with Hydros simulation agents via MQTT.

## Requirements

- Python >= 3.9
- OS: Windows, Linux, macOS

## Installation

```bash
pip install hydros-agent-sdk
```

## Usage

### MQTT Client

The SDK provides a typed MQTT client wrapper for handling simulation commands.

```python
import time
from hydros_agent_sdk.mqtt import HydrosMqttClient, CommandDispatcher
from hydros_agent_sdk.protocol.commands import SimTaskInitRequest, HydroCmd

def on_init_request(cmd: HydroCmd):
    if isinstance(cmd, SimTaskInitRequest):
        print(f"Received init request for agents: {cmd.agentList}")

# 1. Setup Dispatcher and Handlers
dispatcher = CommandDispatcher()
dispatcher.register_handler("SIMCMD_TASK_INIT_REQUEST", on_init_request)

# 2. Initialize Client
client = HydrosMqttClient(client_id="my_agent_1", dispatcher=dispatcher)

# 3. Connect
client.connect("tcp://localhost", port=1883)
client.subscribe("hydros/agent/+/request")

# 4. Keep running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.disconnect()
```

### Protocol Models

The SDK includes Pydantic models for protocol validation.

```python
from hydros_agent_sdk.protocol.commands import TickCmdRequest, SimTaskInitRequest

# Create a command
tick_cmd = TickCmdRequest(
    command_id="cmd_123",
    context={"bizSceneInstanceId": "scene_1", "taskId": "task_1"},
    tickId=100,
    deltaTime=0.05
)

# Serialize
payload = tick_cmd.model_dump_json()
print(payload)
```

## Binary Support

This package supports being bundled into binaries using tools like `PyInstaller` internally, but is primarily designed to be imported as a library.
