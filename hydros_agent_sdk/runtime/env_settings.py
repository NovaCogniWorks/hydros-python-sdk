"""
Shared runtime environment settings.

This module centralizes deployment-level defaults so agents and factories do not
each need to know how the SDK env.properties and OS environment variables are
layered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional


DEFAULT_METRICS_TOPIC = "/hydros/data/edges/{hydros_cluster_id}"
DEFAULT_MQTT_TOPIC = "/hydros/commands/coordination/{hydros_cluster_id}"


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_value(*values: Optional[str]) -> Optional[str]:
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return None


@dataclass(frozen=True)
class RuntimeEnvSettings:
    """Deployment-level settings shared by runtime modules."""

    raw: Dict[str, str] = field(default_factory=dict)
    hydros_cluster_id: Optional[str] = None
    hydros_node_id: Optional[str] = None
    mqtt_broker_url: Optional[str] = None
    mqtt_broker_port: Optional[str] = None
    mqtt_topic: Optional[str] = None
    metrics_topic: Optional[str] = None
    mpc_service_base_url: Optional[str] = None

    @classmethod
    def from_config(cls, env_config: Optional[Mapping[str, str]] = None) -> "RuntimeEnvSettings":
        config = {str(key): str(value) for key, value in (env_config or {}).items() if value is not None}

        hydros_cluster_id = _first_value(os.getenv("HYDROS_CLUSTER_ID"), config.get("hydros_cluster_id"))
        hydros_node_id = _first_value(os.getenv("HYDROS_NODE_ID"), config.get("hydros_node_id"))
        metrics_topic = _first_value(
            os.getenv("HYDROS_METRICS_TOPIC"),
            os.getenv("METRICS_TOPIC"),
            config.get("metrics_topic"),
        )
        mqtt_topic = _first_value(config.get("mqtt_topic"))
        if not mqtt_topic and hydros_cluster_id:
            mqtt_topic = DEFAULT_MQTT_TOPIC.format(hydros_cluster_id=hydros_cluster_id)

        return cls(
            raw=config,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            mqtt_broker_url=_first_value(os.getenv("MQTT_BROKER_URL"), config.get("mqtt_broker_url")),
            mqtt_broker_port=_first_value(os.getenv("MQTT_BROKER_PORT"), config.get("mqtt_broker_port")),
            mqtt_topic=mqtt_topic,
            metrics_topic=metrics_topic,
            mpc_service_base_url=_first_value(
                os.getenv("HYDROS_MPC_SERVICE_BASE_URL"),
                os.getenv("MPC_SERVICE_BASE_URL"),
                config.get("mpc_service_base_url"),
            ),
        )

    def render_topic(self, topic_template: Optional[str], cluster_id: Optional[str] = None) -> Optional[str]:
        topic = _clean(topic_template)
        if not topic:
            return None
        return topic.replace("{hydros_cluster_id}", cluster_id or self.hydros_cluster_id or "")

    def rendered_metrics_topic(self, cluster_id: Optional[str] = None) -> Optional[str]:
        return self.render_topic(self.metrics_topic or DEFAULT_METRICS_TOPIC, cluster_id=cluster_id)


def load_runtime_env_settings(
    env_file: str = "./env.properties",
    env_config: Optional[Mapping[str, str]] = None,
    suppress_errors: bool = True,
) -> RuntimeEnvSettings:
    """Load shared runtime settings from an optional dict or env.properties."""
    if env_config is None:
        try:
            from hydros_agent_sdk.config_loader import load_env_config

            env_config = load_env_config(env_file)
        except Exception:
            if not suppress_errors:
                raise
            env_config = {}
    return RuntimeEnvSettings.from_config(env_config)
