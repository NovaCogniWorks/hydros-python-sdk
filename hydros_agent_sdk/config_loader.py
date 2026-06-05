"""
Hydros Agent SDK 配置加载器。

本模块提供从 .properties 文件加载环境配置和智能体配置的工具。
"""

import os
import logging
from typing import Dict, Optional
from configparser import ConfigParser

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILE_NAME = "env.properties"


def get_default_env_config_path() -> str:
    """返回当前工作目录下默认 env.properties 路径。"""
    return os.path.abspath(DEFAULT_ENV_FILE_NAME)


def _find_nearest_env_config(start_dir: str) -> Optional[str]:
    current_dir = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(current_dir, DEFAULT_ENV_FILE_NAME)
        if os.path.exists(candidate):
            return candidate

        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            return None
        current_dir = parent_dir


def load_env_config(env_file: str = "./env.properties") -> Dict[str, str]:
    """
    从 env.properties 文件加载环境配置。

    该函数加载全部智能体共享的环境配置。如果未显式提供 mqtt_topic，
    会根据 hydros_cluster_id 自动构造。

    Args:
        env_file: 环境配置文件路径。默认相对路径会从当前目录及其父目录查找。

    Returns:
        环境配置字典

    Raises:
        FileNotFoundError: env.properties 文件不存在时抛出
        ValueError: 缺少必填属性时抛出
    """
    if not os.path.isabs(env_file):
        requested_env_file = os.path.abspath(env_file)
        is_default_request = os.path.normpath(env_file) == DEFAULT_ENV_FILE_NAME

        if os.path.exists(requested_env_file):
            env_file = requested_env_file
        elif is_default_request:
            nearest_env_file = _find_nearest_env_config(os.getcwd())
            env_file = nearest_env_file or requested_env_file
        else:
            env_file = requested_env_file

    # 检查文件是否存在
    if not os.path.exists(env_file):
        raise FileNotFoundError(
            f"Environment configuration file not found: {env_file}\n"
            f"Please create env.properties in the current application directory or pass an absolute path."
        )

    logger.info(f"Loading environment config from: {env_file}")

    # 加载 properties
    config = load_properties_file(env_file)

    # 未提供 mqtt_topic 时根据 hydros_cluster_id 自动生成
    if 'mqtt_topic' not in config or not config['mqtt_topic']:
        if 'hydros_cluster_id' in config and config['hydros_cluster_id']:
            config['mqtt_topic'] = f"/hydros/commands/coordination/{config['hydros_cluster_id']}"
            logger.info(f"Auto-generated mqtt_topic: {config['mqtt_topic']}")

    # 校验必填属性
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
    从 .properties 文件加载属性。

    Args:
        file_path: properties 文件路径

    Returns:
        属性字典

    Raises:
        FileNotFoundError: 文件不存在时抛出
        RuntimeError: 文件无法解析时抛出
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Properties file not found: {file_path}")

    config = ConfigParser()

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        result = {}
        # 从 DEFAULT 段加载全部属性
        for key, value in config.items('DEFAULT'):
            if value:
                result[key] = value

        return result

    except Exception as e:
        logger.error(f"Error loading properties file {file_path}: {e}")
        raise RuntimeError(f"Error loading properties file {file_path}: {e}")


def load_agent_config(config_file: str) -> Dict[str, str]:
    """
    从 agent.properties 文件加载智能体配置。

    Args:
        config_file: 智能体配置文件路径

    Returns:
        智能体配置字典

    Raises:
        FileNotFoundError: 配置文件不存在时抛出
        ValueError: 缺少必填属性时抛出
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Agent config file not found: {config_file}")

    config = ConfigParser()

    try:
        # 读取 properties 文件
        with open(config_file, 'r', encoding='utf-8') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        # 必填属性
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

        # 加载配置
        return {
            'agent_code': config.get('DEFAULT', 'agent_code'),
            'agent_type': config.get('DEFAULT', 'agent_type'),
            'agent_name': config.get('DEFAULT', 'agent_name'),
        }

    except Exception as e:
        logger.error(f"Error loading agent config file: {e}")
        raise
