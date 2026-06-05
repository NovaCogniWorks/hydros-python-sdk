"""
智能体运行时上下文。

AgentContext 是智能体常用运行时服务的小型门面。新代码可以依赖稳定的上下文对象，
现有智能体仍可继续直接使用 sim_coordination_client、state_manager 和 properties。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydros_agent_sdk.base_agent import BaseHydroAgent
    from hydros_agent_sdk.coordination_client import SimCoordinationClient
    from hydros_agent_sdk.state_manager import AgentStateManager


class AgentContext:
    """
    暴露给智能体实现的轻量运行时门面。

    Phase 2 中刻意保持较窄边界。后续可以在这里增加更多运行时服务，
    而不强迫智能体代码依赖具体 MQTT/client 内部实现。
    """

    def __init__(
        self,
        client: "SimCoordinationClient",
        state_manager: "AgentStateManager",
        agent: "BaseHydroAgent",
    ):
        self.client = client
        self.state_manager = state_manager
        self.agent = agent

    @property
    def logger(self) -> logging.Logger:
        """限定到当前 agent code 的 logger。"""
        return logging.getLogger(self.agent.agent_code)

    @property
    def config(self) -> Any:
        """智能体配置属性。"""
        return self.agent.properties

    @property
    def context(self):
        """该智能体实例的仿真上下文。"""
        return self.agent.context

    def send_response(self, response) -> None:
        """通过协调客户端队列发送响应。"""
        self.client.enqueue(response)
