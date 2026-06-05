"""
Logging configuration for Hydros Agent SDK.

Provides a custom formatter with Python-style source location for VSCode navigation.

Log format varies by context:

1. Agent business logic (with biz_scene_instance_id):
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_scene_instance_id}|${agent_id}|coordination_client.py:123|message

2. SDK infrastructure (without biz_scene_instance_id):
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_component}|-|coordination_client.py:123|message

Format breakdown:
- hydros_cluster_id (e.g., "default_cluster")
- hydros_node_id (e.g., "default_central")
- timestamp (yyyy-MM-dd HH:mm:ss)
- log level (5 chars, left-aligned)
- biz_scene_instance_id (from SimulationContext) OR biz_component (e.g., "SIM_SDK", "SIM_COORDINATOR")
- agent_id (from HydroAgentInstance) OR "-" for infrastructure logs
- source location (filename:lineno) - clickable in VSCode
- message
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from contextvars import ContextVar
from typing import Optional
from datetime import datetime

# 用于类 MDC 功能的上下文变量（类似 Java MDC）
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
    """为当前上下文设置 biz_scene_instance_id（来自 SimulationContext）。"""
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
    """为当前上下文设置 hydros_cluster_id。"""
    _hydros_cluster_id.set(hydros_cluster_id)


def set_hydros_node_id(hydros_node_id: Optional[str]):
    """为当前上下文设置 hydros_node_id。"""
    _hydros_node_id.set(hydros_node_id)


def get_biz_scene_instance_id() -> Optional[str]:
    """获取当前 biz_scene_instance_id。"""
    return _biz_scene_instance_id.get()


def get_biz_component() -> Optional[str]:
    """获取当前 biz_component。"""
    return _biz_component.get()


def get_hydros_cluster_id() -> Optional[str]:
    """获取当前 hydros_cluster_id。"""
    return _hydros_cluster_id.get()


def get_hydros_node_id() -> Optional[str]:
    """获取当前 hydros_node_id。"""
    return _hydros_node_id.get()


# 向后兼容别名（已废弃）
def set_task_id(task_id: Optional[str]):
    """已废弃：请改用 set_biz_scene_instance_id。"""
    set_biz_scene_instance_id(task_id)


def set_agent_id(agent_id: Optional[str]):
    """已废弃：请改用 set_biz_component。"""
    set_biz_component(agent_id)


def set_node_id(node_id: Optional[str]):
    """已废弃：请改用 set_hydros_node_id。"""
    set_hydros_node_id(node_id)


def get_task_id() -> Optional[str]:
    """已废弃：请改用 get_biz_scene_instance_id。"""
    return get_biz_scene_instance_id()


def get_agent_id() -> Optional[str]:
    """已废弃：请改用 get_biz_component。"""
    return get_biz_component()


def get_node_id() -> Optional[str]:
    """已废弃：请改用 get_hydros_node_id。"""
    return get_hydros_node_id()


class HydrosSimpleFormatter(logging.Formatter):
    """
    Simplified formatter for local development.

    Format: TIME|LEVEL|SOURCE|MESSAGE

    Example:
        2026-01-28 23:29:48|INFO |coordination_client.py:123|Processing command
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        level = f"{record.levelname:<5}"
        source_location = f"{record.filename}:{record.lineno}"
        message = record.getMessage()

        if record.exc_info:
            if not message.endswith('\n'):
                message += '\n'
            message += self.formatException(record.exc_info)

        return f"{timestamp}|{level}|{source_location}|{message}"


class HydrosFormatter(logging.Formatter):
    """
    Full formatter for production deployment.

    Format varies by context:
    1. With biz_scene_instance_id (agent business logic):
       CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|SOURCE|MESSAGE

    2. Without biz_scene_instance_id (infrastructure):
       CLUSTER|NODE|TIME|LEVEL|BIZ_COMPONENT|-|SOURCE|MESSAGE

    Example outputs:
    - Agent: default_cluster|default_central|2026-01-28 23:29:48|INFO |TASK202601282328VG3IE7H3CA0F|AGENT_001|coordination_client.py:123|Processing command
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
        """使用 Python 风格源码位置格式化日志记录。"""
        # 获取带默认值的上下文值
        hydros_cluster_id = get_hydros_cluster_id() or self.default_hydros_cluster_id
        hydros_node_id = get_hydros_node_id() or self.default_hydros_node_id
        biz_scene_instance_id = get_biz_scene_instance_id()
        biz_component = get_biz_component() or "Common"

        # 格式化时间戳
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')

        # 格式化日志级别（5 个字符，左对齐）
        level = f"{record.levelname:<5}"

        # 格式化源码位置（filename:lineno），便于 VSCode 跳转
        source_location = f"{record.filename}:{record.lineno}"

        # 格式化消息
        message = record.getMessage()

        # 处理异常
        if record.exc_info:
            if not message.endswith('\n'):
                message += '\n'
            message += self.formatException(record.exc_info)

        # 根据上下文构建日志行
        if biz_scene_instance_id:
            # 智能体业务逻辑格式：CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|SOURCE|MESSAGE
            parts = [
                hydros_cluster_id,
                hydros_node_id,
                timestamp,
                level,
                biz_scene_instance_id,
                biz_component,  # This is agent_id in agent context
                source_location,
                message
            ]
        else:
            # 基础设施格式：CLUSTER|NODE|TIME|LEVEL|BIZ_COMPONENT|-|SOURCE|MESSAGE
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
    simple: bool = True,
    use_rolling: bool = False,
    # 用于向后兼容的废弃参数
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
        simple: Use simplified log format for local dev (default: True).
                Set to False for full production format.
        use_rolling: Whether to use daily rolling for log files (default: False).
        node_id: Deprecated, use hydros_node_id instead
    """
    # 向后兼容：未显式设置 hydros_node_id 时使用 node_id
    if node_id is not None and hydros_node_id == "LOCAL":
        hydros_node_id = node_id

    # 按模式创建 formatter
    if simple:
        formatter = HydrosSimpleFormatter()
    else:
        formatter = HydrosFormatter(
            default_hydros_cluster_id=hydros_cluster_id,
            default_hydros_node_id=hydros_node_id
        )

    # 获取 root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 移除已有 handler
    root_logger.handlers.clear()

    # 添加控制台 handler
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # 如果指定了日志文件，则添加文件 handler
    if log_file:
        if use_rolling:
            # 使用 TimedRotatingFileHandler 做每日轮转
            file_handler = TimedRotatingFileHandler(
                log_file,
                when='midnight',
                interval=1,
                backupCount=30,  # Keep 30 days of logs
                encoding='utf-8',
                utc=False
            )
            # 设置轮转文件后缀，使其包含日期
            file_handler.suffix = "%Y-%m-%d"
        else:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')

        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
