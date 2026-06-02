import os
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

sys.path.insert(0, os.path.abspath('custom-agent/pump/scheduling'))
try:
    from pump_scheduling_agent import PumpCentralSchedulingAgent
except ModuleNotFoundError as exc:
    PumpCentralSchedulingAgent = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class MockContext:
    def __init__(self):
        self.biz_scene_instance_id = "test_scene"


class MockClient:
    def __init__(self):
        self.state_manager = self
        self.mqtt_client = Mock()


class PumpSchedulingPathTest(unittest.TestCase):
    @unittest.skipIf(PumpCentralSchedulingAgent is None, f"pump scheduling dependencies unavailable: {IMPORT_ERROR}")
    def build_agent(self):
        return PumpCentralSchedulingAgent(
            sim_coordination_client=MockClient(),
            agent_id="agent1",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Pump Scheduling Agent",
            context=MockContext(),
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )

    def test_resolve_config_path_does_not_depend_on_cwd(self):
        agent = self.build_agent()
        original_cwd = os.getcwd()

        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                config_path = agent._resolve_config_path()
            finally:
                os.chdir(original_cwd)

        self.assertTrue(config_path.endswith(os.path.join("data", "config_xhh.yaml")))
        self.assertTrue(os.path.exists(config_path))


if __name__ == '__main__':
    unittest.main()
