"""
Common ID generators for Hydros SDK.
"""

from __future__ import annotations

import string
from datetime import datetime
from enum import Enum
from secrets import choice
from typing import Any


def _timestamp_str() -> str:
    return datetime.now().strftime("%Y%m%d%H%M")


def _random_alphanumeric(length: int) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(choice(alphabet) for _ in range(length))


def generate_agent_instance_id(agent_code: str) -> str:
    """Generate agent instance ID in Java-compatible format."""
    return f"AGT{_timestamp_str()}{_random_alphanumeric(6)}_{agent_code}"


def generate_system_command_id() -> str:
    return f"SYSCMD{_timestamp_str()}{_random_alphanumeric(12)}"


def generate_agent_command_id() -> str:
    return f"AGTCMD{_timestamp_str()}{_random_alphanumeric(12)}"


def generate_coordination_command_id() -> str:
    return f"SIMCMD{_timestamp_str()}{_random_alphanumeric(12)}"


def generate_alert_id() -> str:
    return f"RISK{_timestamp_str()}{_random_alphanumeric(12)}"


def generate_sim_task_id() -> str:
    return f"TASK{_timestamp_str()}{_random_alphanumeric(12)}"


def generate_hydro_event_id(hydro_event_type: str) -> str:
    return f"EVENT{hydro_event_type}{_timestamp_str()}{_random_alphanumeric(6)}"


def generate_mqtt_client_id(component: Any) -> str:
    component_name = component.name if isinstance(component, Enum) else str(component)
    return f"MQTT_CLIENT_{component_name}_{_timestamp_str()}_{_random_alphanumeric(8)}"


def generate_monitor_rule_id() -> str:
    return f"MRULE_{_timestamp_str()}_{_random_alphanumeric(8)}"


def generate_data_series_id() -> str:
    return f"TIMESERIES_{_timestamp_str()}_{_random_alphanumeric(8)}"


def generate_sse_session_id(task_type: Any) -> str:
    task_type_name = task_type.name if isinstance(task_type, Enum) else str(task_type)
    return f"{task_type_name}_SSE_{_timestamp_str()}_{_random_alphanumeric(8)}"


def generate_user_id() -> str:
    return f"U{_timestamp_str()}{_random_alphanumeric(8)}"
