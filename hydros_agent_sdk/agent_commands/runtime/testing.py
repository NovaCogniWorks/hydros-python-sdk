"""
智能体指令 runtime 的本地调试和测试辅助工具。
"""

from __future__ import annotations

import logging
from typing import Dict

from hydros_agent_sdk.agent_commands.runtime.handlers import AgentCommandHandler
from hydros_agent_sdk.agent_commands.runtime.runtime import AgentCommandRuntime

logger = logging.getLogger(__name__)


class LocalRuntimeAgentCommandClient:
    """把 AgentCommandRuntime 包一层，方便直接绑到 BaseHydroAgent。"""

    def __init__(self, runtime: AgentCommandRuntime):
        self.runtime = runtime
        self.state_manager = runtime.state_manager

    def register_handler(self, handler: AgentCommandHandler) -> None:
        self.runtime.register_handler(handler)

    def send_command(self, command) -> None:
        self.runtime.send_command(command)

    def set_pending_command_predicate(self, predicate) -> None:
        self.runtime.set_pending_command_predicate(predicate)


class InMemoryNodeBridge:
    """用内存把多个 runtime 串起来，模拟跨节点投递。"""

    def __init__(self):
        self._runtime_by_node_id: Dict[str, AgentCommandRuntime] = {}

    def register_runtime(self, node_id: str, runtime: AgentCommandRuntime) -> None:
        self._runtime_by_node_id[node_id] = runtime

    def get_runtime(self, node_id: str) -> AgentCommandRuntime:
        runtime = self._runtime_by_node_id.get(node_id)
        if runtime is None:
            raise KeyError(f"没有找到 node_id='{node_id}' 对应的 runtime")
        return runtime

    def build_sender(self, source_node_id: str):
        def _send(command) -> None:
            if command.target is None:
                raise ValueError("agent command target 不能为空")

            target_node_id = command.target.hydros_node_id
            target_runtime = self.get_runtime(target_node_id)

            logger.info(
                "桥接转发 agent command: %s -> %s, type=%s, id=%s",
                source_node_id,
                target_node_id,
                command.command_type,
                command.command_id,
            )
            target_runtime.handle_incoming_command(command)

        return _send
