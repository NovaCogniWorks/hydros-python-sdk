"""
Hydros Agent SDK 错误码。

本模块提供错误码定义和消息格式化工具，与 hydros-common 中的
Java ErrorCodes 实现保持一致。

用法：
    from hydros_agent_sdk.error_codes import ErrorCodes

    # 格式化错误消息
    error_msg = ErrorCodes.SYSTEM_ERROR.format_message("NetworkError", "Connection timeout")

    # 在响应中使用
    response = SimTaskInitResponse(
        command_status=CommandStatus.FAILED,
        error_code=ErrorCodes.SYSTEM_ERROR.code,
        error_message=error_msg,
        ...
    )
"""

from typing import Any


class ErrorCode:
    """
    带消息模板的错误码。

    该类表示一个错误码及其关联的消息模板，并提供消息格式化能力。

    Attributes:
        code: 错误码字符串（例如 "SYSTEM_ERROR"）
        message_template: 带占位符的消息模板（例如 "Error: {0}"）
    """

    def __init__(self, code: str, message_template: str):
        """
        初始化错误码。

        Args:
            code: 错误码字符串
            message_template: 带 {0}、{1} 等占位符的消息模板
        """
        self.code = code
        self.message_template = message_template

    def format_message(self, *args: Any) -> str:
        """
        使用参数格式化错误消息。

        该方法会用传入参数替换消息模板中的 {0}、{1} 等占位符。

        Args:
            *args: 写入消息模板的参数

        Returns:
            格式化后的错误消息

        示例：
            >>> error = ErrorCode("TEST_ERROR", "Error: {0}, detail: {1}")
            >>> error.format_message("Connection failed", "Timeout")
            'Error: Connection failed, detail: Timeout'
        """
        try:
            # 使用传入参数替换 {0}、{1} 等占位符
            message = self.message_template
            for i, arg in enumerate(args):
                message = message.replace(f"{{{i}}}", str(arg))
            return message
        except Exception as e:
            # 兜底：返回带错误信息的模板
            return f"{self.message_template} (format error: {e})"

    def __str__(self) -> str:
        """错误码的字符串表示。"""
        return f"ErrorCode({self.code})"

    def __repr__(self) -> str:
        """错误码的详细表示。"""
        return f"ErrorCode(code='{self.code}', template='{self.message_template}')"


class ErrorCodes:
    """
    Hydros Agent SDK 错误码定义。

    该类提供静态错误码定义，并与 com.hydros.common.ErrorCodes 中的
    Java 实现保持一致。

    核心错误码：
    - SYSTEM_ERROR: 未知系统故障
    - INVALID_PARAMS: 参数无效
    - CONFIGURATION_LOAD_FAILURE: 配置加载失败
    - DATA_SERIALIZATION_FAILURE: 数据序列化失败

    智能体相关错误码：
    - AGENT_INIT_FAILURE: 智能体初始化失败
    - AGENT_TICK_FAILURE: 智能体 tick 执行失败
    - AGENT_TERMINATE_FAILURE: 智能体终止失败
    - TIME_SERIES_UPDATE_FAILURE: 时序数据更新失败
    - TOPOLOGY_LOAD_FAILURE: 拓扑加载失败
    - SIMULATION_EXECUTION_FAILURE: 仿真执行失败

    用法：
        # 获取错误码并格式化消息
        error_code = ErrorCodes.SYSTEM_ERROR.code
        error_message = ErrorCodes.SYSTEM_ERROR.format_message("NetworkError", "Connection timeout")

        # 在响应中使用
        response = TickCmdResponse(
            command_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            ...
        )
    """

    # ========== 核心系统错误 ==========

    SYSTEM_ERROR = ErrorCode(
        "SYSTEM_ERROR",
        "Unknown system failure happens, cause: {0}-{1}"
    )

    INVALID_PARAMS = ErrorCode(
        "INVALID_PARAMS",
        "Invalid parameters: {0}"
    )

    ACCESS_UNAUTHORIZED = ErrorCode(
        "ACCESS_UNAUTHORIZED",
        "Unauthorized access request, please contact technical support"
    )

    FOR_FUTURE_IMPLEMENTING = ErrorCode(
        "FOR_FUTURE_IMPLEMENTING",
        "Feature to be implemented in the future: {0}"
    )

    # ========== 配置错误 ==========

    CONFIGURATION_LOAD_FAILURE = ErrorCode(
        "CONFIGURATION_LOAD_FAILURE",
        "Configuration load failure: {0}, {1}"
    )

    DATA_SERIALIZATION_FAILURE = ErrorCode(
        "DATA_SERIALIZATION_FAILURE",
        "Data serialization failure: {0}, {1}"
    )

    DEPLOY_ENV_ERROR = ErrorCode(
        "DEPLOY_ENV_ERROR",
        "Deployment environment information missing: {0}"
    )

    # ========== 外部服务错误 ==========

    CALL_OUTER_SERVICE_FAILURE = ErrorCode(
        "CALL_OUTER_SERVICE_FAILURE",
        "Call outer service failed, service: {0}, detail: {1}"
    )

    SIMULATION_API_FAILURE = ErrorCode(
        "SIMULATION_API_FAILURE",
        "Call simulation service failed, service: {0}, params: {1}"
    )

    SIMULATION_DATA_CORRUPTED = ErrorCode(
        "SIMULATION_DATA_CORRUPTED",
        "Simulation data corrupted, service: {0}, params: {1}"
    )

    # ========== 数据错误 ==========

    DATA_NOT_FOUND = ErrorCode(
        "DATA_NOT_FOUND",
        "Data not found"
    )

    PLC_DATA_CORRUPTED = ErrorCode(
        "PLC_DATA_CORRUPTED",
        "PLC data corrupted, service: {0}, params: {1}"
    )

    # ========== 智能体相关错误 ==========

    AGENT_INIT_FAILURE = ErrorCode(
        "AGENT_INIT_FAILURE",
        "Agent initialization failed: {0}, detail: {1}"
    )

    AGENT_TICK_FAILURE = ErrorCode(
        "AGENT_TICK_FAILURE",
        "Agent tick execution failed: {0}, detail: {1}"
    )

    AGENT_TERMINATE_FAILURE = ErrorCode(
        "AGENT_TERMINATE_FAILURE",
        "Agent termination failed: {0}, detail: {1}"
    )

    TIME_SERIES_UPDATE_FAILURE = ErrorCode(
        "TIME_SERIES_UPDATE_FAILURE",
        "Time series data update failed: {0}, detail: {1}"
    )

    TIME_SERIES_CALCULATION_FAILURE = ErrorCode(
        "TIME_SERIES_CALCULATION_FAILURE",
        "Time series calculation failed: {0}, detail: {1}"
    )

    TOPOLOGY_LOAD_FAILURE = ErrorCode(
        "TOPOLOGY_LOAD_FAILURE",
        "Topology load failure: {0}, detail: {1}"
    )

    SIMULATION_EXECUTION_FAILURE = ErrorCode(
        "SIMULATION_EXECUTION_FAILURE",
        "Simulation execution failed: {0}, detail: {1}"
    )

    MODEL_INITIALIZATION_FAILURE = ErrorCode(
        "MODEL_INITIALIZATION_FAILURE",
        "Model initialization failed: {0}, detail: {1}"
    )

    BOUNDARY_CONDITION_ERROR = ErrorCode(
        "BOUNDARY_CONDITION_ERROR",
        "Boundary condition error: {0}, detail: {1}"
    )

    METRICS_GENERATION_FAILURE = ErrorCode(
        "METRICS_GENERATION_FAILURE",
        "Metrics generation failed: {0}, detail: {1}"
    )

    # ========== 校验错误 ==========

    VALIDATION_ERROR = ErrorCode(
        "VALIDATION_ERROR",
        "Validation error: {0}"
    )

    MISSING_REQUIRED_FIELD = ErrorCode(
        "MISSING_REQUIRED_FIELD",
        "Missing required field: {0}"
    )

    # ========== 状态管理错误 ==========

    STATE_MANAGER_ERROR = ErrorCode(
        "STATE_MANAGER_ERROR",
        "State manager error: {0}, detail: {1}"
    )

    CONTEXT_NOT_FOUND = ErrorCode(
        "CONTEXT_NOT_FOUND",
        "Simulation context not found: {0}"
    )

    AGENT_NOT_FOUND = ErrorCode(
        "AGENT_NOT_FOUND",
        "Agent instance not found: {0}"
    )


# 创建错误响应的便捷函数
def create_error_response(
    response_class,
    error_code: ErrorCode,
    *args: Any,
    **kwargs
):
    """
    创建带格式化错误消息的错误响应。

    这是一个用于创建带错误信息响应对象的便捷函数。

    Args:
        response_class: 要实例化的响应类
        error_code: 要使用的 ErrorCode
        *args: 用于格式化错误消息的参数
        **kwargs: 响应的额外字段

    Returns:
        带错误信息的响应实例

    示例：
        >>> from hydros_agent_sdk.protocol.commands import TickCmdResponse
        >>> from hydros_agent_sdk.protocol.models import CommandStatus
        >>>
        >>> response = create_error_response(
        ...     TickCmdResponse,
        ...     ErrorCodes.AGENT_TICK_FAILURE,
        ...     "MyAgent",
        ...     "Division by zero",
        ...     command_id="CMD123",
        ...     context=context,
        ...     source_agent_instance=agent_instance
        ... )
    """
    from hydros_agent_sdk.protocol.models import CommandStatus

    return response_class(
        command_status=CommandStatus.FAILED,
        error_code=error_code.code,
        error_message=error_code.format_message(*args),
        **kwargs
    )
