"""
Hydros Agent SDK 日志配置。

提供带 Python 风格源码位置的自定义格式化器，便于在 VSCode 中跳转。

日志格式会随上下文变化：

1. 智能体业务逻辑（带 biz_scene_instance_id）：
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_scene_instance_id}|${agent_id}|coordination_client.py:123|message

2. SDK 基础设施（不带 biz_scene_instance_id）：
   ${hydros_cluster_id}|${hydros_node_id}|2026-01-28 23:29:48|INFO|${biz_component}|-|coordination_client.py:123|message

格式字段说明：
- hydros_cluster_id（例如 "cluster-a"）
- hydros_node_id（例如 "node-a"）
- 时间戳（yyyy-MM-dd HH:mm:ss）
- 日志级别（5 个字符，左对齐）
- biz_scene_instance_id（来自 SimulationContext）或 biz_component（例如 "SIM_SDK", "SIM_COORDINATOR"）
- agent_id（来自 HydroAgentInstance）或基础设施日志中的 "-"
- 源码位置（filename:lineno），可在 VSCode 中点击跳转
- 消息正文
"""

import json
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from contextvars import ContextVar
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone

from hydros_agent_sdk.observability import resolve_resource_attributes

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python 3.9+ normally provides zoneinfo
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

# 用于类 MDC 功能的上下文变量（类似 Java MDC）
_biz_scene_instance_id: ContextVar[Optional[str]] = ContextVar('biz_scene_instance_id', default=None)
_biz_component: ContextVar[Optional[str]] = ContextVar('biz_component', default=None)
_hydros_cluster_id: ContextVar[Optional[str]] = ContextVar('hydros_cluster_id', default=None)
_hydros_node_id: ContextVar[Optional[str]] = ContextVar('hydros_node_id', default=None)
_LOG_RECORD_BUILTINS = set(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}


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
    - 智能体：cluster-a|node-a|2026-01-28 23:29:48|INFO |TASK202601282328VG3IE7H3CA0F|AGENT_001|coordination_client.py:123|Processing command
    - SDK：   cluster-a|node-a|2026-01-28 23:29:48|INFO |SIM_SDK|-|coordination_client.py:123|Loading configuration
    """

    def __init__(
        self,
        default_hydros_cluster_id: Optional[str] = None,
        default_hydros_node_id: Optional[str] = None,
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
        hydros_cluster_id = get_hydros_cluster_id() or self.default_hydros_cluster_id or "-"
        hydros_node_id = get_hydros_node_id() or self.default_hydros_node_id or "-"
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


def _resolve_timezone(timezone_name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass
    if timezone_name == "Asia/Shanghai":
        return timezone(timedelta(hours=8), name="Asia/Shanghai")
    return timezone.utc


def _current_trace_identifiers() -> Dict[str, str]:
    try:
        from opentelemetry import trace
    except ImportError:
        return {}

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


class HydrosJsonFormatter(logging.Formatter):
    """输出供 K3s filelog receiver 与 Loki 采集的单行 JSON。"""

    def __init__(
        self,
        default_service_name: str = "hydros-agent",
        default_hydros_cluster_id: Optional[str] = None,
        default_hydros_node_id: Optional[str] = None,
        timezone_name: Optional[str] = None,
    ):
        super().__init__()
        self._timezone = _resolve_timezone(
            timezone_name or os.getenv("HYDROS_LOG_TIMEZONE", "Asia/Shanghai")
        )
        self._resource_attributes = resolve_resource_attributes(
            default_service_name=default_service_name,
            hydros_cluster_id=default_hydros_cluster_id,
            hydros_node_id=default_hydros_node_id,
        )
        self._default_hydros_cluster_id = default_hydros_cluster_id
        self._default_hydros_node_id = default_hydros_node_id

    def format(self, record: logging.LogRecord) -> str:
        biz_scene_instance_id = get_biz_scene_instance_id()
        biz_component = get_biz_component()
        hydros_cluster_id = (
            get_hydros_cluster_id()
            or self._default_hydros_cluster_id
            or self._resource_attributes.get("k8s.cluster.name")
        )
        hydros_node_id = (
            get_hydros_node_id()
            or self._default_hydros_node_id
            or self._resource_attributes.get("k8s.pod.name")
        )

        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=self._timezone,
            ).isoformat(timespec="milliseconds"),
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            **self._resource_attributes,
            **_current_trace_identifiers(),
            "source.file": record.filename,
            "source.function": record.funcName,
            "source.line": record.lineno,
        }
        if hydros_cluster_id:
            payload["hydros_cluster_id"] = hydros_cluster_id
        if hydros_node_id:
            payload["hydros_node_id"] = hydros_node_id
        if biz_scene_instance_id:
            payload["biz_scene_instance_id"] = biz_scene_instance_id
        if biz_component:
            if biz_scene_instance_id:
                payload["agent_id"] = biz_component
            else:
                payload["biz_component"] = biz_component

        for key, value in record.__dict__.items():
            if (
                key not in _LOG_RECORD_BUILTINS
                and key not in payload
                and not key.startswith("_")
            ):
                payload[key] = value

        if record.exc_info:
            exception_type = record.exc_info[0]
            exception_value = record.exc_info[1]
            payload["exception.type"] = (
                exception_type.__name__ if exception_type is not None else None
            )
            payload["exception.message"] = str(exception_value)
            payload["exception.stacktrace"] = self.formatException(record.exc_info)

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )


def setup_logging(
    level: int = logging.INFO,
    hydros_cluster_id: Optional[str] = None,
    hydros_node_id: Optional[str] = None,
    log_file: Optional[str] = None,
    console: bool = True,
    simple: bool = True,
    use_rolling: bool = False,
    format_style: Optional[str] = None,
    service_name: str = "hydros-agent",
    replace_handlers: bool = True,
):
    """
    使用 Hydros 格式化器配置日志。

    Args:
        level: 日志级别（默认 logging.INFO）
        hydros_cluster_id: 可选日志集群 ID；完整日志缺少该值时输出 "-"
        hydros_node_id: 可选日志节点 ID；完整日志缺少该值时输出 "-"
        log_file: 可选日志文件路径
        console: 是否输出到控制台（默认 True）
        simple: 是否使用本地开发的简化日志格式（默认 True）。
                设置为 False 时使用完整生产格式。
        use_rolling: 日志文件是否按天滚动（默认 False）。
        format_style: 显式格式，可选 ``simple``、``full`` 或 ``json``。
                      未提供时继续兼容 ``simple`` 参数。
        service_name: 未设置 ``OTEL_SERVICE_NAME`` 时写入 JSON 的应用名。
        replace_handlers: 是否移除调用方已有的 root handlers。默认保持历史行为。
    """
    # 按模式创建 formatter
    resolved_format = (format_style or ("simple" if simple else "full")).strip().lower()
    if resolved_format == "json":
        formatter = HydrosJsonFormatter(
            default_service_name=service_name,
            default_hydros_cluster_id=hydros_cluster_id,
            default_hydros_node_id=hydros_node_id,
        )
    elif resolved_format == "simple":
        formatter = HydrosSimpleFormatter()
    elif resolved_format == "full":
        formatter = HydrosFormatter(
            default_hydros_cluster_id=hydros_cluster_id,
            default_hydros_node_id=hydros_node_id
        )
    else:
        raise ValueError(
            "format_style must be one of: simple, full, json; "
            f"got {resolved_format!r}"
        )

    # 获取 root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if replace_handlers:
        root_logger.handlers.clear()
    else:
        for handler in list(root_logger.handlers):
            if getattr(handler, "_hydros_sdk_handler", None):
                root_logger.removeHandler(handler)
                handler.close()

    # 添加控制台 handler
    if console:
        console_handler = logging.StreamHandler(
            sys.stdout if resolved_format == "json" else None
        )
        console_handler._hydros_sdk_handler = "console"  # type: ignore[attr-defined]
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

        file_handler._hydros_sdk_handler = "file"  # type: ignore[attr-defined]
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
