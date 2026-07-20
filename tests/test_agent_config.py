import unittest
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

from hydros_agent_sdk.agent_config import AgentConfigLoader


class TestAgentConfigLoader(unittest.TestCase):
    def test_release_at_accepts_yaml_timestamp(self):
        config = AgentConfigLoader.from_yaml_string(
            """
agent_code: CENTRAL_SCHEDULING_AGENT
agent_type: CENTRAL_SCHEDULING_AGENT
agent_name: Central Scheduling Agent
release_at: 2026-03-01 12:34:56+08:00
properties:
  driven_by_coordinator: true
"""
        )

        self.assertEqual(config.release_at, "2026-03-01 12:34:56+08:00")

    def test_release_at_keeps_string_value(self):
        config = AgentConfigLoader.from_yaml_string(
            """
agent_code: CENTRAL_SCHEDULING_AGENT
agent_type: CENTRAL_SCHEDULING_AGENT
agent_name: Central Scheduling Agent
release_at: "2026-03-01 12:34:56+08:00"
properties:
  driven_by_coordinator: true
"""
        )

        self.assertEqual(config.release_at, "2026-03-01 12:34:56+08:00")

    def test_from_url_normalizes_legacy_public_s3_host(self):
        response = MagicMock()
        response.read.return_value = b"""
agent_code: CENTRAL_SCHEDULING_AGENT
agent_type: CENTRAL_SCHEDULING_AGENT
agent_name: Central Scheduling Agent
properties:
  driven_by_coordinator: true
"""
        response.__enter__.return_value = response
        response.__exit__.return_value = False

        with patch("hydros_agent_sdk.agent_config.urlopen", return_value=response) as mocked_urlopen:
            config = AgentConfigLoader.from_url(
                "https://hydroos.cn/s3/hydros-mdm/waternetworks/test/agents/CENTRAL_SCHEDULING_AGENT/agent_config.yaml"
            )

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://s3.hydroos.pub/hydros-mdm/waternetworks/test/agents/CENTRAL_SCHEDULING_AGENT/agent_config.yaml",
        )
        self.assertEqual(config.agent_code, "CENTRAL_SCHEDULING_AGENT")


if __name__ == '__main__':
    unittest.main()
