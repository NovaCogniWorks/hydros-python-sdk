"""
Logging configuration for Hydros Agent SDK.

Provides a custom formatter that matches the Java logback pattern used in hydros-data:
DATA|2026-01-28 23:29:48|INFO|TASK202601282328VG3IE7H3CA0F|SimCoordinator|||c.h.c.s.b.BaseCoordinatorMqttService|message

Format breakdown:
- hydros_node_id (e.g., "DATA")
- timestamp (yyyy-MM-dd HH:mm:ss)
- log level (5 chars, left-aligned)
- biz_scene_instance_id (taskId, defaults to "System")
- agent_code (bizComponent, defaults to "Common")
- type (defaults to empty)
- content (defaults to empty)
- logger name (abbreviated)
- message
"""

import logging
from contextvars import ContextVar
from typing import Optional
from datetime import datetime

# Context variables for MDC-like functionality (similar to Java's MDC)
_task_id: ContextVar[Optional[str]] = ContextVar('task_id', default=None)
_biz_component: ContextVar[Optional[str]] = ContextVar('biz_component', default=None)
_log_type: ContextVar[Optional[str]] = ContextVar('log_type', default=None)
_log_content: ContextVar[Optional[str]] = ContextVar('log_content', default=None)
_node_id: ContextVar[Optional[str]] = ContextVar('node_id', default=None)


class LogContext:
    """
    Context manager for setting logging context (MDC-like functionality).

    Example:
        with LogContext(task_id="TASK123", biz_component="MyAgent"):
            logger.info("Processing task")
    """

    def __init__(
        self,
        task_id: Optional[str] = None,
        biz_component: Optional[str] = None,
        log_type: Optional[str] = None,
        log_content: Optional[str] = None,
        node_id: Optional[str] = None
    ):
        self.task_id = task_id
        self.biz_component = biz_component
        self.log_type = log_type
        self.log_content = log_content
        self.node_id = node_id
        self.tokens = []

    def __enter__(self):
        if self.task_id is not None:
            self.tokens.append(_task_id.set(self.task_id))
        if self.biz_component is not None:
            self.tokens.append(_biz_component.set(self.biz_component))
        if self.log_type is not None:
            self.tokens.append(_log_type.set(self.log_type))
        if self.log_content is not None:
            self.tokens.append(_log_content.set(self.log_content))
        if self.node_id is not None:
            self.tokens.append(_node_id.set(self.node_id))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for token in reversed(self.tokens):
            token.var.reset(token)


def set_task_id(task_id: Optional[str]):
    """Set the task ID (biz_scene_instance_id) for the current context."""
    _task_id.set(task_id)


def set_biz_component(biz_component: Optional[str]):
    """Set the business component (agent_code) for the current context."""
    _biz_component.set(biz_component)


def set_log_type(log_type: Optional[str]):
    """Set the log type for the current context."""
    _log_type.set(log_type)


def set_log_content(log_content: Optional[str]):
    """Set the log content for the current context."""
    _log_content.set(log_content)


def set_node_id(node_id: Optional[str]):
    """Set the node ID (hydros_node_id) for the current context."""
    _node_id.set(node_id)


def get_task_id() -> Optional[str]:
    """Get the current task ID."""
    return _task_id.get()


def get_biz_component() -> Optional[str]:
    """Get the current business component."""
    return _biz_component.get()


def get_log_type() -> Optional[str]:
    """Get the current log type."""
    return _log_type.get()


def get_log_content() -> Optional[str]:
    """Get the current log content."""
    return _log_content.get()


def get_node_id() -> Optional[str]:
    """Get the current node ID."""
    return _node_id.get()


class HydrosFormatter(logging.Formatter):
    """
    Custom formatter that matches the Java logback pattern.

    Format: NODE_ID|TIMESTAMP|LEVEL|TASK_ID|BIZ_COMPONENT|TYPE|CONTENT|LOGGER|MESSAGE

    Example output:
    DATA|2026-01-28 23:29:48|INFO|TASK202601282328VG3IE7H3CA0F|SimCoordinator|||c.h.c.s.b.BaseCoordinatorMqttService|Processing command
    """

    def __init__(self, default_node_id: str = "DATA", logger_max_length: int = 36):
        """
        Initialize the formatter.

        Args:
            default_node_id: Default node ID if not set in context (default: "DATA")
            logger_max_length: Maximum length for logger name abbreviation (default: 36)
        """
        super().__init__()
        self.default_node_id = default_node_id
        self.logger_max_length = logger_max_length

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record according to the Hydros pattern."""
        # Get context values with defaults
        node_id = get_node_id() or self.default_node_id
        task_id = get_task_id() or "System"
        biz_component = get_biz_component() or "Common"
        log_type = get_log_type() or ""
        log_content = get_log_content() or ""

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')

        # Format log level (5 chars, left-aligned)
        level = f"{record.levelname:<5}"

        # Abbreviate logger name if needed
        logger_name = self._abbreviate_logger_name(record.name)

        # Format message
        message = record.getMessage()

        # Handle exceptions
        if record.exc_info:
            if not message.endswith('\n'):
                message += '\n'
            message += self.formatException(record.exc_info)

        # Build the log line
        parts = [
            node_id,
            timestamp,
            level,
            task_id,
            biz_component,
            log_type,
            log_content,
            logger_name,
            message
        ]

        return '|'.join(parts)

    def _abbreviate_logger_name(self, name: str) -> str:
        """
        Abbreviate logger name similar to logback's %logger{36}.

        Examples:
            com.hydros.coordination.service.BaseCoordinatorMqttService
            -> c.h.c.s.BaseCoordinatorMqttService

            hydros_agent_sdk.coordination_client
            -> h.a.coordination_client
        """
        if len(name) <= self.logger_max_length:
            return name

        parts = name.split('.')
        if len(parts) <= 1:
            return name[:self.logger_max_length]

        # Abbreviate all parts except the last one
        abbreviated = []
        for part in parts[:-1]:
            if part:
                abbreviated.append(part[0])
        abbreviated.append(parts[-1])

        result = '.'.join(abbreviated)

        # If still too long, truncate
        if len(result) > self.logger_max_length:
            return result[:self.logger_max_length]

        return result


def setup_logging(
    level: int = logging.INFO,
    node_id: str = "DATA",
    log_file: Optional[str] = None,
    console: bool = True
):
    """
    Configure logging with Hydros formatter.

    Args:
        level: Logging level (default: logging.INFO)
        node_id: Default node ID for logs (default: "DATA")
        log_file: Optional log file path
        console: Whether to log to console (default: True)

    Example:
        setup_logging(level=logging.INFO, node_id="AGENT_NODE_01")

        # Set context and log
        set_task_id("TASK202601282328VG3IE7H3CA0F")
        set_biz_component("SimCoordinator")
        logger.info("Processing command")
    """
    # Create formatter
    formatter = HydrosFormatter(default_node_id=node_id)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Add console handler
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
