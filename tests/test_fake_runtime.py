from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import TickCmdRequest, TickCmdResponse
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    AgentDriveMode,
    CommandStatus,
    HydroAgentInstance,
    SimulationContext,
)
from hydros_agent_sdk.state_manager import AgentStateManager
from tests.helpers import FakeRuntime


def make_context():
    return SimulationContext(biz_scene_instance_id="TASK_001")


def make_agent(context):
    return HydroAgentInstance(
        agent_code="TEST_AGENT",
        agent_type="TEST_AGENT",
        agent_name="Test Agent",
        agent_configuration_url="",
        agent_id="AGT_TEST",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )


class TickCallback(SimCoordinationCallback):
    def __init__(self, agent):
        self.agent = agent

    def get_component(self) -> str:
        return self.agent.agent_code

    def on_sim_task_init(self, request):
        return None

    def on_tick(self, request):
        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.agent,
            completed_step=request.step,
            broadcast=False,
        )


def test_fake_runtime_dispatches_command_and_captures_response():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    with FakeRuntime(TickCallback(agent), state_manager=state_manager) as runtime:
        responses = runtime.send(TickCmdRequest(command_id="CMD_TICK", context=context, step=2))

        assert len(responses) == 1
        assert isinstance(responses[0], TickCmdResponse)
        assert responses[0].command_status == CommandStatus.SUCCEED
        assert runtime.responses == responses


def test_fake_runtime_can_publish_queued_responses_through_transport():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    with FakeRuntime(TickCallback(agent), state_manager=state_manager) as runtime:
        runtime.send(TickCmdRequest(command_id="CMD_TICK", context=context, step=2))

        assert len(runtime.transport.published) == 1
        published = runtime.transport.published[0]
        assert published.topic == "/hydros/commands/coordination/test"
        assert '"command_id":"CMD_TICK"' in published.payload
        assert published.qos == 1
