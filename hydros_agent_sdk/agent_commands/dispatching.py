"""发送中央调度产生的控制指令。"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from hydros_agent_sdk.agent_commands.models import AgentCommand

logger = logging.getLogger(__name__)


class ControlCommandDispatcher:
    """发送 agent command，或先转换旧的 dict 控制意图再发送。"""

    def __init__(
        self,
        send_command: Callable[[AgentCommand], None],
        build_station_target_value_request: Callable[..., Optional[AgentCommand]],
    ):
        self.send_command = send_command
        self.build_station_target_value_request = build_station_target_value_request

    def dispatch(self, control_commands: List[Any]) -> None:
        for command in control_commands:
            if isinstance(command, AgentCommand):
                self.send_command(command)
                continue

            target_agent_code = command.get("target_agent_code")
            target_command_type = command.get("target_command_type")
            target_value = command.get("target_value")
            object_id = command.get("object_id")
            object_type = command.get("object_type")

            logger.debug(
                "Control command: target=%s, type=%s, value=%s, object_id=%s",
                target_agent_code,
                target_command_type,
                target_value,
                object_id,
            )

            if not target_agent_code or not target_command_type:
                logger.warning("控制指令缺少必要字段，已跳过: %s", command)
                continue

            command_request = self.build_station_target_value_request(
                target_agent_code=target_agent_code,
                target_command_type=target_command_type,
                target_value=target_value,
                object_id=object_id,
                object_type=object_type,
            )
            if command_request is not None:
                self.send_command(command_request)
