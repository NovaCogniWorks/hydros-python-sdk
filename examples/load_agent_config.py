"""
Example: Loading and Using Agent Configuration

This example demonstrates how to load agent configuration from a URL or file,
and access various configuration properties.
"""

import logging
from hydros_agent_sdk.agent_config import AgentConfigLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Main example function demonstrating agent configuration loading."""

    # Example 1: Load from URL
    print("=" * 60)
    print("Example 1: Loading configuration from URL")
    print("=" * 60)

    config_url = "http://47.97.1.45:9000/hydros/mdm/京石段/agents/twins_simulation/agent_config.yaml"

    try:
        config = AgentConfigLoader.from_url(config_url)

        # Access basic properties
        print(f"\nAgent Code: {config.get_agent_code()}")
        print(f"Agent Type: {config.agent_type}")
        print(f"Agent Name: {config.agent_name}")
        print(f"Version: {config.version}")
        print(f"Author: {config.author.user_name}")
        print(f"Description: {config.description}")

        # Access waterway information
        print(f"\nWaterway ID: {config.waterway.waterway_id}")
        print(f"Waterway Name: {config.waterway.waterway_name}")

        # Access properties
        print(f"\nBusiness Start Time: {config.properties.biz_start_time}")
        print(f"Step Resolution: {config.properties.step_resolution}")
        print(f"Total Steps: {config.properties.total_steps}")
        print(f"Driven by Coordinator: {config.properties.driven_by_coordinator}")

        # Access important URLs using convenience methods
        print(f"\nHydros Objects Modeling URL: {config.get_hydros_objects_modeling_url()}")
        print(f"IDZ Config URL: {config.get_idz_config_url()}")
        print(f"Time Series Config URL: {config.get_time_series_config_url()}")

        # Access MQTT configuration
        mqtt_broker = config.get_mqtt_broker_config()
        if mqtt_broker:
            print(f"\nMQTT Broker Host: {mqtt_broker.mqtt_host}")
            print(f"MQTT Broker Port: {mqtt_broker.mqtt_port}")
            print(f"MQTT Server URI: {mqtt_broker.server_uri}")

        # Access output configuration
        if config.properties.output_config:
            print(f"Output Mode: {config.properties.output_config.output_mode}")
            print(f"MQTT Topic: {config.properties.output_config.mqtt_topic}")

        # Use generic property accessor
        print(f"\nHydro Environment Type: {config.get_property('hydro_environment_type')}")
        print(f"Unknown Property (with default): {config.get_property('unknown_key', 'default_value')}")

    except Exception as e:
        logger.error(f"Failed to load configuration from URL: {e}")
        print(f"\nNote: If the URL is not accessible, this is expected.")

    # Example 2: Load from local file
    print("\n" + "=" * 60)
    print("Example 2: Loading configuration from local file")
    print("=" * 60)

    # Create a sample YAML file for demonstration
    sample_yaml = """agent_code: TWINS_SIMULATION_AGENT
agent_type: TWINS_SIMULATION_AGENT
agent_name: 孪生智能体
agent_configuration_url: http://47.97.1.45:9000/hydros/mdm/京石段/agents/twins_simulation/agent_config.yaml
version: v0.0.1
release_at: 2026/01/01
author:
  user_name: 曹国军/黄志峰
description: 孪生仿真，积分延迟零模型，简化水力学模型，常用于数字孪生系统中以实现快速仿真和实时控制
waterway:
  waterway_id: 50
  waterway_name: 京石段
properties:
  biz_start_time: 2025/01/01 00:00:00
  step_resolution: 60
  total_steps: 4320
  driven_by_coordinator: true
  hydro_environment_type: NORMAL
  hydros_objects_modeling_url: http://47.97.1.45:9000/hydros/mdm/京石段/hydro_modeling/objects.yaml
  idz_config_url: http://47.97.1.45:9000/hydros/mdm/京石段/agents/twins_simulation/idz_config.yml
  time_series_config_url: http://47.97.1.45:9000/hydros/mdm/京石段/time_series/time_series.yaml
  output_config:
    output_mode: MQTT
    mqtt_broker:
      mqtt_host: 192.168.1.24
      mqtt_port: 1883
      server_uri: tcp://192.168.1.24:1883
    mqtt_topic: +/hydros/simulation/jobs/+/twins/objects
"""

    # Save sample to temporary file
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write(sample_yaml)
        temp_file = f.name

    try:
        config = AgentConfigLoader.from_file(temp_file)

        print(f"\nLoaded from file: {temp_file}")
        print(f"Agent Code: {config.get_agent_code()}")
        print(f"Hydros Objects Modeling URL: {config.get_hydros_objects_modeling_url()}")

        # Clean up
        os.unlink(temp_file)

    except Exception as e:
        logger.error(f"Failed to load configuration from file: {e}")
        if os.path.exists(temp_file):
            os.unlink(temp_file)

    # Example 3: Load from YAML string
    print("\n" + "=" * 60)
    print("Example 3: Loading configuration from YAML string")
    print("=" * 60)

    try:
        config = AgentConfigLoader.from_yaml_string(sample_yaml)

        print(f"\nAgent Code: {config.get_agent_code()}")
        print(f"Agent Name: {config.agent_name}")
        print(f"Hydros Objects Modeling URL: {config.get_hydros_objects_modeling_url()}")

    except Exception as e:
        logger.error(f"Failed to load configuration from YAML string: {e}")

    # Example 4: Integration with SimCoordinationClient
    print("\n" + "=" * 60)
    print("Example 4: Using configuration with SimCoordinationClient")
    print("=" * 60)

    print("""
# Typical usage pattern in an agent:

from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.callback import SimCoordinationCallback

# Load configuration
config = AgentConfigLoader.from_url(config_url)

# Extract required values
agent_code = config.get_agent_code()
modeling_url = config.get_hydros_objects_modeling_url()

# Use in your agent implementation
class MyAgent(SimCoordinationCallback):
    def __init__(self, config):
        self.config = config
        self.agent_code = config.get_agent_code()
        self.modeling_url = config.get_hydros_objects_modeling_url()

    def on_sim_task_init(self, request):
        # Use configuration in business logic
        print(f"Initializing agent: {self.agent_code}")
        print(f"Loading models from: {self.modeling_url}")
        # ... rest of initialization
        pass

# Create client with callback
agent = MyAgent(config)
client = SimCoordinationClient(
    mqtt_host="localhost",
    mqtt_port=1883,
    callback=agent
)
client.start()
""")


if __name__ == "__main__":
    main()
