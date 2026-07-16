import unittest

from pydantic import ValidationError

from hydros_agent_sdk.protocol.commands import AgentInstanceStatusReport, TickCmdResponse
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    AgentInstanceStatus,
    AgentStatus,
    CommandStatus,
    HydroAgentInstance,
    SimulationContext,
)
from hydros_agent_sdk.runtime.agent_instance_status_support import AgentInstanceStatusSupport


def make_context():
    return SimulationContext(biz_scene_instance_id="TASK_STATUS_001")


def make_agent(context=None):
    context = context or make_context()
    return HydroAgentInstance(
        agent_code="CENTRAL_SCHEDULING_AGENT",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="中央调度智能体",
        agent_configuration_url="",
        agent_id="AGT_STATUS_001",
        biz_scene_instance_id=context.biz_scene_instance_id,
        cluster_id="cluster-a",
        node_id="node-a",
        context=context,
        agent_status=AgentStatus.INIT,
        agent_instance_status=AgentInstanceStatus.INIT,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )


class AgentInstanceStatusSupportTest(unittest.TestCase):
    def test_agent_instance_serializes_agent_instance_status(self):
        agent = make_agent()
        object.__setattr__(agent, "agent_status", AgentStatus.ACTIVE)
        object.__setattr__(agent, "agent_instance_status", AgentInstanceStatus.RUNNING)

        payload = agent.model_dump(mode="json", by_alias=True)

        self.assertEqual(payload["agent_status"], "ACTIVE")
        self.assertEqual(payload["agent_instance_status"], "RUNNING")

    def test_status_report_contains_top_level_and_source_instance_status(self):
        agent = make_agent()
        support = AgentInstanceStatusSupport()

        report = support.transition_status(
            agent,
            AgentInstanceStatus.RUNNING,
            phase="TICK_STARTED",
            metadata={"step": 1},
        )

        payload = report.model_dump(mode="json", by_alias=True)
        self.assertEqual(payload["command_type"], "report_agent_instance_status")
        self.assertEqual(payload["agent_instance_status"], "RUNNING")
        self.assertEqual(payload["source_agent_instance"]["agent_status"], "ACTIVE")
        self.assertEqual(payload["source_agent_instance"]["agent_instance_status"], "RUNNING")
        self.assertEqual(payload["init_result"]["phase"], "TICK_STARTED")
        self.assertEqual(payload["init_result"]["step"], 1)
        self.assertNotIn("created_state", payload)
        self.assertNotIn("created_state", payload["source_agent_instance"])

    def test_execute_with_status_success_reports_running_then_waiting(self):
        submitted = []
        context = make_context()
        agent = make_agent(context)
        support = AgentInstanceStatusSupport(report_sink=submitted.append)

        response = TickCmdResponse(
            command_id="CMD_TICK",
            context=context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=agent,
            completed_step=1,
        )

        result = support.execute_with_status(
            agent,
            lambda: response,
            phase="TICK",
            metadata={"step": 1},
        )

        self.assertIs(result, response)
        self.assertEqual(
            [item.agent_instance_status for item in submitted],
            [AgentInstanceStatus.RUNNING, AgentInstanceStatus.WAITING],
        )
        self.assertEqual(agent.agent_status, AgentStatus.ACTIVE)
        self.assertEqual(agent.agent_instance_status, AgentInstanceStatus.WAITING)

    def test_execute_with_status_failed_response_reports_failed(self):
        submitted = []
        context = make_context()
        agent = make_agent(context)
        support = AgentInstanceStatusSupport(report_sink=submitted.append)

        response = TickCmdResponse(
            command_id="CMD_TICK",
            context=context,
            command_status=CommandStatus.FAILED,
            source_agent_instance=agent,
            completed_step=1,
        )

        support.execute_with_status(
            agent,
            lambda: response,
            phase="TICK",
        )

        self.assertEqual(
            [item.agent_instance_status for item in submitted],
            [AgentInstanceStatus.RUNNING, AgentInstanceStatus.FAILED],
        )
        self.assertEqual(agent.agent_status, AgentStatus.FAILED)
        self.assertEqual(agent.agent_instance_status, AgentInstanceStatus.FAILED)

    def test_execute_with_status_exception_reports_failed_and_reraises(self):
        submitted = []
        agent = make_agent()
        support = AgentInstanceStatusSupport(report_sink=submitted.append)

        def fail():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            support.execute_with_status(agent, fail, phase="TICK")

        self.assertEqual(
            [item.agent_instance_status for item in submitted],
            [AgentInstanceStatus.RUNNING, AgentInstanceStatus.FAILED],
        )

    def test_transition_status_skips_same_status(self):
        submitted = []
        agent = make_agent()
        support = AgentInstanceStatusSupport(report_sink=submitted.append)

        support.transition_status(agent, AgentInstanceStatus.RUNNING, phase="A")
        support.transition_status(agent, AgentInstanceStatus.RUNNING, phase="B")

        self.assertEqual(len(submitted), 1)

    def test_status_report_no_longer_accepts_created_state(self):
        context = make_context()
        agent = make_agent(context)

        with self.assertRaises(ValidationError):
            AgentInstanceStatusReport(
                command_id="CMD_STATUS",
                context=context,
                source_agent_instance=agent,
                created_state="RUNNING",
            )


if __name__ == "__main__":
    unittest.main()
