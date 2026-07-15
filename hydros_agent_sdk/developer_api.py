"""面向外部开发者的组合式 Agent API。"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentIdentity:
    """开发者可读取的 Agent 标识，不暴露内部运行时对象。"""

    agent_id: str
    agent_code: str
    agent_type: str
    agent_name: str


class AgentExecutionContext:
    """开发者可依赖的运行时门面，不暴露 SDK 的协议模型继承结构。"""

    def __init__(self, client, identity: AgentIdentity, simulation_context, properties) -> None:
        self._client = client
        self._identity = identity
        self._simulation_context = simulation_context
        self._properties = properties

    @property
    def agent(self) -> AgentIdentity:
        return self._identity

    @property
    def simulation_context(self):
        return self._simulation_context

    @property
    def config(self):
        return self._properties

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self._identity.agent_code)

    def send_response(self, response) -> None:
        self._client.enqueue(response)


class CustomAgent(ABC):
    """开发者实现的自定义 Agent 生命周期，不继承协议 DTO 或运行时实现。"""

    def on_init(self, runtime: AgentExecutionContext, request):
        return None

    def on_tick(self, runtime: AgentExecutionContext, request):
        return None

    def on_terminate(self, runtime: AgentExecutionContext, request):
        return None

    def on_time_series_data_update(self, runtime: AgentExecutionContext, request):
        return None

    def on_outflow_time_series_data_update(self, runtime: AgentExecutionContext, request):
        return None

    def on_time_series_calculation(self, runtime: AgentExecutionContext, request):
        return None

    def on_outflow_time_series(self, runtime: AgentExecutionContext, request):
        return None


# Historical public name for the original composition API.
AgentBehavior = CustomAgent
