"""
智能体指令处理器抽象。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, Type, TypeVar

from hydros_agent_sdk.error_codes import ErrorCode, ErrorCodes
from hydros_agent_sdk.protocol.models import CommandStatus

from hydros_agent_sdk.protocol.agent_commands.base import AgentCommandRequest, AgentCommandResponse


RequestType = TypeVar("RequestType", bound=AgentCommandRequest)
ResponseType = TypeVar("ResponseType", bound=AgentCommandResponse)


class AgentCommandHandler(ABC, Generic[RequestType, ResponseType]):
    """业务方实现这个类，就能接住一类智能体指令。"""

    @abstractmethod
    def get_command(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def response_type(self) -> Type[ResponseType]:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: RequestType) -> ResponseType:
        raise NotImplementedError

    def build_failure_response(
        self,
        request: RequestType,
        exc: Exception,
        error_code: ErrorCode = ErrorCodes.SYSTEM_ERROR,
    ) -> ResponseType:
        return self.response_type.from_request(
            request,
            command_status=CommandStatus.FAILED,
            success=False,
            error_code=error_code.code,
            error_message=error_code.format_message(type(exc).__name__, str(exc)),
        )
