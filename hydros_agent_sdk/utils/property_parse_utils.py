"""Shared helpers for reading typed values from agent properties."""

from typing import Optional

from hydros_agent_sdk.agent_properties import AgentProperties


class PropertyParseUtils:
    """Typed accessors for AgentProperties values."""

    @staticmethod
    def get_int(properties: AgentProperties, name: str, default: Optional[int]) -> int:
        value = properties.get_property(name, default)
        if value is None:
            raise ValueError(f"Missing integer property: {name}")
        return int(value)

    @staticmethod
    def get_float(properties: AgentProperties, name: str, default: Optional[float]) -> float:
        value = properties.get_property(name, default)
        if value is None:
            raise ValueError(f"Missing float property: {name}")
        return float(value)

    @staticmethod
    def get_string(properties: AgentProperties, name: str, default: Optional[str]) -> Optional[str]:
        value = properties.get_property(name, default)
        if value is None:
            return None
        return str(value)

    @staticmethod
    def get_bool(properties: AgentProperties, name: str, default: bool) -> bool:
        value = properties.get_property(name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "on")
        return bool(value)
