"""
Hydros Agent SDK

Official Python SDK for the Hydros ecosystem, providing simulation agent
coordination and MQTT protocol support.
"""

from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.callback import SimCoordinationCallback
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.message_filter import MessageFilter
from hydros_agent_sdk.mqtt import HydrosMqttClient
from hydros_agent_sdk.agent_config import (
    AgentConfigLoader,
    AgentConfiguration,
    AgentProperties,
    Author,
    Waterway,
    MqttBroker,
    OutputConfig,
)
from hydros_agent_sdk.utils import (
    HydroObjectUtilsV2,
    WaterwayTopology,
    TopHydroObject,
    SimpleChildObject,
    HydroObjectType,
    MetricsCodes,
)

__version__ = "0.1.3"

__all__ = [
    # Core client and callback
    "SimCoordinationClient",
    "SimCoordinationCallback",

    # State management
    "AgentStateManager",
    "MessageFilter",

    # MQTT client
    "HydrosMqttClient",

    # Configuration loading
    "AgentConfigLoader",
    "AgentConfiguration",
    "AgentProperties",
    "Author",
    "Waterway",
    "MqttBroker",
    "OutputConfig",

    # Utility classes
    "HydroObjectUtilsV2",
    "WaterwayTopology",
    "TopHydroObject",
    "SimpleChildObject",
    "HydroObjectType",
    "MetricsCodes",
]
