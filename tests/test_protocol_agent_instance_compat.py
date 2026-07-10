import unittest

from pydantic import ValidationError

from hydros_agent_sdk.protocol.commands import (
    AgentInstanceStatusReport,
    DeviceStatusChangeResponse,
    EdgeControlExecutionReport,
    EdgeControlResultReport,
    MpcExecutionStatusReport,
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


def make_agent(context, agent_code="TEST_AGENT"):
    return HydroAgentInstance(
        agent_code=agent_code,
        agent_type=agent_code,
        agent_name="Test Agent",
        agent_configuration_url="",
        agent_id=f"AGT_{agent_code}",
        biz_scene_instance_id=context.biz_scene_instance_id,
        cluster_id="cluster-a",
        node_id="node-a",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        agent_instance_status=AgentInstanceStatus.WAITING,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )


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


class CoordinationReportContractTest(unittest.TestCase):
    def test_edge_control_result_report_envelope_matches_java_command_type(self):
        context = make_context()
        agent = make_agent(context, agent_code="GATE_STATION_AGENT")
        payload = {
            "command_id": "CMD_EDGE_CONTROL_RESULT_REPORT",
            "command_type": "edge_control_result_report",
            "context": context.model_dump(mode="json"),
            "broadcast": True,
            "source_agent_instance": agent.model_dump(mode="json", by_alias=True),
            "report": {
                "status": "SUCCEED",
                "message": "ok",
                "control_group_id": "control-group-001",
                "main_step_index": 12,
            },
            "details": [{"object_id": 1001, "target_value": 1.25}],
        }

        envelope = SimCommandEnvelope(command=payload)

        self.assertIsInstance(envelope.command, EdgeControlResultReport)
        self.assertEqual(envelope.command.command_id, "CMD_EDGE_CONTROL_RESULT_REPORT")
        self.assertEqual(envelope.command.report["status"], "SUCCEED")
        self.assertEqual(envelope.command.report["control_group_id"], "control-group-001")
        self.assertEqual(envelope.command.report["main_step_index"], 12)
        self.assertEqual(envelope.command.details[0]["object_id"], 1001)

    def test_pid_control_execution_report_discriminator_is_not_supported(self):
        context = make_context()
        agent = make_agent(context, agent_code="GATE_STATION_AGENT")
        payload = {
            "command_id": "CMD_OLD_REPORT",
            "command_type": "pid_control_execution_report",
            "context": context.model_dump(mode="json"),
            "broadcast": True,
            "source_agent_instance": agent.model_dump(mode="json", by_alias=True),
            "run_result": {},
            "actuator_results": [],
        }

        with self.assertRaises(ValidationError):
            SimCommandEnvelope(command=payload)

    def test_edge_control_execution_report_envelope_matches_java_command_type(self):
        context = make_context()
        source_agent = make_agent(context, agent_code="GATE_STATION_AGENT")
        target_agent = make_agent(context, agent_code="CENTRAL_SCHEDULING_AGENT")
        payload = {
            "command_id": "CMD_EDGE_REPORT",
            "command_type": "edge_control_execution_report",
            "context": context.model_dump(mode="json"),
            "broadcast": True,
            "source_agent_instance": source_agent.model_dump(mode="json", by_alias=True),
            "target_agent_instance": target_agent.model_dump(mode="json", by_alias=True),
            "exec_command_id": "CMD_EXEC",
            "control_run_id": "RUN_001",
            "object_type": "GATE",
            "object_id": 1001,
            "target_value_type": "GATE_OPENING",
            "target_value": 1.5,
            "exec_status": "COMPLETED",
            "error_code": None,
            "error_message": None,
            "started_time": "2026-06-23T15:58:00+08:00",
            "finished_time": "2026-06-23T15:58:01+08:00",
            "group_id": "control-group-001",
            "session_id": "hydraulic-session-001",
            "sub_step_index": 6,
        }

        envelope = SimCommandEnvelope(command=payload)

        self.assertIsInstance(envelope.command, EdgeControlExecutionReport)
        self.assertEqual(envelope.command.exec_command_id, "CMD_EXEC")
        self.assertEqual(envelope.command.control_run_id, "RUN_001")
        self.assertEqual(envelope.command.target_agent_instance.agent_code, "CENTRAL_SCHEDULING_AGENT")
        self.assertEqual(envelope.command.exec_status, "COMPLETED")
        self.assertEqual(envelope.command.group_id, "control-group-001")
        self.assertEqual(envelope.command.session_id, "hydraulic-session-001")
        self.assertEqual(envelope.command.sub_step_index, 6)
        serialized = envelope.command.model_dump(mode="json", by_alias=True)
        self.assertEqual(serialized["control_run_id"], "RUN_001")
        self.assertNotIn("exec_run_id", serialized)

        unsupported_payload = dict(payload)
        unsupported_payload.pop("control_run_id")
        unsupported_payload["exec_run_id"] = "UNSUPPORTED_RUN_001"
        unsupported_envelope = SimCommandEnvelope(command=unsupported_payload)
        self.assertIsNone(unsupported_envelope.command.control_run_id)

    def test_mpc_execution_status_report_envelope_matches_java_command_type(self):
        context = make_context()
        agent = make_agent(context, agent_code="CENTRAL_SCHEDULING_AGENT")
        payload = {
            "command_id": "CMD_MPC_STATUS",
            "command_type": "mpc_execution_status_report",
            "context": context.model_dump(mode="json"),
            "broadcast": True,
            "source_agent_instance": agent.model_dump(mode="json", by_alias=True),
            "optimize_step": 1,
            "horizon_step": 2,
            "biz_idem_key": "idem-1",
            "node_id": 10,
            "object_id": 1001,
            "object_type": "GATE",
            "target_value_type": "GATE_OPENING",
            "target_value": 1.5,
            "execution_command_id": "CMD_EXEC",
            "dispatch_key": "dispatch-1",
            "execution_status": "DISPATCHED",
            "execution_error_code": None,
            "execution_error_message": None,
            "dispatched_at": "2026-06-23T15:58:00+08:00",
            "executed_at": None,
        }

        envelope = SimCommandEnvelope(command=payload)

        self.assertIsInstance(envelope.command, MpcExecutionStatusReport)
        self.assertEqual(envelope.command.execution_command_id, "CMD_EXEC")
        self.assertEqual(envelope.command.dispatch_key, "dispatch-1")
        self.assertEqual(envelope.command.execution_status, "DISPATCHED")
