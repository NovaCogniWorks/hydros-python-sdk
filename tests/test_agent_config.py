import unittest
import os
import sys

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


if __name__ == '__main__':
    unittest.main()
