"""
智能体属性。

本模块提供与 Java 实现对齐的 AgentProperties 类。
它本质上是一个字典，并为常见属性类型提供类型化访问方法。
"""

from typing import Any, Optional


class AgentProperties(dict):
    """
    带类型化访问方法的智能体属性字典。

    该类对应 Java 实现：
    com.hydros.agent.configuration.base.AgentProperties

    它扩展 dict 以支持灵活的键值存储，同时提供类型化访问方法，
    便于安全读取属性。
    """

    def get_property_as_integer(self, property_name: str) -> int:
        """
        将属性值读取为整数。

        Args:
            property_name: 属性键名

        Returns:
            整数形式的属性值

        Raises:
            KeyError: 未找到属性时抛出
            ValueError: 属性无法转换为整数时抛出
        """
        value = self.get(property_name)
        if value is None:
            raise KeyError(f"Property not found: {property_name}")

        try:
            if isinstance(value, (int, float)):
                return int(value)
            return int(str(value))
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Property '{property_name}' cannot be converted to integer: {value}"
            ) from e

    def get_property_as_string(self, property_name: str) -> str:
        """
        将属性值读取为字符串。

        Args:
            property_name: 属性键名

        Returns:
            字符串形式的属性值

        Raises:
            KeyError: 未找到属性时抛出
            ValueError: 属性无法转换为字符串时抛出
        """
        value = self.get(property_name)
        if value is None:
            raise KeyError(f"Property not found: {property_name}")

        if isinstance(value, str):
            return value

        try:
            return str(value)
        except Exception as e:
            raise ValueError(
                f"Property '{property_name}' cannot be converted to string: {value}"
            ) from e

    def get_property_as_float(self, property_name: str) -> float:
        """
        将属性值读取为浮点数。

        Args:
            property_name: 属性键名

        Returns:
            浮点数形式的属性值

        Raises:
            KeyError: 未找到属性时抛出
            ValueError: 属性无法转换为浮点数时抛出
        """
        value = self.get(property_name)
        if value is None:
            raise KeyError(f"Property not found: {property_name}")

        try:
            if isinstance(value, (int, float)):
                return float(value)
            return float(str(value))
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Property '{property_name}' cannot be converted to float: {value}"
            ) from e

    def get_property_as_bool(self, property_name: str) -> bool:
        """
        将属性值读取为布尔值。

        Args:
            property_name: 属性键名

        Returns:
            布尔形式的属性值

        Raises:
            KeyError: 未找到属性时抛出
        """
        value = self.get(property_name)
        if value is None:
            raise KeyError(f"Property not found: {property_name}")

        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.lower() in ('true', 'yes', '1', 'on')

        return bool(value)

    def get_property(self, property_name: str, default: Any = None) -> Any:
        """
        获取属性值，并支持可选默认值。

        Args:
            property_name: 属性键名
            default: 未找到属性时返回的默认值

        Returns:
            属性值或默认值
        """
        return self.get(property_name, default)
