import unittest
from types import SimpleNamespace

from hydros_agent_sdk.agent_commands.persistence import AgentCommandLogEntry
from hydros_agent_sdk.agent_commands.runtime import HydroCommandLogReportScheduler
from hydros_agent_sdk.dto_model import CommandLogDTO
from hydros_agent_sdk.protocol.models import CommandStatus
from hydros_agent_sdk.protocol.system_commands import HydroCommandLogReportRequest


class FakeLogOps:
    def __init__(self):
        self.reported_entries = []

    def mark_reported(self, entries):
        self.reported_entries.extend(entries)


class FakeRuntime:
    def __init__(self, entries, node_id="node-a"):
        self._entries = list(entries)
        self.state_manager = SimpleNamespace(get_node_id=lambda: node_id)
        self.log_ops = FakeLogOps()

    def find_unreported_command_logs(self, limit: int = 100):
        return self._entries[:limit]


class HydroCommandLogReportSchedulerTest(unittest.TestCase):
    def test_build_request_uses_current_node_and_logs(self):
        entry = AgentCommandLogEntry(
            command_id="cmd-001",
            source_id="node-a",
            biz_scenario_id="biz-001",
            biz_scene_instance_id="scene-001",
            command_type="direct_gate_opening_request",
            command_request="{}",
            command_status=CommandStatus.INIT,
        )
        runtime = FakeRuntime([entry], node_id="node-a")
        submitted = []
        scheduler = HydroCommandLogReportScheduler(
            runtime=runtime,
            submit_command=submitted.append,
            interval_seconds=0.01,
        )

        request = scheduler.build_request([entry])

        self.assertIsInstance(request, HydroCommandLogReportRequest)
        self.assertEqual(request.source_id, "node-a")
        self.assertEqual(request.target_id, "default_data")
        self.assertFalse(request.need_ack_reply)
        self.assertEqual(len(request.agent_logs), 1)
        self.assertIsInstance(request.agent_logs[0], CommandLogDTO)
        self.assertEqual(request.agent_logs[0].command_id, "cmd-001")

        sync_request = scheduler.do_sync()
        self.assertIs(sync_request, submitted[0])
        self.assertEqual(len(runtime.log_ops.reported_entries), 1)
        self.assertEqual(runtime.log_ops.reported_entries[0].command_id, "cmd-001")

    def test_do_sync_returns_none_when_no_logs(self):
        runtime = FakeRuntime([], node_id="node-a")
        submitted = []
        scheduler = HydroCommandLogReportScheduler(
            runtime=runtime,
            submit_command=submitted.append,
            interval_seconds=0.01,
        )

        request = scheduler.do_sync()

        self.assertIsNone(request)
        self.assertEqual(submitted, [])
        self.assertEqual(runtime.log_ops.reported_entries, [])


if __name__ == "__main__":
    unittest.main()
