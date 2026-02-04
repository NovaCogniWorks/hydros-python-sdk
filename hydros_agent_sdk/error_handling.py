"""
Error handling decorators and utilities for Hydros Agent SDK.

This module provides decorators and utilities for handling errors in agent methods,
automatically converting exceptions to appropriate error responses.

Usage:
    from hydros_agent_sdk.error_handling import handle_agent_errors

    class MyAgent(TickableAgent):
        @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
        def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
            # Your initialization logic
            # Any exception will be caught and converted to error response
            pass
"""

import logging
import traceback
from functools import wraps
from typing import Callable, TypeVar, Any, Optional

from hydros_agent_sdk.error_codes import ErrorCode, ErrorCodes
from hydros_agent_sdk.protocol.models import CommandStatus

logger = logging.getLogger(__name__)

# Type variable for decorated function
F = TypeVar('F', bound=Callable[..., Any])


def handle_agent_errors(
    error_code: ErrorCode,
    agent_name_attr: str = "agent_code",
    include_traceback: bool = True
) -> Callable[[F], F]:
    """
    Decorator for handling errors in agent methods.

    This decorator catches exceptions in agent methods and converts them to
    appropriate error responses with proper error codes and messages.

    Args:
        error_code: The ErrorCode to use for this method
        agent_name_attr: Attribute name to get agent name from (default: "agent_code")
        include_traceback: Whether to include traceback in error message (default: True)

    Returns:
        Decorated function that handles errors

    Example:
        @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
        def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
            # Your logic here
            pass

        @handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
        def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
            # Your logic here
            pass
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            try:
                # Execute the original function
                return func(self, request, *args, **kwargs)

            except Exception as e:
                # Get agent name
                agent_name = getattr(self, agent_name_attr, "UnknownAgent")

                # Format error message
                error_detail = str(e)
                if include_traceback:
                    error_detail = f"{error_detail}\n{traceback.format_exc()}"

                error_message = error_code.format_message(agent_name, error_detail)

                # Log the error
                logger.error(
                    f"Error in {func.__name__} for agent {agent_name}: {error_message}",
                    exc_info=True
                )

                # Determine response class from function name
                response_class = _get_response_class(func.__name__)

                if response_class is None:
                    # If we can't determine response class, re-raise
                    logger.error(f"Cannot determine response class for {func.__name__}, re-raising exception")
                    raise

                # Create error response
                try:
                    response = response_class(
                        command_id=getattr(request, 'command_id', 'UNKNOWN'),
                        context=getattr(request, 'context', getattr(self, 'context', None)),
                        command_status=CommandStatus.FAILED,
                        error_code=error_code.code,
                        error_message=error_message,
                        source_agent_instance=self,
                    )

                    # Add response-specific fields
                    if hasattr(response, 'created_agent_instances'):
                        response.created_agent_instances = []
                    if hasattr(response, 'managed_top_objects'):
                        response.managed_top_objects = {}

                    return response

                except Exception as response_error:
                    logger.error(
                        f"Failed to create error response: {response_error}",
                        exc_info=True
                    )
                    # Re-raise original exception if we can't create response
                    raise e

        return wrapper  # type: ignore
    return decorator


def _get_response_class(method_name: str):
    """
    Get response class based on method name.

    Args:
        method_name: Name of the method (e.g., "on_init", "on_tick")

    Returns:
        Response class or None if not found
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
    Safely execute a function and return success status with result or error.

    This is a utility function for executing code blocks that might fail,
    without using decorators.

    Args:
        func: Function to execute
        error_code: ErrorCode to use if function fails
        agent_name: Name of the agent (for error messages)
        *args: Arguments to pass to function
        **kwargs: Keyword arguments to pass to function

    Returns:
        Tuple of (success, result, error_message)
        - success: True if function executed successfully
        - result: Return value of function (or None if failed)
        - error_message: Formatted error message (or None if succeeded)

    Example:
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
    Context manager for handling errors in agent code blocks.

    This provides a more flexible way to handle errors in specific code blocks
    without using decorators.

    Example:
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
        Initialize error context.

        Args:
            error_code: ErrorCode to use for errors in this context
            agent_name: Name of the agent
            include_traceback: Whether to include traceback in error message
        """
        self.error_code = error_code
        self.agent_name = agent_name
        self.include_traceback = include_traceback
        self.has_error = False
        self.error_message: Optional[str] = None
        self.exception: Optional[Exception] = None

    def __enter__(self):
        """Enter context."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and handle any exception."""
        if exc_type is not None:
            # An exception occurred
            self.has_error = True
            self.exception = exc_val

            # Format error message
            error_detail = str(exc_val)
            if self.include_traceback:
                error_detail = f"{error_detail}\n{traceback.format_exc()}"

            self.error_message = self.error_code.format_message(
                self.agent_name,
                error_detail
            )

            # Log the error
            logger.error(
                f"Error in AgentErrorContext for {self.agent_name}: {self.error_message}",
                exc_info=True
            )

            # Suppress the exception (return True)
            return True

        return False


def validate_request(
    request: Any,
    required_fields: list[str],
    agent_name: str = "UnknownAgent"
) -> tuple[bool, Optional[str]]:
    """
    Validate that a request has all required fields.

    Args:
        request: Request object to validate
        required_fields: List of required field names
        agent_name: Name of the agent (for error messages)

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if all required fields are present
        - error_message: Error message if validation failed (None if valid)

    Example:
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
