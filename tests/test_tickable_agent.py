from hydros_agent_sdk.agents.tickable_agent import TickableAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitResponse,
    SimTaskTerminateResponse,
    TickCmdRequest,
)
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    AgentDriveMode,
    CommandStatus,
    SimulationContext,
)
from hydros_agent_sdk.state_manager import AgentStateManager


class FakeClient:
    def __init__(self):
        self.state_manager = AgentStateManager()
        self.topic = "/hydros/commands/coordination/test"
        self.mqtt_client = object()
        self.enqueued = []

    def enqueue(self, response):
        self.enqueued.append(response)


class MinimalTickableAgent(TickableAgent):
    def on_init(self, request):
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=self.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False,
        )

    def on_tick_simulation(self, request: TickCmdRequest):
        return []

    def on_terminate(self, request):
        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=self.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )


def test_tickable_agent_can_be_instantiated():
    context = SimulationContext(biz_scene_instance_id="TASK_001")
    agent = MinimalTickableAgent(
        sim_coordination_client=FakeClient(),
        agent_id="AGT_TEST",
        agent_code="TEST_AGENT",
        agent_type="TEST_AGENT",
        agent_name="Test Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        agent_status=AgentStatus.INIT,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )

    assert agent.current_step == 0
    assert agent.time_series_cache.get_value(1, "water_level", agent.current_step) is None


def test_tickable_agent_exposes_runtime_context():
    context = SimulationContext(biz_scene_instance_id="TASK_001")
    client = FakeClient()
    agent = MinimalTickableAgent(
        sim_coordination_client=client,
        agent_id="AGT_TEST",
        agent_code="TEST_AGENT",
        agent_type="TEST_AGENT",
        agent_name="Test Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        agent_status=AgentStatus.INIT,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )

    runtime_context = agent.runtime_context
    assert runtime_context.agent is agent
    assert runtime_context.client is client
    assert runtime_context.state_manager is client.state_manager
    assert runtime_context.config is agent.properties
