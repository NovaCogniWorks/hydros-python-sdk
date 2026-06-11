"""
Hydros Agent SDK 错误处理装饰器和工具。

本模块提供用于处理智能体方法错误的装饰器和工具函数，
可自动将异常转换为合适的错误响应。

用法：
    from hydros_agent_sdk.error_handling import handle_agent_errors

    class MyAgent(TickableAgent):
        @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
        def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
            # 你的初始化逻辑
            # 任何异常都会被捕获并转换为错误响应
            pass
"""

import logging
import traceback
from functools import wraps
from typing import Callable, TypeVar, Any, Optional

from hydros_agent_sdk.error_codes import ErrorCode, ErrorCodes
from hydros_agent_sdk.protocol.models import CommandStatus

logger = logging.getLogger(__name__)

# 被装饰函数的类型变量
F = TypeVar('F', bound=Callable[..., Any])


def handle_agent_errors(
    error_code: ErrorCode,
    agent_name_attr: str = "agent_code",
    include_traceback: bool = True
) -> Callable[[F], F]:
    """
    用于处理智能体方法错误的装饰器。

    该装饰器会捕获智能体方法中的异常，并将其转换为带有合适错误码
    和错误消息的响应。

    Args:
        error_code: 当前方法使用的 ErrorCode
        agent_name_attr: 用于获取智能体名称的属性名（默认 "agent_code"）
        include_traceback: 错误消息中是否包含 traceback（默认 True）

    Returns:
        已具备错误处理能力的装饰后函数

    示例：
        @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
        def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
            # 你的逻辑写在这里
            pass

        @handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
        def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
            # 你的逻辑写在这里
            pass
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            try:
                # 执行原始函数
                return func(self, request, *args, **kwargs)

            except Exception as e:
                # 获取智能体名称
                agent_name = getattr(self, agent_name_attr, "UnknownAgent")

                # 格式化错误消息
                error_detail = str(e)
                if include_traceback:
                    error_detail = f"{error_detail}\n{traceback.format_exc()}"

                error_message = error_code.format_message(agent_name, error_detail)

                # 记录错误日志
                logger.error(
                    f"Error in {func.__name__} for agent {agent_name}: {error_message}",
                    exc_info=True
                )

                # 根据函数名判断响应类
                response_class = _get_response_class(func.__name__)

                if response_class is None:
                    # 如果无法判断响应类，则重新抛出
                    logger.error(f"Cannot determine response class for {func.__name__}, re-raising exception")
                    raise

                # 创建错误响应
                try:
                    # 为特定响应类型预填必填字段，以通过 Pydantic 校验
                    extra_fields = {}
                    if func.__name__ == "on_init" or response_class.__name__ == "SimTaskInitResponse":
                        extra_fields["created_agent_instances"] = []
                        extra_fields["managed_top_objects"] = {}

                    response = response_class(
                        command_id=getattr(request, "command_id", "UNKNOWN"),
                        context=getattr(request, "context", getattr(self, "context", None)),
                        command_status=CommandStatus.FAILED,
                        error_code=error_code.code,
                        error_message=error_message,
                        source_agent_instance=self,
                        **extra_fields
                    )

                    return response

                except Exception as response_error:
                    logger.error(
                        f"Failed to create error response: {response_error}",
                        exc_info=True
                    )
                    # 如果无法创建响应，则重新抛出原始异常
                    raise e

        return wrapper  # type: ignore
    return decorator


def _get_response_class(method_name: str):
    """
    根据方法名获取响应类。

    Args:
        method_name: 方法名称（例如 "on_init", "on_tick"）

    Returns:
        响应类；未找到时返回 None
    """
    from hydros_agent_sdk.protocol.commands import (
        SimTaskInitResponse,
        TickCmdResponse,
        SimTaskTerminateResponse,
        TimeSeriesDataUpdateResponse,
        TimeSeriesCalculationResponse,
    )

    response_map = {
        'on_init': SimTaskInitResponse,
        'on_tick': TickCmdResponse,
        'on_tick_simulation': TickCmdResponse,
        'on_terminate': SimTaskTerminateResponse,
        'on_time_series_data_update': TimeSeriesDataUpdateResponse,
        'on_time_series_calculation': TimeSeriesCalculationResponse,
    }

    return response_map.get(method_name)


def safe_execute(
    func: Callable,
    error_code: ErrorCode,
    agent_name: str = "UnknownAgent",
    *args,
    **kwargs
) -> tuple[bool, Any, Optional[str]]:
    """
    安全执行函数，并返回成功状态、结果或错误。

    这是一个用于执行可能失败代码块的工具函数，适合不使用装饰器的场景。

    Args:
        func: 要执行的函数
        error_code: 函数失败时使用的 ErrorCode
        agent_name: 智能体名称（用于错误消息）
        *args: 传给函数的位置参数
        **kwargs: 传给函数的关键字参数

    Returns:
        (success, result, error_message) 元组
        - success: 函数成功执行时为 True
        - result: 函数返回值（失败时为 None）
        - error_message: 格式化后的错误消息（成功时为 None）

    示例：
        success, topology, error_msg = safe_execute(
            HydroObjectUtilsV2.build_waterway_topology,
            ErrorCodes.TOPOLOGY_LOAD_FAILURE,
            "MyAgent",
            topology_url
        )

        if not success:
            logger.error(f"Failed to load topology: {error_msg}")
            return create_error_response(...)
    """
    try:
        result = func(*args, **kwargs)
        return True, result, None

    except Exception as e:
        error_detail = f"{str(e)}\n{traceback.format_exc()}"
        error_message = error_code.format_message(agent_name, error_detail)

        logger.error(
            f"Error in safe_execute for {agent_name}: {error_message}",
            exc_info=True
        )

        return False, None, error_message


class AgentErrorContext:
    """
    用于处理智能体代码块错误的上下文管理器。

    它提供一种更灵活的方式来处理特定代码块中的错误，无需使用装饰器。

    示例：
        with AgentErrorContext(
            ErrorCodes.TOPOLOGY_LOAD_FAILURE,
            agent_name="MyAgent"
        ) as ctx:
            topology = HydroObjectUtilsV2.build_waterway_topology(url)

        if ctx.has_error:
            return create_error_response(
                SimTaskInitResponse,
                ErrorCodes.TOPOLOGY_LOAD_FAILURE,
                "MyAgent",
                ctx.error_message,
                ...
            )
    """

    def __init__(
        self,
        error_code: ErrorCode,
        agent_name: str = "UnknownAgent",
        include_traceback: bool = True
    ):
        """
        初始化错误上下文。

        Args:
            error_code: 当前上下文出现错误时使用的 ErrorCode
            agent_name: 智能体名称
            include_traceback: 错误消息中是否包含 traceback
        """
        self.error_code = error_code
        self.agent_name = agent_name
        self.include_traceback = include_traceback
        self.has_error = False
        self.error_message: Optional[str] = None
        self.exception: Optional[Exception] = None

    def __enter__(self):
        """进入上下文。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文并处理可能出现的异常。"""
        if exc_type is not None:
            # 出现异常
            self.has_error = True
            self.exception = exc_val

            # 格式化错误消息
            error_detail = str(exc_val)
            if self.include_traceback:
                error_detail = f"{error_detail}\n{traceback.format_exc()}"

            self.error_message = self.error_code.format_message(
                self.agent_name,
                error_detail
            )

            # 记录错误日志
            logger.error(
                f"Error in AgentErrorContext for {self.agent_name}: {self.error_message}",
                exc_info=True
            )

            # 抑制异常（返回 True）
            return True

        return False


def validate_request(
    request: Any,
    required_fields: list[str],
    agent_name: str = "UnknownAgent"
) -> tuple[bool, Optional[str]]:
    """
    校验请求是否包含全部必填字段。

    Args:
        request: 要校验的请求对象
        required_fields: 必填字段名称列表
        agent_name: 智能体名称（用于错误消息）

    Returns:
        (is_valid, error_message) 元组
        - is_valid: 全部必填字段存在时为 True
        - error_message: 校验失败时的错误消息（校验通过时为 None）

    示例：
        is_valid, error_msg = validate_request(
            request,
            ['context', 'agent_list'],
            "MyAgent"
        )

        if not is_valid:
            return create_error_response(
                SimTaskInitResponse,
                ErrorCodes.INVALID_PARAMS,
                error_msg,
                ...
            )
    """
    missing_fields = []

    for field in required_fields:
        if not hasattr(request, field) or getattr(request, field) is None:
            missing_fields.append(field)

    if missing_fields:
        error_message = ErrorCodes.MISSING_REQUIRED_FIELD.format_message(
            f"{agent_name}: {', '.join(missing_fields)}"
        )
        return False, error_message

    return True, None
