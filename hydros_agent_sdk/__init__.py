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
from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.agent_config import (
    AgentConfigLoader,
    AgentConfiguration,
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
    MqttMetrics,
    send_metrics,
    send_metrics_batch,
    create_mock_metrics,
)
from hydros_agent_sdk.logging_config import (
    setup_logging,
    LogContext,
    HydrosFormatter,
    set_task_id,
    set_biz_component,
    set_log_type,
    set_log_content,
    set_node_id,
    get_task_id,
    get_biz_component,
    get_log_type,
    get_log_content,
    get_node_id,
)

__version__ = "0.1.3"

__all__ = [
    # Core client and callback
    "SimCoordinationClient",
    "SimCoordinationCallback",
    "BaseHydroAgent",

    # State management
    "AgentStateManager",
    "MessageFilter",

    # MQTT client
    "HydrosMqttClient",

    # Agent properties
    "AgentProperties",

    # Configuration loading
    "AgentConfigLoader",
    "AgentConfiguration",
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
    "MqttMetrics",
    "send_metrics",
    "send_metrics_batch",
    "create_mock_metrics",

    # Logging configuration
    "setup_logging",
    "LogContext",
    "HydrosFormatter",
    "set_task_id",
    "set_biz_component",
    "set_log_type",
    "set_log_content",
    "set_node_id",
    "get_task_id",
    "get_biz_component",
    "get_log_type",
    "get_log_content",
    "get_node_id",
]
