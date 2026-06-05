"""
智能体配置加载器。

本模块提供从 URL 或本地文件加载并解析智能体配置 YAML 的能力。
它定义配置结构对应的 Pydantic 模型，并提供常用配置值的便捷访问方法。

使用示例：
    # 从 URL 加载
    config = AgentConfigLoader.from_url("http://example.com/agent_config.yaml")

    # 访问配置值
    agent_code = config.get_agent_code()
    modeling_url = config.get_hydros_objects_modeling_url()

    # 访问嵌套属性
    step_resolution = config.properties.step_resolution
    mqtt_host = config.properties.output_config.mqtt_broker.mqtt_host
"""

import logging
from datetime import date, datetime
from typing import Optional, Any, Dict, List
from pydantic import ConfigDict, Field, field_validator
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote

try:
    import yaml
except ImportError:
    yaml = None

from hydros_agent_sdk.protocol.base import HydroBaseModel

logger = logging.getLogger(__name__)


class Author(HydroBaseModel):
    """智能体配置的作者信息。"""
    user_name: str


class Waterway(HydroBaseModel):
    """水系信息。"""
    waterway_id: int
    waterway_name: str


class MqttBroker(HydroBaseModel):
    """用于 MQTT broker 的配置。"""
    mqtt_host: str
    mqtt_port: int
    server_uri: str


class OutputConfig(HydroBaseModel):
    """智能体结果输出配置。"""
    output_mode: str
    mqtt_broker: MqttBroker
    mqtt_topic: str


class AgentProperties(HydroBaseModel):
    """包含业务逻辑配置的智能体属性。"""
    model_config = ConfigDict(extra='allow')

    driven_by_coordinator: Optional[bool] = None
    hydro_environment_type: Optional[str] = None
    hydros_objects_modeling_url: Optional[str] = None


class AgentComponentConfiguration(HydroBaseModel):
    """嵌套在智能体配置下的组件配置。"""
    model_config = ConfigDict(extra='allow')

    component_id: Optional[str] = None
    component_name: Optional[str] = None
    enabled: bool = True
    properties: Optional[AgentProperties] = None


class AgentConfiguration(HydroBaseModel):
    """
    完整智能体配置模型。

    该模型表示智能体配置 YAML 文件的完整结构，
    包括智能体元数据、水系信息和业务属性。
    """
    model_config = ConfigDict(extra='allow')

    agent_code: str
    agent_type: str
    agent_name: str
    agent_configuration_url: Optional[str] = None
    version: Optional[str] = None
    release_at: Optional[str] = None
    author: Optional[Author] = None
    description: Optional[str] = None
    waterway: Optional[Waterway] = None
    properties: AgentProperties
    components: List[AgentComponentConfiguration] = Field(default_factory=list)

    @field_validator('release_at', mode='before')
    @classmethod
    def normalize_release_at(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat(sep=' ')
        if isinstance(value, date):
            return value.isoformat()
        return value

    def get_agent_code(self) -> str:
        """
        获取 agent code。

        Returns:
            agent code 字符串
        """
        return self.agent_code

    def get_hydros_objects_modeling_url(self) -> Optional[str]:
        """
        从 properties 获取 Hydros 对象建模 URL。

        Returns:
            存在时返回建模 URL，否则返回 None
        """
        return self.properties.hydros_objects_modeling_url if self.properties else None



    def get_property(self, key: str, default: Any = None) -> Any:
        """
        按 key 获取属性值，并支持可选默认值。

        Args:
            key: 属性 key 名称（snake_case）
            default: 属性不存在时使用的默认值

        Returns:
            属性值或默认值
        """
        if not self.properties:
            return default
        return getattr(self.properties, key, default)


class AgentConfigLoader:
    """
    智能体配置文件加载类。

    该类提供静态方法，从 URL 或本地文件路径加载智能体配置，
    并解析为结构化的 AgentConfiguration 对象。
    """

    @staticmethod
    def from_url(url: str, timeout: int = 30) -> AgentConfiguration:
        """
        从 URL 加载智能体配置。

        Args:
            url: 获取 YAML 配置的 URL
            timeout: 请求超时时间，单位秒（默认 30）

        Returns:
            包含已解析配置的 AgentConfiguration 对象

        Raises:
            ImportError: 未安装 PyYAML 时抛出
            URLError: URL 无法访问时抛出
            HTTPError: HTTP 请求失败时抛出
            ValueError: YAML 内容无效时抛出
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to load agent configurations. "
                "Install it with: pip install pyyaml"
            )

        logger.info(f"Loading agent configuration from URL: {url}")

        try:
            # 编码 URL 以处理非 ASCII 字符（例如中文字符）
            # 将 URL 拆分为多个部分，只编码 path 部分
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(url)

            # 编码 path 组件，同时保留已经编码的字符
            encoded_path = quote(parsed.path, safe='/:@!$&\'()*+,;=')

            # 使用编码后的 path 重建 URL
            encoded_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                encoded_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))

            logger.debug(f"Encoded URL: {encoded_url}")

            # 创建带有合适 header 的请求
            request = Request(encoded_url)
            request.add_header('User-Agent', 'Hydros-Agent-SDK/0.1.5')

            with urlopen(request, timeout=timeout) as response:
                content = response.read().decode('utf-8')
                return AgentConfigLoader.from_yaml_string(content)
        except HTTPError as e:
            logger.error(f"HTTP error loading configuration from {url}: {e.code} {e.reason}")
            raise
        except URLError as e:
            logger.error(f"URL error loading configuration from {url}: {e.reason}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error loading configuration from {url}: {e}")
            raise

    @staticmethod
    def from_file(file_path: str) -> AgentConfiguration:
        """
        从本地文件加载智能体配置。

        Args:
            file_path: YAML 配置文件路径

        Returns:
            包含已解析配置的 AgentConfiguration 对象

        Raises:
            ImportError: 未安装 PyYAML 时抛出
            FileNotFoundError: 文件不存在时抛出
            ValueError: YAML 内容无效时抛出
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to load agent configurations. "
                "Install it with: pip install pyyaml"
            )

        logger.info(f"Loading agent configuration from file: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return AgentConfigLoader.from_yaml_string(content)
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error loading configuration from file {file_path}: {e}")
            raise

    @staticmethod
    def from_yaml_string(yaml_content: str) -> AgentConfiguration:
        """
        从 YAML 字符串解析智能体配置。

        Args:
            yaml_content: YAML 字符串内容

        Returns:
            包含已解析配置的 AgentConfiguration 对象

        Raises:
            ImportError: 未安装 PyYAML 时抛出
            ValueError: YAML 内容无效时抛出
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to load agent configurations. "
                "Install it with: pip install pyyaml"
            )

        try:
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                raise ValueError("YAML content must be a dictionary")

            return AgentConfiguration(**data)
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error: {e}")
            raise ValueError(f"Invalid YAML content: {e}")
        except Exception as e:
            logger.error(f"Error parsing configuration: {e}")
            raise ValueError(f"Failed to parse agent configuration: {e}")

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> AgentConfiguration:
        """
        从字典创建智能体配置。

        Args:
            data: 包含配置数据的字典

        Returns:
            包含已解析配置的 AgentConfiguration 对象
        """
        return AgentConfiguration(**data)
