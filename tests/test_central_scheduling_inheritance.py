import unittest
from unittest.mock import Mock

from hydros_agent_sdk.agent_commands.target_value_builder import StationTargetValueCommandBuilder
from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.agents.mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from hydros_agent_sdk.agents.system_central_scheduling_agent import SystemCentralSchedulingAgent
from hydros_agent_sdk.mpc.control_command_builder import MpcControlCommandBuilder
from hydros_agent_sdk.protocol.commands import TickCmdRequest
from hydros_agent_sdk.protocol.models import SimulationContext


class GenericCentralSchedulingAgentForTest(CentralSchedulingAgent):
    def on_init(self, request):
        return None

    def on_terminate(self, request):
        return None


class MpcCentralSchedulingAgentForTest(MpcCentralSchedulingAgent):
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

    def test_generic_base_uses_default_control_command_builder(self):
        agent = GenericCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(mqtt_client=Mock()),
            agent_id="agent-generic-builder",
            agent_code="GENERIC_CENTRAL",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Generic Central",
            context=SimulationContext(biz_scene_instance_id="scene-generic-builder"),
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )

        self.assertIsInstance(agent._control_command_builder, StationTargetValueCommandBuilder)
        self.assertIs(
            agent._control_command_dispatcher.build_station_target_value_request.__self__,
            agent._control_command_builder,
        )

    def test_mpc_base_uses_mpc_control_command_builder_without_rebinding_dispatcher(self):
        agent = MpcCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(mqtt_client=Mock()),
            agent_id="agent-mpc-builder",
            agent_code="MPC_CENTRAL",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="MPC Central",
            context=SimulationContext(biz_scene_instance_id="scene-mpc-builder"),
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )

        self.assertIsInstance(agent._control_command_builder, MpcControlCommandBuilder)
        self.assertIs(
            agent._control_command_dispatcher.build_station_target_value_request.__self__,
            agent._control_command_builder,
        )


if __name__ == "__main__":
    unittest.main()
