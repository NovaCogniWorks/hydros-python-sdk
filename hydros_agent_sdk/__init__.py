"""
Hydros Agent SDK。

Hydros 生态的官方 Python SDK，提供仿真智能体协调和 MQTT 协议支持。
"""

from hydros_agent_sdk.version import SDK_USER_AGENT, __version__, get_sdk_version
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.context_manager import (
    ContextKeyResolver,
    ContextManager,
    HydroModelContext,
    HydroModelContextRepository,
)
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.message_filter import MessageFilter
from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.developer_api import AgentBehavior, AgentExecutionContext, AgentIdentity
from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache
from hydros_agent_sdk.utils.property_parse_utils import PropertyParseUtils
from hydros_agent_sdk.topics import HydrosTopics
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
    generate_agent_instance_id,
    generate_system_command_id,
    generate_agent_command_id,
    generate_coordination_command_id,
    generate_alert_id,
    generate_sim_task_id,
    generate_hydro_event_id,
    generate_mqtt_client_id,
    generate_monitor_rule_id,
    generate_data_series_id,
    generate_sse_session_id,
    generate_user_id,
    MqttMetrics,
    send_metrics,
    send_metrics_batch,
    create_mock_metrics,
)
from hydros_agent_sdk.logging_config import (
    setup_logging,
    LogContext,
    HydrosFormatter,
    # 新 API
    set_biz_scene_instance_id,
    set_biz_component,
    set_hydros_cluster_id,
    set_hydros_node_id,
    get_biz_scene_instance_id,
    get_biz_component,
    get_hydros_cluster_id,
    get_hydros_node_id,
)

# 导入工厂和多智能体支持
from hydros_agent_sdk.factory import BehaviorAgentFactory, HydroAgentFactory, SystemCentralSchedulingAgentFactory
from hydros_agent_sdk.multi_agent import (
    MultiAgentCallback,
)
from hydros_agent_sdk.config_loader import (
    get_default_env_config_path,
    load_env_config,
    load_agent_config,
    load_properties_file,
)
from hydros_agent_sdk.runtime import (
    AgentContext,
    AgentConfigurationService,
    AgentLoggingContextSetter,
    RuntimeEnvSettings,
    ResponseFactory,
    TimeSeriesCache,
    load_runtime_env_settings,
)
from hydros_agent_sdk.transport import (
    InMemoryTransport,
    MqttMetricsPublisher,
    MqttMetricsSubscriber,
    PublishRecord,
    Transport,
)
# 导入错误处理
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
from hydros_agent_sdk.protocol.system_commands import (
    SystemCmd,
    SystemCommand,
    SystemCommandRequest,
    SystemCommandResponse,
)
from hydros_agent_sdk.protocol.hydro_event_type import AgentEventType
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.protocol.agent_commands import (
    HydroCommandReceivedAckReply,
    HydroEventReportRequest,
    HydroEventReportResponse,
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.agent_commands import (
    AgentCommandHandler,
    AgentCommandHandlerRegistry,
    AgentCommandQueueService,
    AgentCommandRuntime,
    AgentCommandClient,
    StationTargetValueCommandBuilder,
)
from hydros_agent_sdk.control_algorithms import (
    ControlActuator,
    ControlActuatorTarget,
    ControlAlgorithm,
    ControlAlgorithmHttpService,
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    ControlValueRange,
    SignalType,
    create_control_algorithm_http_server,
)

__all__ = [
    "__version__",
    "get_sdk_version",
    "SDK_USER_AGENT",

    # 核心客户端和回调
    "SimCoordinationClient",
    "SimCoordinationCallback",
    "ContextManager",
    "ContextKeyResolver",
    "HydroModelContext",
    "HydroModelContextRepository",
    "BaseHydroAgent",
    "AgentBehavior",
    "AgentExecutionContext",
    "AgentIdentity",
    "HydrosTopics",

    # 状态管理
    "AgentStateManager",
    "MessageFilter",

    # 智能体属性
    "AgentProperties",

    # 配置加载
    "AgentConfigLoader",
    "AgentConfiguration",
    "Author",
    "Waterway",
    "MqttBroker",
    "OutputConfig",
    "get_default_env_config_path",
    "load_env_config",
    "load_agent_config",
    "load_properties_file",
    "AgentContext",
    "AgentConfigurationService",
    "AgentLoggingContextSetter",
    "FieldMetricsCache",
    "RuntimeEnvSettings",
    "ResponseFactory",
    "TimeSeriesCache",
    "load_runtime_env_settings",
    "InMemoryTransport",
    "PublishRecord",
    "Transport",
    "MqttMetricsPublisher",
    "MqttMetricsSubscriber",

    # 工厂和多智能体支持
    "generate_agent_instance_id",
    "generate_system_command_id",
    "generate_agent_command_id",
    "generate_coordination_command_id",
    "generate_alert_id",
    "generate_sim_task_id",
    "generate_hydro_event_id",
    "generate_mqtt_client_id",
    "generate_monitor_rule_id",
    "generate_data_series_id",
    "generate_sse_session_id",
    "generate_user_id",
    "HydroAgentFactory",
    "BehaviorAgentFactory",
    "SystemCentralSchedulingAgentFactory",
    "MultiAgentCallback",

    # 错误处理
    "ErrorCode",
    "ErrorCodes",
    "create_error_response",
    "handle_agent_errors",
    "safe_execute",
    "AgentErrorContext",
    "validate_request",

    # 系统指令
    "SystemCmd",
    "SystemCommand",
    "SystemCommandRequest",
    "SystemCommandResponse",
    "AgentEventType",

    # 智能体指令运行时
    "HydroCommandReceivedAckReply",
    "HydroEventReportRequest",
    "HydroEventReportResponse",
    "HydroStationTargetValueRequest",
    "HydroStationTargetValueResponse",
    "DeviceValueTypeEnum",
    "AgentCommandHandler",
    "AgentCommandHandlerRegistry",
    "AgentCommandQueueService",
    "AgentCommandRuntime",
    "AgentCommandClient",
    "StationTargetValueCommandBuilder",

    # 控制算法开发接口
    "ControlAlgorithm",
    "ControlAlgorithmHttpService",
    "ControlAlgorithmRuntime",
    "ControlAlgorithmInput",
    "ControlAlgorithmOutput",
    "ControlAlgorithmContext",
    "ControlSignal",
    "ControlActuator",
    "ControlActuatorTarget",
    "ControlValueRange",
    "ControlTaskType",
    "ControlAlgorithmStatus",
    "SignalType",
    "create_control_algorithm_http_server",

    # 工具类
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

    # 日志配置
    "setup_logging",
    "LogContext",
    "HydrosFormatter",
    # 新 API
    "set_biz_scene_instance_id",
    "set_biz_component",
    "set_hydros_cluster_id",
    "set_hydros_node_id",
    "get_biz_scene_instance_id",
    "get_biz_component",
    "get_hydros_cluster_id",
    "get_hydros_node_id",

]
