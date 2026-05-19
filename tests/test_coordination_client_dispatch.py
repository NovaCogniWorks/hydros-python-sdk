from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.protocol.commands import (
    SimTaskTerminateResponse,
    TickCmdRequest,
    TickCmdResponse,
)
from hydros_agent_sdk.protocol.models import (
    AgentBizStatus,
    AgentDriveMode,
    CommandStatus,
    HydroAgentInstance,
    SimulationContext,
)
from hydros_agent_sdk.state_manager import AgentStateManager


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
        agent_biz_status=AgentBizStatus.ACTIVE,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )


class ReturningCallback(SimCoordinationCallback):
    def __init__(self, agent):
        self.agent = agent

    def get_component(self) -> str:
        return "TEST_AGENT"

    def on_sim_task_init(self, request):
        return None

    def on_tick(self, request):
        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.agent,
            broadcast=False,
        )


class RaisingCallback(ReturningCallback):
    def on_tick(self, request):
        raise RuntimeError("boom")


def make_client(callback, state_manager):
    return SimCoordinationClient(
        broker_url="tcp://localhost",
        broker_port=1883,
        topic="/hydros/commands/coordination/test",
        sim_coordination_callback=callback,
        state_manager=state_manager,
    )


def test_callback_returned_response_is_enqueued():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    client = make_client(ReturningCallback(agent), state_manager)

    request = TickCmdRequest(command_id="CMD_TICK", context=context, step=1)
    client._handle_incoming_message(request)

    response = client.out_message_queue.get_nowait()
    assert isinstance(response, TickCmdResponse)
    assert response.command_status == CommandStatus.SUCCEED
    assert response.command_id == "CMD_TICK"


def test_handler_exception_becomes_failed_response_when_agent_context_exists():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    client = make_client(RaisingCallback(agent), state_manager)

    request = TickCmdRequest(command_id="CMD_TICK", context=context, step=1)
    client._handle_incoming_message(request)

    response = client.out_message_queue.get_nowait()
    assert isinstance(response, TickCmdResponse)
    assert response.command_status == CommandStatus.FAILED
    assert response.error_code == "AGENT_TICK_FAILURE"
    assert "boom" in response.error_message


def test_terminate_response_from_same_node_is_sendable_after_local_agent_removed():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    client = make_client(ReturningCallback(agent), state_manager)

    response = SimTaskTerminateResponse(
        command_id="CMD_TERM",
        context=context,
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=agent,
        broadcast=False,
    )

    assert client._should_send(response) is True
