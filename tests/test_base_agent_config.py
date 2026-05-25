import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskTerminateRequest,
    TickCmdRequest,
)
from hydros_agent_sdk.protocol.models import HydroAgent, SimulationContext


class DummyAgent(BaseHydroAgent):
    def on_init(self, request: SimTaskInitRequest):
        return None

    def on_tick(self, request: TickCmdRequest):
        return None

    def on_terminate(self, request: SimTaskTerminateRequest):
        return None


class BaseAgentConfigurationTest(unittest.TestCase):
    def build_agent(self):
        context = SimulationContext(biz_scene_instance_id="scene-001")
        sim_client = SimpleNamespace(state_manager=SimpleNamespace())
        return DummyAgent(
            sim_coordination_client=sim_client,
            agent_id="agent-001",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Pump Scheduling Agent",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

    def build_request(self, agent):
        return SimTaskInitRequest(
            command_id="init-001",
            context=agent.context,
            agent_list=[
                HydroAgent(
                    agent_code=agent.agent_code,
                    agent_type=agent.agent_type,
                    agent_name=agent.agent_name,
                    agent_configuration_url="https://example.test/agent_config.yaml",
                )
            ],
        )

    def build_config(self, agent_code):
        return AgentConfigLoader.from_dict(
            {
                "agent_code": agent_code,
                "agent_type": "CENTRAL_SCHEDULING_AGENT",
                "agent_name": "Central Scheduling Agent",
                "properties": {
                    "driven_by_coordinator": True,
                    "hydro_environment_type": "test",
                },
            }
        )

    def test_load_agent_configuration_accepts_exact_agent_code(self):
        agent = self.build_agent()
        request = self.build_request(agent)

        with patch(
            "hydros_agent_sdk.agent_config.AgentConfigLoader.from_url",
            return_value=self.build_config("CENTRAL_SCHEDULING_AGENT_PUMP"),
        ):
            agent.load_agent_configuration(request)

        self.assertTrue(agent.properties.get_property("driven_by_coordinator"))
        self.assertEqual(agent.properties.get_property("hydro_environment_type"), "test")

    def test_load_agent_configuration_accepts_agent_type_code(self):
        agent = self.build_agent()
        request = self.build_request(agent)

        with patch(
            "hydros_agent_sdk.agent_config.AgentConfigLoader.from_url",
            return_value=self.build_config("CENTRAL_SCHEDULING_AGENT"),
        ):
            agent.load_agent_configuration(request)

        self.assertTrue(agent.properties.get_property("driven_by_coordinator"))
        self.assertEqual(
            agent.agent_configuration_url,
            "https://example.test/agent_config.yaml",
        )

    def test_load_agent_configuration_rejects_unrelated_agent_code(self):
        agent = self.build_agent()
        request = self.build_request(agent)

        with patch(
            "hydros_agent_sdk.agent_config.AgentConfigLoader.from_url",
            return_value=self.build_config("TWINS_SIMULATION_AGENT"),
        ):
            with self.assertRaisesRegex(ValueError, "Agent code mismatch"):
                agent.load_agent_configuration(request)

    def test_system_default_central_agent_can_load_single_custom_central_config(self):
        context = SimulationContext(biz_scene_instance_id="scene-002")
        sim_client = SimpleNamespace(state_manager=SimpleNamespace())
        agent = DummyAgent(
            sim_coordination_client=sim_client,
            agent_id="agent-002",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="System Central Scheduling Agent",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        request = SimTaskInitRequest(
            command_id="init-002",
            context=context,
            agent_list=[
                HydroAgent(
                    agent_code="CENTRAL_SCHEDULING_AGENT_POWER01",
                    agent_type="CENTRAL_SCHEDULING_AGENT",
                    agent_name="Power Scheduling Agent",
                    agent_configuration_url="https://example.test/power_config.yaml",
                )
            ],
        )

        with patch(
            "hydros_agent_sdk.agent_config.AgentConfigLoader.from_url",
            return_value=self.build_config("CENTRAL_SCHEDULING_AGENT_POWER01"),
        ):
            agent.load_agent_configuration(request)

        self.assertTrue(agent.properties.get_property("driven_by_coordinator"))
        self.assertEqual(
            agent.agent_configuration_url,
            "https://example.test/power_config.yaml",
        )


if __name__ == '__main__':
    unittest.main()
