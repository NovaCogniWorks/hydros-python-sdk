"""智能体指令客户端网关。"""

from __future__ import annotations

from typing import Callable, Optional

from hydros_agent_sdk.protocol.agent_commands.base import AgentCommand
from hydros_agent_sdk.agent_commands.runtime import AgentCommandRuntime
from hydros_agent_sdk.agent_commands.transport.client import AgentCommandClient
from hydros_agent_sdk.state_manager import AgentStateManager


class AgentCommandGateway:
    """管理单个智能体使用的 AgentCommandClient。"""

    def __init__(
        self,
        sim_coordination_client,
        hydros_cluster_id: str,
        state_manager: AgentStateManager,
        client_factory: Callable[..., AgentCommandClient] = AgentCommandClient,
    ):
        self.sim_coordination_client = sim_coordination_client
        self.hydros_cluster_id = hydros_cluster_id
        self.state_manager = state_manager
        self.client_factory = client_factory
        self._agent_command_client: Optional[AgentCommandClient] = None
        self._agent_command_client_started = False
        self._ack_listeners = []
        self._response_listeners = []

    @property
    def client(self) -> Optional[AgentCommandClient]:
        return self._agent_command_client

    @property
    def started(self) -> bool:
        return self._agent_command_client_started

    def get_or_create_agent_command_client(self) -> AgentCommandClient:
        if self._agent_command_client is None:
            client = self.client_factory(
                broker_url=self.sim_coordination_client.broker_url,
                broker_port=self.sim_coordination_client.broker_port,
                hydros_cluster_id=self.hydros_cluster_id,
                state_manager=self.state_manager,
                mqtt_username=getattr(self.sim_coordination_client, "mqtt_username", None),
                mqtt_password=getattr(self.sim_coordination_client, "mqtt_password", None),
            )
            runtime = AgentCommandRuntime(
                state_manager=self.state_manager,
                sender=client.publish_command,
            )
            for listener in self._ack_listeners:
                runtime.add_ack_listener(listener)
            for listener in self._response_listeners:
                runtime.add_response_listener(listener)
            client.bind_runtime(runtime)
            self._agent_command_client = client
        return self._agent_command_client

    def start(self) -> None:
        if self._agent_command_client_started:
            return
        self.get_or_create_agent_command_client().start()
        self._agent_command_client_started = True

    def shutdown(self) -> None:
        if self._agent_command_client is None:
            return
        if not self._agent_command_client_started:
            return
        self._agent_command_client.stop()
        self._agent_command_client_started = False

    def send_command(self, command: AgentCommand) -> None:
        self.start()
        self.get_or_create_agent_command_client().send_command(command)

    def add_ack_listener(self, listener) -> None:
        self._ack_listeners.append(listener)
        if self._agent_command_client is not None:
            self._agent_command_client.runtime.add_ack_listener(listener)

    def add_response_listener(self, listener) -> None:
        self._response_listeners.append(listener)
        if self._agent_command_client is not None:
            self._agent_command_client.runtime.add_response_listener(listener)
