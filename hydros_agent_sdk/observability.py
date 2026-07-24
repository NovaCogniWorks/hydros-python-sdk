"""Hydros Agent 进程的可选 OpenTelemetry 初始化与 Span 支撑。

模块本身不会在 import 时配置全局 tracer provider 或连接 Collector。
应用组合根需要显式调用 :func:`configure_opentelemetry`，并在退出时关闭
返回的 :class:`ObservabilityHandle`。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Mapping, Optional
from urllib.parse import urlparse, urlunparse


logger = logging.getLogger(__name__)


def parse_resource_attributes(
    raw_attributes: Optional[str] = None,
) -> Dict[str, str]:
    """解析 ``OTEL_RESOURCE_ATTRIBUTES``，不要求安装 OpenTelemetry。"""
    attributes: Dict[str, str] = {}
    raw_value = raw_attributes
    if raw_value is None:
        raw_value = os.getenv("OTEL_RESOURCE_ATTRIBUTES", "")

    for item in raw_value.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            attributes[key] = value
    return attributes


def resolve_resource_attributes(
    default_service_name: str,
    hydros_cluster_id: Optional[str] = None,
    hydros_node_id: Optional[str] = None,
) -> Dict[str, str]:
    """解析日志和 Trace 共用的服务、环境与 K3s 资源属性。"""
    attributes = parse_resource_attributes()
    attributes.setdefault(
        "service.name",
        os.getenv("OTEL_SERVICE_NAME", default_service_name),
    )

    app_env = os.getenv("APP_ENV")
    cluster_id = os.getenv("HYDROS_CLUSTER_ID") or hydros_cluster_id
    namespace = os.getenv("HYDROS_K3S_NAMESPACE") or os.getenv("KUBE_NAMESPACE")
    pod_name = os.getenv("POD_NAME") or os.getenv("HOSTNAME") or hydros_node_id

    if app_env:
        attributes.setdefault("deployment.environment", app_env)
    if cluster_id:
        attributes.setdefault("k8s.cluster.name", cluster_id)
    if namespace:
        attributes.setdefault("k8s.namespace.name", namespace)
    if pod_name:
        attributes.setdefault("k8s.pod.name", pod_name)
    return attributes


def _resolve_sampler():
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        ParentBased,
        TraceIdRatioBased,
    )

    sampler_name = os.getenv("OTEL_TRACES_SAMPLER", "always_on").strip().lower()
    if sampler_name in {"always_off", "alwaysoff"}:
        return ALWAYS_OFF
    if sampler_name in {"traceidratio", "parentbased_traceidratio"}:
        raw_ratio = os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")
        try:
            ratio = float(raw_ratio)
        except ValueError:
            logger.warning(
                "Invalid OTEL_TRACES_SAMPLER_ARG=%r; falling back to 1.0",
                raw_ratio,
            )
            ratio = 1.0
        ratio = min(1.0, max(0.0, ratio))
        ratio_sampler = TraceIdRatioBased(ratio)
        if sampler_name == "parentbased_traceidratio":
            return ParentBased(ratio_sampler)
        return ratio_sampler
    return ALWAYS_ON


def _http_trace_endpoint(base_endpoint: str) -> str:
    """把 OTLP HTTP 基址规范化为 traces signal endpoint。"""
    explicit_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if explicit_endpoint:
        return explicit_endpoint

    parsed = urlparse(base_endpoint)
    if parsed.path and parsed.path != "/":
        return base_endpoint
    return urlunparse(parsed._replace(path="/v1/traces"))


@dataclass
class ObservabilityHandle:
    """拥有本进程创建的 OpenTelemetry provider 生命周期。"""

    tracer_provider: Optional[Any] = None
    _closed: bool = False

    def shutdown(self) -> None:
        """刷新并关闭 SDK 创建的 provider；可重复调用。"""
        if self._closed or self.tracer_provider is None:
            return
        self._closed = True
        try:
            self.tracer_provider.force_flush()
        finally:
            self.tracer_provider.shutdown()


def configure_opentelemetry(
    default_service_name: str,
    hydros_cluster_id: Optional[str] = None,
    hydros_node_id: Optional[str] = None,
) -> ObservabilityHandle:
    """按标准 OTEL 环境变量显式启用 tracing。

    日志仍通过 JSON stdout 交给 K3s 节点 ``otel-agent`` 采集，避免应用
    同时通过 OTLP Logs 和 stdout 重复上报。
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OpenTelemetry disabled: OTEL_EXPORTER_OTLP_ENDPOINT is not set")
        return ObservabilityHandle()

    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").strip().lower()
    if protocol not in {"grpc", "http/protobuf"}:
        logger.warning(
            "OpenTelemetry disabled: unsupported OTEL_EXPORTER_OTLP_PROTOCOL=%s",
            protocol,
        )
        return ObservabilityHandle()

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint)
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=_http_trace_endpoint(endpoint))
    except ImportError as exc:
        logger.warning("OpenTelemetry disabled: dependency import failed: %s", exc)
        return ObservabilityHandle()

    attributes = resolve_resource_attributes(
        default_service_name=default_service_name,
        hydros_cluster_id=hydros_cluster_id,
        hydros_node_id=hydros_node_id,
    )
    provider = TracerProvider(
        resource=Resource.create(attributes),
        sampler=_resolve_sampler(),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    if trace.get_tracer_provider() is not provider:
        provider.shutdown()
        logger.warning(
            "OpenTelemetry provider already configured by the host application; "
            "Hydros Agent SDK will reuse the host provider"
        )
        return ObservabilityHandle()

    logger.info(
        "OpenTelemetry enabled: service.name=%s endpoint=%s protocol=%s",
        attributes["service.name"],
        endpoint,
        protocol,
    )
    return ObservabilityHandle(tracer_provider=provider)


@contextmanager
def observe_span(
    name: str,
    attributes: Optional[Mapping[str, Any]] = None,
) -> Iterator[None]:
    """在已安装 OTel API 时创建当前 Span，否则无副作用地执行代码块。"""
    try:
        from opentelemetry import trace
    except ImportError:
        yield
        return

    span_attributes = {
        key: value
        for key, value in (attributes or {}).items()
        if value is not None and isinstance(value, (bool, str, int, float))
    }
    tracer = trace.get_tracer("hydros_agent_sdk")
    with tracer.start_as_current_span(name, attributes=span_attributes):
        yield
