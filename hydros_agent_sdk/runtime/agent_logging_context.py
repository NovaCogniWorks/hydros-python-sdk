"""Agent 调用日志上下文设置。"""

from __future__ import annotations

from hydros_agent_sdk.logging_config import set_biz_component, set_biz_scene_instance_id


class AgentLoggingContextSetter:
    """在运行时调用 Agent 前设置日志上下文。"""

    def set_for_agent(self, agent) -> None:
        agent_instance = getattr(agent, "instance", agent)

        agent_id = getattr(agent, "agent_id", None) or getattr(agent_instance, "agent_id", None)
        if agent_id:
            set_biz_component(agent_id)

        context = getattr(agent, "context", None) or getattr(agent_instance, "context", None)
        biz_scene_instance_id = getattr(context, "biz_scene_instance_id", None)
        if biz_scene_instance_id:
            set_biz_scene_instance_id(biz_scene_instance_id)
