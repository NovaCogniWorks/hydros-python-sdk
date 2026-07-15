"""Adapt a developer-defined CustomAgent to the coordination runtime."""

from __future__ import annotations

from hydros_agent_sdk.base_agent import BaseHydroAgent
from typing import Optional

from hydros_agent_sdk.developer_api import CustomAgent, AgentExecutionContext, AgentIdentity
from hydros_agent_sdk.runtime.response_factory import ResponseFactory


class CustomAgentRuntimeAdapter(BaseHydroAgent):
    """Internal runtime adapter; developers implement ``CustomAgent`` instead."""

    def __init__(
        self,
        custom_agent: Optional[CustomAgent] = None,
        *args,
        behavior: Optional[CustomAgent] = None,
        **kwargs,
    ) -> None:
        if custom_agent is None:
            custom_agent = behavior
        elif behavior is not None and behavior is not custom_agent:
            raise ValueError("custom_agent and behavior must reference the same instance")
        if custom_agent is None:
            raise ValueError("custom_agent is required")

        super().__init__(*args, **kwargs)
        self._custom_agent = custom_agent
        self._execution_context = AgentExecutionContext(
            client=self.sim_coordination_client,
            identity=AgentIdentity(
                agent_id=self.agent_id,
                agent_code=self.agent_code,
                agent_type=self.agent_type,
                agent_name=self.agent_name,
            ),
            simulation_context=self.context,
            properties=self.properties,
        )

    @property
    def custom_agent(self) -> CustomAgent:
        return self._custom_agent

    @property
    def behavior(self) -> CustomAgent:
        """Historical alias for ``custom_agent``."""
        return self.custom_agent

    @property
    def execution_context(self) -> AgentExecutionContext:
        return self._execution_context

    def refresh_execution_context_identity(self) -> None:
        """在 coordinator 同步路由身份后刷新开发者可见的不可变身份快照。"""
        self._execution_context = AgentExecutionContext(
            client=self.sim_coordination_client,
            identity=AgentIdentity(
                agent_id=self.agent_id,
                agent_code=self.agent_code,
                agent_type=self.agent_type,
                agent_name=self.agent_name,
            ),
            simulation_context=self.context,
            properties=self.properties,
        )

    def supports_tick_command(self) -> bool:
        return True

    def on_init(self, request):
        response = self.custom_agent.on_init(self.execution_context, request)
        return response or ResponseFactory.init_succeed(self, request)

    def on_tick(self, request):
        response = self.custom_agent.on_tick(self.execution_context, request)
        return response or ResponseFactory.tick_succeed(self, request)

    def on_terminate(self, request):
        response = self.custom_agent.on_terminate(self.execution_context, request)
        return response or ResponseFactory.terminate_succeed(self, request)

    def on_time_series_data_update(self, request):
        response = self.custom_agent.on_time_series_data_update(self.execution_context, request)
        return response or ResponseFactory.time_series_data_update_succeed(self, request)

    def on_outflow_time_series_data_update(self, request):
        response = self.custom_agent.on_outflow_time_series_data_update(self.execution_context, request)
        return response or ResponseFactory.outflow_time_series_data_update_succeed(self, request)

    def on_time_series_calculation(self, request):
        return self.custom_agent.on_time_series_calculation(self.execution_context, request)

    def on_outflow_time_series(self, request):
        return self.custom_agent.on_outflow_time_series(self.execution_context, request)
