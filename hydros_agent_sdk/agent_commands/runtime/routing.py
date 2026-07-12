"""
智能体指令路由判断。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from hydros_agent_sdk.protocol.agent_commands.base import AgentCommand, AgentCommandRequest


logger = logging.getLogger(__name__)


class AgentCommandRoutePlanner:
    """只管判断命令该走哪条路，不碰执行细节。"""

    def __init__(
        self,
        state_manager,
        pending_command_predicate: Optional[Callable[[AgentCommand], bool]] = None,
    ):
        self.state_manager = state_manager
        self.pending_command_predicate = pending_command_predicate

    def set_pending_command_predicate(
        self,
        predicate: Optional[Callable[[AgentCommand], bool]],
    ) -> None:
        self.pending_command_predicate = predicate

    def should_execute_locally(self, command: AgentCommandRequest) -> bool:
        return command.target is None or self.state_manager.is_local_agent(command.target)

    def should_track_inbound(self, command: AgentCommand) -> bool:
        return bool(command.target and self.state_manager.is_local_agent(command.target))

    def should_send_remote(self, command: AgentCommand) -> bool:
        return bool(command.target and self.state_manager.is_remote_agent(command.target))

    def is_pending(self, command: AgentCommand) -> bool:
        if self.pending_command_predicate is None:
            return False

        try:
            return bool(self.pending_command_predicate(command))
        except Exception:
            logger.error(
                "pending_command_predicate 执行失败，按非 pending 继续发送: type=%s id=%s",
                command.command_type,
                command.command_id,
                exc_info=True,
            )
            return False
