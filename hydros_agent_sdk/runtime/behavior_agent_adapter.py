"""把组合式开发者行为适配到既有协调运行时。"""

from __future__ import annotations

from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.developer_api import AgentBehavior, AgentExecutionContext, AgentIdentity
from hydros_agent_sdk.runtime.response_factory import ResponseFactory


class BehaviorAgentAdapter(BaseHydroAgent):
    """内部运行时适配器；开发者不需要继承此类。"""

    def __init__(self, behavior: AgentBehavior, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._behavior = behavior
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
    def behavior(self) -> AgentBehavior:
        return self._behavior

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
        response = self._behavior.on_init(self.execution_context, request)
        return response or ResponseFactory.init_succeed(self, request)

    def on_tick(self, request):
        response = self._behavior.on_tick(self.execution_context, request)
        return response or ResponseFactory.tick_succeed(self, request)

    def on_terminate(self, request):
        response = self._behavior.on_terminate(self.execution_context, request)
        return response or ResponseFactory.terminate_succeed(self, request)

    def on_time_series_data_update(self, request):
        response = self._behavior.on_time_series_data_update(self.execution_context, request)
        return response or ResponseFactory.time_series_data_update_succeed(self, request)

    def on_outflow_time_series_data_update(self, request):
        response = self._behavior.on_outflow_time_series_data_update(self.execution_context, request)
        return response or ResponseFactory.outflow_time_series_data_update_succeed(self, request)

    def on_time_series_calculation(self, request):
        return self._behavior.on_time_series_calculation(self.execution_context, request)

    def on_outflow_time_series(self, request):
        return self._behavior.on_outflow_time_series(self.execution_context, request)
