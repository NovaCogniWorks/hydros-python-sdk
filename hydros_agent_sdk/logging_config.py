"""
Hydros Agent SDK 日志配置。

提供带 Python 风格源码位置的自定义格式化器，便于在 VSCode 中跳转。

日志格式会随上下文变化：

1. 智能体业务逻辑（带 biz_scene_instance_id）：
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_scene_instance_id}|${agent_id}|coordination_client.py:123|message

2. SDK 基础设施（不带 biz_scene_instance_id）：
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_component}|-|coordination_client.py:123|message

格式字段说明：
- hydros_cluster_id（例如 "hydros-k3s-staging"）
- hydros_node_id（例如 "default_central"）
- 时间戳（yyyy-MM-dd HH:mm:ss）
- 日志级别（5 个字符，左对齐）
- biz_scene_instance_id（来自 SimulationContext）或 biz_component（例如 "SIM_SDK", "SIM_COORDINATOR"）
- agent_id（来自 HydroAgentInstance）或基础设施日志中的 "-"
- 源码位置（filename:lineno），可在 VSCode 中点击跳转
- 消息正文
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
    用于设置日志上下文的上下文管理器（类似 MDC 功能）。

    示例：
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
    为当前上下文设置 biz_component。

    该值可以是：
    - 智能体业务逻辑中的 agent_id（例如 "AGENT_001"）
    - 基础设施代码中的组件名（例如 "SIM_SDK", "SIM_COORDINATOR"）
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


class HydrosSimpleFormatter(logging.Formatter):
    """
    供本地开发使用的简化格式化器。

    格式：TIME|LEVEL|SOURCE|MESSAGE

    示例：
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
    供生产部署使用的完整格式化器。

    格式会随上下文变化：
    1. 带 biz_scene_instance_id（智能体业务逻辑）：
       CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|SOURCE|MESSAGE

    2. 不带 biz_scene_instance_id（基础设施）：
       CLUSTER|NODE|TIME|LEVEL|BIZ_COMPONENT|-|SOURCE|MESSAGE

    示例输出：
    - 智能体：hydros-k3s-staging|default_central|2026-01-28 23:29:48|INFO |TASK202601282328VG3IE7H3CA0F|AGENT_001|coordination_client.py:123|Processing command
    - SDK：   hydros-k3s-staging|default_central|2026-01-28 23:29:48|INFO |SIM_SDK|-|coordination_client.py:123|Loading configuration
    """

    def __init__(
        self,
        default_hydros_cluster_id: str = "hydros-k3s-staging",
        default_hydros_node_id: str = "LOCAL"
    ):
        """
        初始化格式化器。

        Args:
            default_hydros_cluster_id: 上下文未设置时使用的默认集群 ID
            default_hydros_node_id: 上下文未设置时使用的默认节点 ID
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
                biz_component,  # 在智能体上下文中表示 agent_id
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
                biz_component,  # 组件名，例如 "SIM_SDK", "SIM_COORDINATOR"
                "-",  # 基础设施日志不带 agent_id
                source_location,
                message
            ]

        return '|'.join(parts)


def setup_logging(
    level: int = logging.INFO,
    hydros_cluster_id: str = "hydros-k3s-staging",
    hydros_node_id: str = "LOCAL",
    log_file: Optional[str] = None,
    console: bool = True,
    simple: bool = True,
    use_rolling: bool = False,
):
    """
    使用 Hydros 格式化器配置日志。

    Args:
        level: 日志级别（默认 logging.INFO）
        hydros_cluster_id: 日志默认集群 ID（默认 "hydros-k3s-staging"）
        hydros_node_id: 日志默认节点 ID（默认 "LOCAL"）
        log_file: 可选日志文件路径
        console: 是否输出到控制台（默认 True）
        simple: 是否使用本地开发的简化日志格式（默认 True）。
                设置为 False 时使用完整生产格式。
        use_rolling: 日志文件是否按天滚动（默认 False）。
    """
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
                backupCount=30,  # 保留 30 天日志
                encoding='utf-8',
                utc=False
            )
            # 设置轮转文件后缀，使其包含日期
            file_handler.suffix = "%Y-%m-%d"
        else:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')

        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
