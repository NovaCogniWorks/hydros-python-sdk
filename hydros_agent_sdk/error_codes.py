"""
Error codes for Hydros Agent SDK.

This module provides error code definitions and message formatting utilities,
matching the Java ErrorCodes implementation in hydros-common.

Usage:
    from hydros_agent_sdk.error_codes import ErrorCodes

    # Format error message
    error_msg = ErrorCodes.SYSTEM_ERROR.format_message("NetworkError", "Connection timeout")

    # Use in response
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
    Error code with message template.

    This class represents a single error code with its associated message template.
    It provides message formatting using Python's str.format() method.

    Attributes:
        code: The error code string (e.g., "SYSTEM_ERROR")
        message_template: The message template with placeholders (e.g., "Error: {0}")
    """

    def __init__(self, code: str, message_template: str):
        """
        Initialize error code.

        Args:
            code: Error code string
            message_template: Message template with {0}, {1}, etc. placeholders
        """
        self.code = code
        self.message_template = message_template

    def format_message(self, *args: Any) -> str:
        """
        Format error message with arguments.

        This method replaces {0}, {1}, etc. placeholders in the message template
        with the provided arguments.

        Args:
            *args: Arguments to format into the message template

        Returns:
            Formatted error message

        Example:
            >>> error = ErrorCode("TEST_ERROR", "Error: {0}, detail: {1}")
            >>> error.format_message("Connection failed", "Timeout")
            'Error: Connection failed, detail: Timeout'
        """
        try:
            # Replace {0}, {1}, etc. with provided arguments
            message = self.message_template
            for i, arg in enumerate(args):
                message = message.replace(f"{{{i}}}", str(arg))
            return message
        except Exception as e:
            # Fallback: return template with error info
            return f"{self.message_template} (format error: {e})"

    def __str__(self) -> str:
        """String representation of error code."""
        return f"ErrorCode({self.code})"

    def __repr__(self) -> str:
        """Detailed representation of error code."""
        return f"ErrorCode(code='{self.code}', template='{self.message_template}')"


class ErrorCodes:
    """
    Error code definitions for Hydros Agent SDK.

    This class provides static error code definitions matching the Java implementation
    in com.hydros.common.ErrorCodes.

    Core error codes:
    - SYSTEM_ERROR: Unknown system failures
    - INVALID_PARAMS: Invalid parameters
    - CONFIGURATION_LOAD_FAILURE: Configuration loading failures
    - DATA_SERIALIZATION_FAILURE: Data serialization failures

    Agent-specific error codes:
    - AGENT_INIT_FAILURE: Agent initialization failures
    - AGENT_TICK_FAILURE: Agent tick execution failures
    - AGENT_TERMINATE_FAILURE: Agent termination failures
    - TIME_SERIES_UPDATE_FAILURE: Time series data update failures
    - TOPOLOGY_LOAD_FAILURE: Topology loading failures
    - SIMULATION_EXECUTION_FAILURE: Simulation execution failures

    Usage:
        # Get error code and format message
        error_code = ErrorCodes.SYSTEM_ERROR.code
        error_message = ErrorCodes.SYSTEM_ERROR.format_message("NetworkError", "Connection timeout")

        # Use in response
        response = TickCmdResponse(
            command_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            ...
        )
    """

    # ========== Core System Errors ==========

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

    # ========== Configuration Errors ==========

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

    # ========== External Service Errors ==========

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

    # ========== Data Errors ==========

    DATA_NOT_FOUND = ErrorCode(
        "DATA_NOT_FOUND",
        "Data not found"
    )

    PLC_DATA_CORRUPTED = ErrorCode(
        "PLC_DATA_CORRUPTED",
        "PLC data corrupted, service: {0}, params: {1}"
    )

    # ========== Agent-Specific Errors ==========

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

    # ========== Validation Errors ==========

    VALIDATION_ERROR = ErrorCode(
        "VALIDATION_ERROR",
        "Validation error: {0}"
    )

    MISSING_REQUIRED_FIELD = ErrorCode(
        "MISSING_REQUIRED_FIELD",
        "Missing required field: {0}"
    )

    # ========== State Management Errors ==========

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


# Convenience function for creating error responses
def create_error_response(
    response_class,
    error_code: ErrorCode,
    *args: Any,
    **kwargs
):
    """
    Create an error response with formatted error message.

    This is a convenience function for creating response objects with
    error information.

    Args:
        response_class: The response class to instantiate
        error_code: The ErrorCode to use
        *args: Arguments for error message formatting
        **kwargs: Additional fields for the response

    Returns:
        Response instance with error information

    Example:
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
