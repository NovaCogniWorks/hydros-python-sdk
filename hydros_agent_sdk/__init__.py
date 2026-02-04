"""
Hydros Agent SDK

Official Python SDK for the Hydros ecosystem, providing simulation agent
coordination and MQTT protocol support.
"""

from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
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
    # New API
    set_biz_scene_instance_id,
    set_biz_component,
    set_hydros_cluster_id,
    set_hydros_node_id,
    get_biz_scene_instance_id,
    get_biz_component,
    get_hydros_cluster_id,
    get_hydros_node_id,
    # Deprecated API (for backward compatibility)
    set_task_id,
    set_agent_id,
    set_node_id,
    get_task_id,
    get_agent_id,
    get_node_id,
)

# Import specialized agent types
from hydros_agent_sdk.agents import (
    TickableAgent,
    OntologySimulationAgent,
    TwinsSimulationAgent,
    ModelCalculationAgent,
    CentralSchedulingAgent,
)

# Import factory and multi-agent support
from hydros_agent_sdk.factory import (
    generate_agent_instance_id,
    HydroAgentFactory,
)
from hydros_agent_sdk.multi_agent import (
    MultiAgentCallback,
)
from hydros_agent_sdk.config_loader import (
    load_env_config,
    load_agent_config,
    load_properties_file,
)

# Import error handling
from hydros_agent_sdk.error_codes import (
    ErrorCode,
    ErrorCodes,
    create_error_response,
)
from hydros_agent_sdk.error_handling import (
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
    validate_request,
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
    "load_env_config",
    "load_agent_config",
    "load_properties_file",

    # Factory and multi-agent support
    "generate_agent_instance_id",
    "HydroAgentFactory",
    "MultiAgentCallback",

    # Error handling
    "ErrorCode",
    "ErrorCodes",
    "create_error_response",
    "handle_agent_errors",
    "safe_execute",
    "AgentErrorContext",
    "validate_request",

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
    # New API
    "set_biz_scene_instance_id",
    "set_biz_component",
    "set_hydros_cluster_id",
    "set_hydros_node_id",
    "get_biz_scene_instance_id",
    "get_biz_component",
    "get_hydros_cluster_id",
    "get_hydros_node_id",
    # Deprecated API (for backward compatibility)
    "set_task_id",
    "set_agent_id",
    "set_node_id",
    "get_task_id",
    "get_agent_id",
    "get_node_id",

    # Specialized agent types
    "TickableAgent",
    "OntologySimulationAgent",
    "TwinsSimulationAgent",
    "ModelCalculationAgent",
    "CentralSchedulingAgent",
]
