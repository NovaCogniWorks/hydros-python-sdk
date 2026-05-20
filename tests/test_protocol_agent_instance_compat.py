from hydros_agent_sdk.protocol.commands import AgentInstanceStatusReport
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    AgentInstanceStatus,
    AgentStatus,
    HydroAgentInstance,
    SimulationContext,
)


def make_context():
    return SimulationContext(biz_scene_instance_id="TASK_001")


def test_agent_instance_accepts_legacy_sdk_names_and_serializes_java_names():
    context = make_context()

    agent = HydroAgentInstance(
        agent_code="TEST_AGENT",
        agent_type="TEST_AGENT",
        agent_name="Test Agent",
        agent_configuration_url="",
        agent_id="AGT_TEST",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster-a",
        hydros_node_id="node-a",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )

    assert agent.cluster_id == "cluster-a"
    assert agent.node_id == "node-a"
    assert agent.hydros_cluster_id == "cluster-a"
    assert agent.hydros_node_id == "node-a"
    assert agent.agent_status == AgentStatus.ACTIVE

    payload = agent.model_dump(mode="json", by_alias=True)
    assert payload["cluster_id"] == "cluster-a"
    assert payload["node_id"] == "node-a"
    assert payload["agent_status"] == "ACTIVE"
    assert "hydros_cluster_id" not in payload
    assert "hydros_node_id" not in payload
    assert "agent_biz_status" not in payload
    assert "agent_instance_status" not in payload


def test_agent_instance_accepts_java_camel_case_names():
    context = make_context()

    agent = HydroAgentInstance.model_validate(
        {
            "agent_code": "TEST_AGENT",
            "agent_type": "TEST_AGENT",
            "agent_name": "Test Agent",
            "agent_configuration_url": "",
            "agent_id": "AGT_TEST",
            "biz_scene_instance_id": context.biz_scene_instance_id,
            "clusterId": "cluster-a",
            "nodeId": "node-a",
            "context": context.model_dump(mode="json"),
            "agentStatus": "IDLE",
            "drive_mode": "SIM_TICK_DRIVEN",
        }
    )

    assert agent.cluster_id == "cluster-a"
    assert agent.node_id == "node-a"
    assert agent.agent_status == AgentStatus.IDLE


def test_agent_instance_status_report_uses_java_status_field():
    context = make_context()
    agent = HydroAgentInstance(
        agent_code="TEST_AGENT",
        agent_type="TEST_AGENT",
        agent_name="Test Agent",
        agent_configuration_url="",
        agent_id="AGT_TEST",
        biz_scene_instance_id=context.biz_scene_instance_id,
        cluster_id="cluster-a",
        node_id="node-a",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )

    report = AgentInstanceStatusReport(
        command_id="CMD_STATUS",
        context=context,
        source_agent_instance=agent,
        created_state="RUNNING",
    )

    assert report.agent_instance_status == AgentInstanceStatus.RUNNING
    assert report.created_state == AgentInstanceStatus.RUNNING

    payload = report.model_dump(mode="json", by_alias=True)
    assert payload["agent_instance_status"] == "RUNNING"
    assert "created_state" not in payload
