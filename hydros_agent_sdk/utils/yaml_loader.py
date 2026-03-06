"""
YAML Loader Utility

This module provides a utility class for loading YAML content from URLs or local files.
It returns raw dictionary data without Pydantic model validation, making it suitable
for generic YAML parsing use cases.

Example usage:
    # Load from URL
    config = YamlLoader.from_url("http://example.com/config.yaml")

    # Load from file
    config = YamlLoader.from_file("/path/to/config.yaml")

    # Access configuration values
    value = config.get("key")
    nested_value = config.get("nested.key")
"""

import logging
from typing import Any, Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote, urlparse, urlunparse

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)


class YamlLoader:
    """
    Generic YAML loader utility.

    This class provides static methods to load YAML content from URLs
    or local file paths, and parse them into dictionary objects.

    Unlike AgentConfigLoader, this class returns raw dictionary data
    without Pydantic model validation, making it more flexible for
    generic YAML parsing scenarios.
    """

    @staticmethod
    def from_url(url: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Load YAML configuration from a URL.

        Args:
            url: The URL to fetch the YAML content from
            timeout: Request timeout in seconds (default: 30)

        Returns:
            Dictionary containing parsed YAML data

        Raises:
            ImportError: If PyYAML is not installed
            URLError: If the URL cannot be accessed
            HTTPError: If the HTTP request fails
            ValueError: If the YAML content is invalid
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to load YAML files. "
                "Install it with: pip install pyyaml"
            )

        logger.info(f"Loading YAML from URL: {url}")

        try:
            # Encode URL to handle non-ASCII characters (e.g., Chinese characters)
            # Split URL into parts and encode only the path part
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
                return YamlLoader.from_yaml_string(content)
        except HTTPError as e:
            logger.error(f"HTTP error loading YAML from {url}: {e.code} {e.reason}")
            raise
        except URLError as e:
            logger.error(f"URL error loading YAML from {url}: {e.reason}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error loading YAML from {url}: {e}")
            raise

    @staticmethod
    def from_file(file_path: str, encoding: str = 'utf-8') -> Dict[str, Any]:
        """
        Load YAML configuration from a local file.

        Args:
            file_path: Path to the YAML file
            encoding: File encoding (default: 'utf-8')

        Returns:
            Dictionary containing parsed YAML data

        Raises:
            ImportError: If PyYAML is not installed
            FileNotFoundError: If the file does not exist
            ValueError: If the YAML content is invalid
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to load YAML files. "
                "Install it with: pip install pyyaml"
            )

        logger.info(f"Loading YAML from file: {file_path}")

        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
                return YamlLoader.from_yaml_string(content)
        except FileNotFoundError:
            logger.error(f"YAML file not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error loading YAML from file {file_path}: {e}")
            raise

    @staticmethod
    def from_yaml_string(yaml_content: str) -> Dict[str, Any]:
        """
        Parse YAML content into a dictionary.

        Args:
            yaml_content: YAML content as a string

        Returns:
            Dictionary containing parsed YAML data

        Raises:
            ImportError: If PyYAML is not installed
            ValueError: If the YAML content is invalid
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to parse YAML content. "
                "Install it with: pip install pyyaml"
            )

        try:
            data = yaml.safe_load(yaml_content)
            if data is None:
                return {}
            if not isinstance(data, dict):
                raise ValueError(
                    f"YAML content must be a dictionary, got {type(data).__name__}"
                )
            return data
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error: {e}")
            raise ValueError(f"Invalid YAML content: {e}")
        except Exception as e:
            logger.error(f"Error parsing YAML: {e}")
            raise ValueError(f"Failed to parse YAML: {e}")

    @staticmethod
    def get_nested(data: Dict[str, Any], key_path: str, default: Any = None) -> Any:
        """
        Get a nested value from a dictionary using dot notation.

        Args:
            data: Dictionary to search
            key_path: Dot-separated key path (e.g., "nested.key.path")
            default: Default value if key not found

        Returns:
            Value at the key path or default

        Example:
            >>> data = {"config": {"database": {"host": "localhost"}}}
            >>> YamlLoader.get_nested(data, "config.database.host")
            'localhost'
        """
        keys = key_path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
