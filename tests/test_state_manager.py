from hydros_agent_sdk.protocol.models import (
    AgentBizStatus,
    AgentDriveMode,
    HydroAgentInstance,
    SimulationContext,
)
from hydros_agent_sdk.state_manager import AgentStateManager, TaskStatus


def make_context():
    return SimulationContext(biz_scene_instance_id="TASK_001")


def make_agent(context, agent_id="AGT_TEST", node_id="node"):
    return HydroAgentInstance(
        agent_code="TEST_AGENT",
        agent_type="TEST_AGENT",
        agent_name="Test Agent",
        agent_configuration_url="",
        agent_id=agent_id,
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster",
        hydros_node_id=node_id,
        context=context,
        agent_biz_status=AgentBizStatus.INIT,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )


def test_init_task_registers_active_context_and_agents():
    state_manager = AgentStateManager()
    context = make_context()
    agent = make_agent(context)

    state_manager.init_task(context, [agent])

    assert state_manager.has_active_context(context) is True
    assert state_manager.get_task_state(context.biz_scene_instance_id).status == TaskStatus.ACTIVE
    assert state_manager.get_agent_instance(agent.agent_id) is agent
    assert state_manager.get_agents_for_context(context.biz_scene_instance_id) == [agent]


def test_local_remote_tracking_and_unregister_cleanup():
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    context = make_context()
    local_agent = make_agent(context, node_id="node")
    remote_agent = make_agent(context, agent_id="AGT_REMOTE", node_id="remote")

    state_manager.add_local_agent(local_agent)
    assert state_manager.is_local_agent(local_agent) is True
    assert state_manager.is_remote_agent(remote_agent) is True

    state_manager.register_agent_instance(local_agent)
    state_manager.unregister_agent_instance(local_agent.agent_id)
    assert state_manager.get_agent_instance(local_agent.agent_id) is None
    assert state_manager.is_local_agent(local_agent) is False


def test_terminate_task_marks_task_terminated_and_removes_active_context():
    state_manager = AgentStateManager()
    context = make_context()
    agent = make_agent(context)

    state_manager.init_task(context, [agent])
    state_manager.terminate_task(context)

    task_state = state_manager.get_task_state(context.biz_scene_instance_id)
    assert task_state.status == TaskStatus.TERMINATED
    assert task_state.terminated_at is not None
    assert state_manager.has_active_context(context) is False
    assert state_manager.get_active_tasks() == []
