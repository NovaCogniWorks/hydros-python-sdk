"""
Agent command base models and registry.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type, TypeVar

from hydros_agent_sdk.protocol.base import HydroBaseModel
from hydros_agent_sdk.protocol.models import CommandStatus, HydroAgentInstance, SimulationContext


ResponseType = TypeVar("ResponseType", bound="AgentCommandResponse")

_COMMAND_MODEL_REGISTRY: Dict[str, Type["AgentCommand"]] = {}


class HydroCmd(HydroBaseModel):
    """The minimal shared fields across all agent commands."""

    command_id: str


class AgentCommand(HydroCmd):
    """Shared fields for all agent commands."""

    command_type: str
    timestamp_ms: Optional[Any] = None
    command_status: Optional[CommandStatus] = None
    command_response: Optional[str] = None
    source: Optional[HydroAgentInstance] = None
    target: Optional[HydroAgentInstance] = None
    wait_on_util_send: Optional[Any] = None
    security_check: bool = False

    def get_context(self) -> SimulationContext:
        if self.source and self.source.context:
            return self.source.context
        if self.target and self.target.context:
            return self.target.context
        raise ValueError("source 和 target 不能同时为空")

    @property
    def context(self) -> SimulationContext:
        return self.get_context()

    def auth(self) -> None:
        return None

    def is_completed(self) -> bool:
        return self.command_status in {CommandStatus.SUCCEED, CommandStatus.FAILED}


class AgentCommandRequest(AgentCommand):
    """Shared fields for agent command requests."""

    need_ack_reply: Optional[bool] = None
    acked: Optional[bool] = None


class AgentCommandResponse(AgentCommand):
    """Shared fields for agent command responses."""

    success: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @classmethod
    def from_request(cls: Type[ResponseType], request: AgentCommandRequest, **kwargs: Any) -> ResponseType:
        return cls(
            command_id=request.command_id,
            source=request.target,
            target=request.source,
            **kwargs,
        )


def register_agent_command(command_model: Type[AgentCommand]) -> Type[AgentCommand]:
    """Register a concrete command model by its default command_type."""

    field = command_model.model_fields.get("command_type")
    command_type = None if field is None else field.default
    if not isinstance(command_type, str) or not command_type:
        raise ValueError(f"{command_model.__name__} 缺少可注册的 command_type 默认值")

    existing = _COMMAND_MODEL_REGISTRY.get(command_type)
    if existing is not None and existing is not command_model:
        raise ValueError(f"command_type '{command_type}' 已注册到 {existing.__name__}")

    _COMMAND_MODEL_REGISTRY[command_type] = command_model
    return command_model


def get_agent_command_model(command_type: str) -> Type[AgentCommand]:
    command_model = _COMMAND_MODEL_REGISTRY.get(command_type)
    if command_model is None:
        raise ValueError(f"不支持的 agent command_type: {command_type!r}")
    return command_model


def parse_agent_command(payload: AgentCommand | Dict[str, Any]) -> AgentCommand:
    """Parse a command payload using the command registry."""

    if isinstance(payload, AgentCommand):
        return payload

    if not isinstance(payload, dict):
        raise TypeError("agent command payload 必须是 dict 或 AgentCommand 实例")

    command_type = payload.get("command_type")
    if not isinstance(command_type, str) or not command_type:
        raise ValueError("agent command payload 缺少 command_type")

    command_model = get_agent_command_model(command_type)
    return command_model.model_validate(payload)


def list_registered_command_types() -> tuple[str, ...]:
    return tuple(sorted(_COMMAND_MODEL_REGISTRY))
