"""
Logging configuration for Hydros Agent SDK.

Provides a custom formatter with Python-style source location for VSCode navigation.

Log format varies by context:

1. Agent business logic (with biz_scene_instance_id):
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_scene_instance_id}|${agent_id}|||coordination_client.py:123|message

2. SDK infrastructure (without biz_scene_instance_id):
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_component}|-|coordination_client.py:123|message

Format breakdown:
- hydros_cluster_id (e.g., "default_cluster")
- hydros_node_id (e.g., "default_central")
- timestamp (yyyy-MM-dd HH:mm:ss)
- log level (5 chars, left-aligned)
- biz_scene_instance_id (from SimulationContext) OR biz_component (e.g., "SIM_SDK", "SIM_COORDINATOR")
- agent_id (from HydroAgentInstance) OR "-" for infrastructure logs
- reserved field (empty)
- reserved field (empty)
- source location (filename:lineno) - clickable in VSCode
- message
"""

import logging
from contextvars import ContextVar
from typing import Optional
from datetime import datetime

# Context variables for MDC-like functionality (similar to Java's MDC)
_biz_scene_instance_id: ContextVar[Optional[str]] = ContextVar('biz_scene_instance_id', default=None)
_biz_component: ContextVar[Optional[str]] = ContextVar('biz_component', default=None)
_hydros_cluster_id: ContextVar[Optional[str]] = ContextVar('hydros_cluster_id', default=None)
_hydros_node_id: ContextVar[Optional[str]] = ContextVar('hydros_node_id', default=None)


class LogContext:
    """
    Context manager for setting logging context (MDC-like functionality).

    Example:
        with LogContext(biz_scene_instance_id="TASK123", biz_component="AGENT_001"):
            logger.info("Processing task")
    """

    def __init__(
        self,
        biz_scene_instance_id: Optional[str] = None,
        biz_component: Optional[str] = None,
        hydros_cluster_id: Optional[str] = None,
        hydros_node_id: Optional[str] = None
    ):
        self.biz_scene_instance_id = biz_scene_instance_id
        self.biz_component = biz_component
        self.hydros_cluster_id = hydros_cluster_id
        self.hydros_node_id = hydros_node_id
        self.tokens = []

    def __enter__(self):
        if self.biz_scene_instance_id is not None:
            self.tokens.append(_biz_scene_instance_id.set(self.biz_scene_instance_id))
        if self.biz_component is not None:
            self.tokens.append(_biz_component.set(self.biz_component))
        if self.hydros_cluster_id is not None:
            self.tokens.append(_hydros_cluster_id.set(self.hydros_cluster_id))
        if self.hydros_node_id is not None:
            self.tokens.append(_hydros_node_id.set(self.hydros_node_id))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for token in reversed(self.tokens):
            token.var.reset(token)


def set_biz_scene_instance_id(biz_scene_instance_id: Optional[str]):
    """Set the biz_scene_instance_id (from SimulationContext) for the current context."""
    _biz_scene_instance_id.set(biz_scene_instance_id)


def set_biz_component(biz_component: Optional[str]):
    """
    Set the biz_component for the current context.

    This can be:
    - agent_id (e.g., "AGENT_001") in agent business logic
    - component name (e.g., "SIM_SDK", "SIM_COORDINATOR") in infrastructure code
    """
    _biz_component.set(biz_component)


def set_hydros_cluster_id(hydros_cluster_id: Optional[str]):
    """Set the hydros_cluster_id for the current context."""
    _hydros_cluster_id.set(hydros_cluster_id)


def set_hydros_node_id(hydros_node_id: Optional[str]):
    """Set the hydros_node_id for the current context."""
    _hydros_node_id.set(hydros_node_id)


def get_biz_scene_instance_id() -> Optional[str]:
    """Get the current biz_scene_instance_id."""
    return _biz_scene_instance_id.get()


def get_biz_component() -> Optional[str]:
    """Get the current biz_component."""
    return _biz_component.get()


def get_hydros_cluster_id() -> Optional[str]:
    """Get the current hydros_cluster_id."""
    return _hydros_cluster_id.get()


def get_hydros_node_id() -> Optional[str]:
    """Get the current hydros_node_id."""
    return _hydros_node_id.get()


# Backward compatibility aliases (deprecated)
def set_task_id(task_id: Optional[str]):
    """Deprecated: Use set_biz_scene_instance_id instead."""
    set_biz_scene_instance_id(task_id)


def set_agent_id(agent_id: Optional[str]):
    """Deprecated: Use set_biz_component instead."""
    set_biz_component(agent_id)


def set_node_id(node_id: Optional[str]):
    """Deprecated: Use set_hydros_node_id instead."""
    set_hydros_node_id(node_id)


def get_task_id() -> Optional[str]:
    """Deprecated: Use get_biz_scene_instance_id instead."""
    return get_biz_scene_instance_id()


def get_agent_id() -> Optional[str]:
    """Deprecated: Use get_biz_component instead."""
    return get_biz_component()


def get_node_id() -> Optional[str]:
    """Deprecated: Use get_hydros_node_id instead."""
    return get_hydros_node_id()


class HydrosFormatter(logging.Formatter):
    """
    Custom formatter with Python-style source location for VSCode navigation.

    Format varies by context:
    1. With biz_scene_instance_id (agent business logic):
       CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|||SOURCE|MESSAGE

    2. Without biz_scene_instance_id (infrastructure):
       CLUSTER|NODE|TIME|LEVEL|BIZ_COMPONENT|-|SOURCE|MESSAGE

    Example outputs:
    - Agent: default_cluster|default_central|2026-01-28 23:29:48|INFO |TASK202601282328VG3IE7H3CA0F|AGENT_001|||coordination_client.py:123|Processing command
    - SDK:   default_cluster|default_central|2026-01-28 23:29:48|INFO |SIM_SDK|-|coordination_client.py:123|Loading configuration
    """

    def __init__(
        self,
        default_hydros_cluster_id: str = "default_cluster",
        default_hydros_node_id: str = "LOCAL"
    ):
        """
        Initialize the formatter.

        Args:
            default_hydros_cluster_id: Default cluster ID if not set in context
            default_hydros_node_id: Default node ID if not set in context
        """
        super().__init__()
        self.default_hydros_cluster_id = default_hydros_cluster_id
        self.default_hydros_node_id = default_hydros_node_id

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with Python-style source location."""
        # Get context values with defaults
        hydros_cluster_id = get_hydros_cluster_id() or self.default_hydros_cluster_id
        hydros_node_id = get_hydros_node_id() or self.default_hydros_node_id
        biz_scene_instance_id = get_biz_scene_instance_id()
        biz_component = get_biz_component() or "Common"

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')

        # Format log level (5 chars, left-aligned)
        level = f"{record.levelname:<5}"

        # Format source location (filename:lineno) for VSCode navigation
        source_location = f"{record.filename}:{record.lineno}"

        # Format message
        message = record.getMessage()

        # Handle exceptions
        if record.exc_info:
            if not message.endswith('\n'):
                message += '\n'
            message += self.formatException(record.exc_info)

        # Build the log line based on context
        if biz_scene_instance_id:
            # Agent business logic format: CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|||SOURCE|MESSAGE
            parts = [
                hydros_cluster_id,
                hydros_node_id,
                timestamp,
                level,
                biz_scene_instance_id,
                biz_component,  # This is agent_id in agent context
                "",  # Reserved field
                "",  # Reserved field
                source_location,
                message
            ]
        else:
            # Infrastructure format: CLUSTER|NODE|TIME|LEVEL|BIZ_COMPONENT|-|SOURCE|MESSAGE
            parts = [
                hydros_cluster_id,
                hydros_node_id,
                timestamp,
                level,
                biz_component,  # This is component name like "SIM_SDK", "SIM_COORDINATOR"
                "-",  # No agent_id in infrastructure logs
                source_location,
                message
            ]

        return '|'.join(parts)


def setup_logging(
    level: int = logging.INFO,
    hydros_cluster_id: str = "default_cluster",
    hydros_node_id: str = "LOCAL",
    log_file: Optional[str] = None,
    console: bool = True,
    # Deprecated parameters for backward compatibility
    node_id: Optional[str] = None
):
    """
    Configure logging with Hydros formatter.

    Args:
        level: Logging level (default: logging.INFO)
        hydros_cluster_id: Default cluster ID for logs (default: "default_cluster")
        hydros_node_id: Default node ID for logs (default: "LOCAL")
        log_file: Optional log file path
        console: Whether to log to console (default: True)
        node_id: Deprecated, use hydros_node_id instead

    Example:
        setup_logging(
            level=logging.INFO,
            hydros_cluster_id="default_cluster",
            hydros_node_id="default_central"
        )

        # Set context and log
        set_biz_scene_instance_id("TASK202601282328VG3IE7H3CA0F")
        set_agent_id("AGENT_001")
        logger.info("Processing command")
    """
    # Backward compatibility: use node_id if hydros_node_id not explicitly set
    if node_id is not None and hydros_node_id == "LOCAL":
        hydros_node_id = node_id

    # Create formatter
    formatter = HydrosFormatter(
        default_hydros_cluster_id=hydros_cluster_id,
        default_hydros_node_id=hydros_node_id
    )

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
