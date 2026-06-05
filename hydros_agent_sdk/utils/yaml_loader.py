"""
YAML 加载工具。

本模块提供从 URL 或本地文件加载 YAML 内容的工具类。它返回未经 Pydantic
模型校验的原始字典数据，适用于通用 YAML 解析场景。

使用示例：
    # 从 URL 加载
    config = YamlLoader.from_url("http://example.com/config.yaml")

    # 从文件加载
    config = YamlLoader.from_file("/path/to/config.yaml")

    # 访问配置值
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
    通用 YAML 加载工具。

    该类提供静态方法，用于从 URL 或本地文件路径加载 YAML 内容，
    并解析为字典对象。

    与 AgentConfigLoader 不同，该类返回未经 Pydantic 模型校验的原始字典数据，
    在通用 YAML 解析场景中更灵活。
    """

    @staticmethod
    def from_url(url: str, timeout: int = 30) -> Dict[str, Any]:
        """
        从 URL 加载 YAML 配置。

        Args:
            url: 获取 YAML 内容的 URL
            timeout: 请求超时时间，单位秒（默认 30）

        Returns:
            包含已解析 YAML 数据的字典

        Raises:
            ImportError: 未安装 PyYAML 时抛出
            URLError: URL 无法访问时抛出
            HTTPError: HTTP 请求失败时抛出
            ValueError: YAML 内容无效时抛出
        """
        if yaml is None:
            raise ImportError(
                "PyYAML is required to load YAML files. "
                "Install it with: pip install pyyaml"
            )

        logger.info(f"Loading YAML from URL: {url}")

        try:
            # 编码 URL 以处理非 ASCII 字符（例如中文字符）。
            # 将 URL 拆分为多个部分，只编码 path 部分。
            parsed = urlparse(url)

            # 编码 path 组件，同时保留已经编码的字符。
            encoded_path = quote(parsed.path, safe='/:@!$&\'()*+,;=')

            # 使用编码后的 path 重建 URL。
            encoded_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                encoded_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))

            logger.debug(f"Encoded URL: {encoded_url}")

            # 创建带有合适 header 的请求。
            request = Request(encoded_url)
            request.add_header('User-Agent', 'Hydros-Agent-SDK/0.1.4')

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
        从本地文件加载 YAML 配置。

        Args:
            file_path: YAML 文件路径
            encoding: 文件编码（默认 'utf-8'）

        Returns:
            包含已解析 YAML 数据的字典

        Raises:
            ImportError: 未安装 PyYAML 时抛出
            FileNotFoundError: 文件不存在时抛出
            ValueError: YAML 内容无效时抛出
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
        将 YAML 内容解析为字典。

        Args:
            yaml_content: 字符串形式的 YAML 内容

        Returns:
            包含已解析 YAML 数据的字典

        Raises:
            ImportError: 未安装 PyYAML 时抛出
            ValueError: YAML 内容无效时抛出
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
        使用点号路径从字典中获取嵌套值。

        Args:
            data: 要查找的字典
            key_path: 点号分隔的键路径（例如 "nested.key.path"）
            default: 未找到键时返回的默认值

        Returns:
            键路径对应的值或默认值

        示例：
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
