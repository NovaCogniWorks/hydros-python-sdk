"""
智能体指令 runtime 的本地调试和测试辅助工具。
"""

from __future__ import annotations

import logging
import time
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

    def find_unreported_command_logs(self, limit: int = 100):
        return self.runtime.find_unreported_command_logs(limit=limit)

    def report_unreported_command_logs(self, consumer, limit: int = 100):
        return self.runtime.report_unreported_command_logs(consumer=consumer, limit=limit)

    def find_unacked_command_logs(self, limit: int = 100):
        return self.runtime.find_unacked_command_logs(limit=limit)

    def find_incomplete_command_logs(self, statuses=None, limit: int = 100):
        return self.runtime.find_incomplete_command_logs(statuses=statuses, limit=limit)

    def replay_incomplete_requests(self, statuses=None, limit: int = 100):
        if statuses is None:
            return self.runtime.replay_incomplete_requests(limit=limit)
        return self.runtime.replay_incomplete_requests(statuses=statuses, limit=limit)

    def collect_command_log_snapshot(self, limit: int = 100, incomplete_statuses=None):
        if incomplete_statuses is None:
            return self.runtime.collect_command_log_snapshot(limit=limit)
        return self.runtime.collect_command_log_snapshot(
            limit=limit,
            incomplete_statuses=incomplete_statuses,
        )

    def collect_command_log_stats(self, limit: int = 100, incomplete_statuses=None):
        if incomplete_statuses is None:
            return self.runtime.collect_command_log_stats(limit=limit)
        return self.runtime.collect_command_log_stats(
            limit=limit,
            incomplete_statuses=incomplete_statuses,
        )


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


def wait_command_completed(
    runtime: AgentCommandRuntime,
    command_id: str,
    timeout_seconds: float = 5.0,
):
    deadline = time.time() + timeout_seconds
    source_id = runtime.state_manager.get_node_id() or "UNKNOWN"

    while time.time() < deadline:
        entry = runtime.log_store.find_command_log_by_request_id(command_id, source_id)
        if entry and entry.command_response:
            return entry
        time.sleep(0.05)

    raise TimeoutError(f"等待 command_id='{command_id}' 完成超时")


def wait_command_acked(
    runtime: AgentCommandRuntime,
    command_id: str,
    timeout_seconds: float = 5.0,
):
    deadline = time.time() + timeout_seconds
    source_id = runtime.state_manager.get_node_id() or "UNKNOWN"

    while time.time() < deadline:
        entry = runtime.log_store.find_command_log_by_request_id(command_id, source_id)
        if entry and entry.acked:
            return entry
        time.sleep(0.05)

    raise TimeoutError(f"等待 command_id='{command_id}' ACK 超时")


def wait_command_reported(
    runtime: AgentCommandRuntime,
    command_id: str,
    timeout_seconds: float = 5.0,
):
    deadline = time.time() + timeout_seconds
    source_id = runtime.state_manager.get_node_id() or "UNKNOWN"

    while time.time() < deadline:
        entry = runtime.log_store.find_command_log_by_request_id(command_id, source_id)
        if entry and entry.reported:
            return entry
        time.sleep(0.05)

    raise TimeoutError(f"等待 command_id='{command_id}' reported 超时")
