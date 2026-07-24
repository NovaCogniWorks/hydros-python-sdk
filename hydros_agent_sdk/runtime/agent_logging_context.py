"""Agent 调用日志上下文设置。"""

from __future__ import annotations

from hydros_agent_sdk.logging_config import (
    LogContext,
    set_biz_component,
    set_biz_scene_instance_id,
)


class AgentLoggingContextSetter:
    """在运行时调用 Agent 前设置日志上下文。"""

    def set_for_agent(self, agent) -> None:
        """兼容既有调用：为当前执行上下文直接设置 Agent 字段。"""
        agent_id, biz_scene_instance_id = self._resolve(agent)
        if agent_id:
            set_biz_component(agent_id)
        if biz_scene_instance_id:
            set_biz_scene_instance_id(biz_scene_instance_id)

    def bind_for_agent(self, agent) -> LogContext:
        """返回可可靠恢复上层 ContextVar 的 Agent 日志上下文。"""
        agent_id, biz_scene_instance_id = self._resolve(agent)
        return LogContext(
            biz_scene_instance_id=biz_scene_instance_id,
            biz_component=agent_id,
        )

    @staticmethod
    def _resolve(agent):
        agent_instance = getattr(agent, "instance", agent)

        agent_id = getattr(agent, "agent_id", None) or getattr(agent_instance, "agent_id", None)
        context = getattr(agent, "context", None) or getattr(agent_instance, "context", None)
        biz_scene_instance_id = getattr(context, "biz_scene_instance_id", None)
        return agent_id, biz_scene_instance_id
