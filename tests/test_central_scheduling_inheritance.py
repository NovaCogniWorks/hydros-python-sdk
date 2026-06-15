import unittest
from unittest.mock import Mock

from hydros_agent_sdk import MpcCentralSchedulingAgent
from hydros_agent_sdk.agents import CentralSchedulingAgent, SystemCentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import TickCmdRequest
from hydros_agent_sdk.protocol.models import SimulationContext


class GenericCentralSchedulingAgentForTest(CentralSchedulingAgent):
    def on_init(self, request):
        return None

    def on_terminate(self, request):
        return None


class CentralSchedulingInheritanceTest(unittest.TestCase):
    def test_system_default_uses_explicit_mpc_base(self):
        self.assertTrue(issubclass(MpcCentralSchedulingAgent, CentralSchedulingAgent))
        self.assertTrue(issubclass(SystemCentralSchedulingAgent, MpcCentralSchedulingAgent))

    def test_generic_base_does_not_install_default_mpc_runtime(self):
        agent = GenericCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(mqtt_client=Mock()),
            agent_id="agent-generic",
            agent_code="GENERIC_CENTRAL",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Generic Central",
            context=SimulationContext(biz_scene_instance_id="scene-generic"),
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )

        self.assertFalse(hasattr(agent, "_mpc_rolling_runtime"))
        self.assertFalse(hasattr(agent, "_mpc_optimization_service"))
        self.assertIsNone(
            agent.on_tick_simulation(
                TickCmdRequest(
                    command_id="tick-generic",
                    context=agent.context,
                    step=1,
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
