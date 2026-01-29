"""
Agent Configuration Loader

This module provides functionality to load and parse agent configuration YAML files
from URLs or local files. It defines Pydantic models for the configuration structure
and provides convenient accessor methods for common configuration values.

Example usage:
    # Load from URL
    config = AgentConfigLoader.from_url("http://example.com/agent_config.yaml")

    # Access configuration values
    agent_code = config.get_agent_code()
    modeling_url = config.get_hydros_objects_modeling_url()

    # Access nested properties
    step_resolution = config.properties.step_resolution
    mqtt_host = config.properties.output_config.mqtt_broker.mqtt_host
"""

import logging
from typing import Optional, Any, Dict
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
    """Author information for the agent configuration."""
    user_name: str


class Waterway(HydroBaseModel):
    """Waterway information."""
    waterway_id: int
    waterway_name: str


class MqttBroker(HydroBaseModel):
    """MQTT broker configuration."""
    mqtt_host: str
    mqtt_port: int
    server_uri: str


class OutputConfig(HydroBaseModel):
    """Output configuration for agent results."""
    output_mode: str
    mqtt_broker: MqttBroker
    mqtt_topic: str


class AgentProperties(HydroBaseModel):
    """Agent properties containing business logic configuration."""
    biz_start_time: Optional[str] = None
    step_resolution: Optional[int] = None
    total_steps: Optional[int] = None
    driven_by_coordinator: Optional[bool] = None
    hydro_environment_type: Optional[str] = None
    hydros_objects_modeling_url: Optional[str] = None
    idz_config_url: Optional[str] = None
    time_series_config_url: Optional[str] = None
    output_config: Optional[OutputConfig] = None

    # Allow additional properties not explicitly defined
    class Config:
        extra = "allow"


class AgentConfiguration(HydroBaseModel):
    """
    Complete agent configuration model.

    This model represents the full structure of an agent configuration YAML file,
    including agent metadata, waterway information, and business properties.
    """
    agent_code: str
    agent_type: str
    agent_name: str
    agent_configuration_url: Optional[str] = None
    version: str
    release_at: str
    author: Author
    description: str
    waterway: Waterway
    properties: AgentProperties

    def get_agent_code(self) -> str:
        """
        Get the agent code.

        Returns:
            The agent code string
        """
        return self.agent_code

    def get_hydros_objects_modeling_url(self) -> Optional[str]:
        """
        Get the Hydros objects modeling URL from properties.

        Returns:
            The modeling URL if present, None otherwise
        """
        return self.properties.hydros_objects_modeling_url if self.properties else None

    def get_idz_config_url(self) -> Optional[str]:
        """
        Get the IDZ configuration URL from properties.

        Returns:
            The IDZ config URL if present, None otherwise
        """
        return self.properties.idz_config_url if self.properties else None

    def get_time_series_config_url(self) -> Optional[str]:
        """
        Get the time series configuration URL from properties.

        Returns:
            The time series config URL if present, None otherwise
        """
        return self.properties.time_series_config_url if self.properties else None

    def get_mqtt_broker_config(self) -> Optional[MqttBroker]:
        """
        Get the MQTT broker configuration from output config.

        Returns:
            MqttBroker object if present, None otherwise
        """
        if self.properties and self.properties.output_config:
            return self.properties.output_config.mqtt_broker
        return None

    def get_property(self, key: str, default: Any = None) -> Any:
        """
        Get a property value by key with optional default.

        Args:
            key: Property key name (snake_case)
            default: Default value if property not found

        Returns:
            Property value or default
        """
        if not self.properties:
            return default
        return getattr(self.properties, key, default)


class AgentConfigLoader:
    """
    Loader class for agent configuration files.

    This class provides static methods to load agent configurations from URLs
    or local file paths, and parse them into structured AgentConfiguration objects.
    """

    @staticmethod
    def from_url(url: str, timeout: int = 30) -> AgentConfiguration:
        """
        Load agent configuration from a URL.

        Args:
            url: The URL to fetch the YAML configuration from
            timeout: Request timeout in seconds (default: 30)

        Returns:
            AgentConfiguration object with parsed configuration

        Raises:
            ImportError: If PyYAML is not installed
            URLError: If the URL cannot be accessed
            HTTPError: If the HTTP request fails
            ValueError: If the YAML content is invalid
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to load agent configurations. "
                "Install it with: pip install pyyaml"
            )

        logger.info(f"Loading agent configuration from URL: {url}")

        try:
            # Encode URL to handle non-ASCII characters (e.g., Chinese characters)
            # Split URL into parts and encode only the path part
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(url)

            # Encode the path component while preserving already-encoded characters
            encoded_path = quote(parsed.path, safe='/:@!$&\'()*+,;=')

            # Reconstruct the URL with encoded path
            encoded_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                encoded_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))

            logger.debug(f"Encoded URL: {encoded_url}")

            # Create request with proper headers
            request = Request(encoded_url)
            request.add_header('User-Agent', 'Hydros-Agent-SDK/0.1.3')

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
        Load agent configuration from a local file.

        Args:
            file_path: Path to the YAML configuration file

        Returns:
            AgentConfiguration object with parsed configuration

        Raises:
            ImportError: If PyYAML is not installed
            FileNotFoundError: If the file does not exist
            ValueError: If the YAML content is invalid
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
        Parse agent configuration from a YAML string.

        Args:
            yaml_content: YAML content as a string

        Returns:
            AgentConfiguration object with parsed configuration

        Raises:
            ImportError: If PyYAML is not installed
            ValueError: If the YAML content is invalid
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
        Create agent configuration from a dictionary.

        Args:
            data: Dictionary containing configuration data

        Returns:
            AgentConfiguration object with parsed configuration
        """
        return AgentConfiguration(**data)
