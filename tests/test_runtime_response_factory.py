from hydros_agent_sdk.runtime import AgentContext, ResponseFactory
from hydros_agent_sdk.protocol.commands import TickCmdRequest, SimTaskInitRequest
from hydros_agent_sdk.protocol.models import (
    AgentBizStatus,
    AgentDriveMode,
    CommandStatus,
    HydroAgent,
    HydroAgentInstance,
    SimulationContext,
)


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


def test_runtime_exports_are_available():
    assert AgentContext is not None
    assert ResponseFactory is not None


def test_response_factory_creates_standard_tick_failure():
    context = make_context()
    agent = make_agent(context)
    request = TickCmdRequest(command_id="CMD_TICK", context=context, step=3)

    response = ResponseFactory.tick_failed(
        agent,
        request,
        error_code="AGENT_TICK_FAILURE",
        error_message="failed",
    )

    assert response.command_id == "CMD_TICK"
    assert response.context is context
    assert response.command_status == CommandStatus.FAILED
    assert response.error_code == "AGENT_TICK_FAILURE"
    assert response.error_message == "failed"
    assert response.source_agent_instance is agent
    assert response.broadcast is False


def test_response_factory_creates_init_success_defaults():
    context = make_context()
    agent = make_agent(context)
    request = SimTaskInitRequest(
        command_id="CMD_INIT",
        context=context,
        agent_list=[
            HydroAgent(
                agent_code="TEST_AGENT",
                agent_type="TEST_AGENT",
                agent_name="Test Agent",
                agent_configuration_url="",
            )
        ],
    )

    response = ResponseFactory.init_succeed(agent, request)

    assert response.command_id == "CMD_INIT"
    assert response.command_status == CommandStatus.SUCCEED
    assert response.created_agent_instances == [agent]
    assert response.managed_top_objects == {}
