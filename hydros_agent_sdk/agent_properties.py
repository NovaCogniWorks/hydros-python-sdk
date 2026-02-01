"""
Agent Properties

This module provides the AgentProperties class that matches the Java implementation.
It's essentially a dictionary with typed accessor methods for common property types.
"""

from typing import Any, Optional


class AgentProperties(dict):
    """
    Agent properties dictionary with typed accessor methods.

    This class matches the Java implementation:
    com.hydros.agent.configuration.base.AgentProperties

    It extends dict to allow flexible key-value storage while providing
    typed accessor methods for safe property retrieval.
    """

    def get_property_as_integer(self, property_name: str) -> int:
        """
        Get a property value as an integer.

        Args:
            property_name: The property key name

        Returns:
            The property value as an integer

        Raises:
            KeyError: If property not found
            ValueError: If property cannot be converted to integer
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
        Get a property value as a string.

        Args:
            property_name: The property key name

        Returns:
            The property value as a string

        Raises:
            KeyError: If property not found
            ValueError: If property cannot be converted to string
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
        Get a property value as a float.

        Args:
            property_name: The property key name

        Returns:
            The property value as a float

        Raises:
            KeyError: If property not found
            ValueError: If property cannot be converted to float
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
        Get a property value as a boolean.

        Args:
            property_name: The property key name

        Returns:
            The property value as a boolean

        Raises:
            KeyError: If property not found
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
        Get a property value with optional default.

        Args:
            property_name: The property key name
            default: Default value if property not found

        Returns:
            The property value or default
        """
        return self.get(property_name, default)
