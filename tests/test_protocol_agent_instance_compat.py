from hydros_agent_sdk.protocol.commands import (
    AgentInstanceStatusReport,
    DeviceStatusChangeResponse,
    SimCommandEnvelope,
    SimTaskInitResponse,
)
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    AgentInstanceStatus,
    AgentStatus,
    CommandStatus,
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
        agent_instance_status=AgentInstanceStatus.RUNNING,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )

    assert agent.cluster_id == "cluster-a"
    assert agent.node_id == "node-a"
    assert agent.hydros_cluster_id == "cluster-a"
    assert agent.hydros_node_id == "node-a"
    assert agent.agent_status == AgentStatus.ACTIVE
    assert agent.agent_instance_status == AgentInstanceStatus.RUNNING

    payload = agent.model_dump(mode="json", by_alias=True)
    assert payload["cluster_id"] == "cluster-a"
    assert payload["node_id"] == "node-a"
    assert payload["agent_status"] == "ACTIVE"
    assert payload["agent_instance_status"] == "RUNNING"
    assert "hydros_cluster_id" not in payload
    assert "hydros_node_id" not in payload
    assert "agent_biz_status" not in payload


def test_agent_instance_accepts_java_camel_case_status_names():
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
            "agentInstanceStatus": "WAITING",
            "drive_mode": "SIM_TICK_DRIVEN",
        }
    )

    assert agent.cluster_id == "cluster-a"
    assert agent.node_id == "node-a"
    assert agent.agent_status == AgentStatus.IDLE
    assert agent.agent_instance_status == AgentInstanceStatus.WAITING


def test_agent_instance_status_report_uses_agent_instance_status_field():
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
        agent_instance_status=AgentInstanceStatus.RUNNING,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )

    report = AgentInstanceStatusReport(
        command_id="CMD_STATUS",
        context=context,
        source_agent_instance=agent,
        agent_instance_status=AgentInstanceStatus.RUNNING,
    )

    assert report.agent_instance_status == AgentInstanceStatus.RUNNING

    payload = report.model_dump(mode="json", by_alias=True)
    assert payload["agent_instance_status"] == "RUNNING"
    assert payload["source_agent_instance"]["agent_instance_status"] == "RUNNING"
    assert "created_state" not in payload
    assert "created_state" not in payload["source_agent_instance"]


def test_task_init_response_accepts_missing_managed_top_objects():
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
    payload = {
        "command_id": "CMD_INIT",
        "command_type": "task_init_response",
        "context": context.model_dump(mode="json"),
        "command_status": CommandStatus.SUCCEED.value,
        "source_agent_instance": agent.model_dump(mode="json", by_alias=True),
        "created_agent_instances": [agent.model_dump(mode="json", by_alias=True)],
    }

    envelope = SimCommandEnvelope(command=payload)

    assert isinstance(envelope.command, SimTaskInitResponse)
    assert envelope.command.managed_top_objects == {}


def test_device_status_change_response_envelope_matches_java_command_type():
    context = make_context()
    agent = HydroAgentInstance(
        agent_code="GATE_STATION_AGENT",
        agent_type="GATE_STATION_AGENT",
        agent_name="Gate Station Agent",
        agent_configuration_url="",
        agent_id="AGT_GATE_STATION",
        biz_scene_instance_id=context.biz_scene_instance_id,
        cluster_id="cluster-a",
        node_id="node-a",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        drive_mode=AgentDriveMode.PROACTIVE,
    )
    payload = {
        "command_id": "CMD_DEVICE_STATUS",
        "command_type": "device_status_change_response",
        "context": context.model_dump(mode="json"),
        "command_status": CommandStatus.SUCCEED.value,
        "source_agent_instance": agent.model_dump(mode="json", by_alias=True),
        "objectTimeSeries": [],
    }

    envelope = SimCommandEnvelope(command=payload)

    assert isinstance(envelope.command, DeviceStatusChangeResponse)
    assert envelope.command.command_id == "CMD_DEVICE_STATUS"
    assert envelope.command.object_time_series == []
