"""
Configuration loader for Hydros Agent SDK.

This module provides utilities for loading environment and agent configurations
from .properties files.
"""

import os
import logging
from typing import Dict, Optional
from configparser import ConfigParser

logger = logging.getLogger(__name__)

ENV_OVERRIDE_MAP = {
    'MQTT_BROKER_URL': 'mqtt_broker_url',
    'MQTT_BROKER_PORT': 'mqtt_broker_port',
    'MQTT_TOPIC': 'mqtt_topic',
    'MQTT_USERNAME': 'mqtt_username',
    'MQTT_PASSWORD': 'mqtt_password',
    'HYDROS_CLUSTER_ID': 'hydros_cluster_id',
    'HYDROS_NODE_ID': 'hydros_node_id',
}


def load_env_config(env_file: str = "./env.properties") -> Dict[str, str]:
    """
    Load environment configuration from env.properties file.

    This function loads the shared environment configuration that all agents use.
    The mqtt_topic is automatically constructed from hydros_cluster_id if not explicitly provided.

    Args:
        env_file: Path to environment configuration file (default: ./env.properties)

    Returns:
        Environment configuration dictionary

    Raises:
        FileNotFoundError: If env.properties file does not exist
        ValueError: If required properties are missing
    """
    # 解析 env.properties 路径：
    # 1. 如果调用方显式传入了相对路径，优先按当前工作目录解析
    # 2. 只有在使用默认值且当前目录找不到时，才回退到 examples/env.properties
    if not os.path.isabs(env_file):
        requested_env_file = os.path.abspath(env_file)
        if os.path.exists(requested_env_file):
            env_file = requested_env_file
        else:
            current_file = os.path.abspath(__file__)
            sdk_dir = os.path.dirname(current_file)
            project_root = os.path.dirname(sdk_dir)
            examples_dir = os.path.join(project_root, "examples")
            shared_env_file = os.path.join(examples_dir, "env.properties")

            if env_file == "./env.properties" and os.path.exists(shared_env_file):
                env_file = shared_env_file
            else:
                env_file = requested_env_file

    # Check if file exists
    if not os.path.exists(env_file):
        raise FileNotFoundError(
            f"Environment configuration file not found: {env_file}\n"
            f"Please create env.properties with required MQTT and cluster configuration."
        )

    logger.info(f"Loading environment config from: {env_file}")

    # Load properties
    config = load_properties_file(env_file)

    # Apply environment variable overrides before auto-generating mqtt_topic.
    overridden_keys = []
    for env_name, config_key in ENV_OVERRIDE_MAP.items():
        env_value = os.getenv(env_name)
        if env_value:
            config[config_key] = env_value
            overridden_keys.append(config_key)
    if overridden_keys:
        logger.info(f"Applied env overrides for: {', '.join(sorted(overridden_keys))}")

    # Auto-generate mqtt_topic from hydros_cluster_id if not provided
    if 'mqtt_topic' not in config or not config['mqtt_topic']:
        if 'hydros_cluster_id' in config and config['hydros_cluster_id']:
            config['mqtt_topic'] = f"/hydros/commands/coordination/{config['hydros_cluster_id']}"
            logger.info(f"Auto-generated mqtt_topic: {config['mqtt_topic']}")

    # Validate required properties
    required_props = [
        'mqtt_broker_url',
        'mqtt_broker_port',
        'mqtt_topic',
        'hydros_cluster_id',
        'hydros_node_id'
    ]

    missing_props = [prop for prop in required_props if prop not in config or not config[prop]]

    if missing_props:
        raise ValueError(
            f"Missing required properties in {env_file}:\n"
            f"  {', '.join(missing_props)}\n"
            f"\n"
            f"Required properties:\n"
            f"  - mqtt_broker_url: MQTT broker URL (e.g., tcp://192.168.1.24)\n"
            f"  - mqtt_broker_port: MQTT broker port (e.g., 1883)\n"
            f"  - hydros_cluster_id: Hydros cluster ID (e.g., weijiahao)\n"
            f"  - hydros_node_id: Hydros node ID (e.g., local)\n"
            f"\n"
            f"Note: mqtt_topic will be auto-generated as /hydros/commands/coordination/{{hydros_cluster_id}}\n"
        )

    return config


def load_properties_file(file_path: str) -> Dict[str, str]:
    """
    Load properties from a .properties file.

    Args:
        file_path: Path to properties file

    Returns:
        Properties dictionary

    Raises:
        FileNotFoundError: If file does not exist
        RuntimeError: If file cannot be parsed
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Properties file not found: {file_path}")

    config = ConfigParser()

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        result = {}
        # Load all properties from DEFAULT section
        for key, value in config.items('DEFAULT'):
            if value:
                result[key] = value

        return result

    except Exception as e:
        logger.error(f"Error loading properties file {file_path}: {e}")
        raise RuntimeError(f"Error loading properties file {file_path}: {e}")


def load_agent_config(config_file: str) -> Dict[str, str]:
    """
    Load agent configuration from agent.properties file.

    Args:
        config_file: Path to agent configuration file

    Returns:
        Agent configuration dictionary

    Raises:
        FileNotFoundError: If config file does not exist
        ValueError: If required properties are missing
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Agent config file not found: {config_file}")

    config = ConfigParser()

    try:
        # Read properties file
        with open(config_file, 'r', encoding='utf-8') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        # Required properties
        required_props = ['agent_code', 'agent_type', 'agent_name']
        missing_props = []

        for prop in required_props:
            if not config.has_option('DEFAULT', prop):
                missing_props.append(prop)

        if missing_props:
            raise ValueError(
                f"Missing required properties in {config_file}: "
                f"{', '.join(missing_props)}"
            )

        # Load configuration
        return {
            'agent_code': config.get('DEFAULT', 'agent_code'),
            'agent_type': config.get('DEFAULT', 'agent_type'),
            'agent_name': config.get('DEFAULT', 'agent_name'),
        }

    except Exception as e:
        logger.error(f"Error loading agent config file: {e}")
        raise
