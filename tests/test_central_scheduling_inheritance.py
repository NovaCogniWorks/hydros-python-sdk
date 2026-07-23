import unittest
from unittest.mock import Mock

from hydros_agent_sdk.agent_commands.target_value_builder import StationTargetValueCommandBuilder
from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.agents.mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from hydros_agent_sdk.agents.system_central_scheduling_agent import SystemCentralSchedulingAgent
from hydros_agent_sdk.mpc.control_command_builder import MpcControlCommandBuilder
from hydros_agent_sdk.protocol.commands import SimTaskTerminateRequest, TickCmdRequest
from hydros_agent_sdk.protocol.models import AgentStatus, CommandStatus, SimulationContext


class GenericCentralSchedulingAgentForTest(CentralSchedulingAgent):
    def on_init(self, request):
        return None

    def on_terminate(self, request):
        return None


class MpcCentralSchedulingAgentForTest(MpcCentralSchedulingAgent):
    def on_init(self, request):
        return None


class CentralSchedulingInheritanceTest(unittest.TestCase):
    def test_system_default_uses_explicit_mpc_base(self):
        self.assertTrue(issubclass(MpcCentralSchedulingAgent, CentralSchedulingAgent))
        self.assertTrue(issubclass(SystemCentralSchedulingAgent, MpcCentralSchedulingAgent))

    def test_generic_base_does_not_install_default_mpc_runtime(self):
        agent = GenericCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(transport=Mock()),
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
        self.assertFalse(hasattr(agent, "on_optimization"))
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
            sim_coordination_client=Mock(transport=Mock()),
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

    def test_generic_base_subscribes_field_metrics_topic_for_current_task(self):
        transport = Mock()
        agent = GenericCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(transport=transport),
            agent_id="agent-generic-metrics",
            agent_code="GENERIC_CENTRAL",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Generic Central",
            context=SimulationContext(biz_scene_instance_id="scene-generic-metrics"),
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )
        agent.properties["metrics_topic"] = "/hydros/data/edges/{hydros_cluster_id}"

        topic = agent.subscribe_field_metrics()

        self.assertEqual(topic, "/hydros/data/edges/cluster/scene-generic-metrics")
        transport.subscribe.assert_called_once_with(topic, agent._metrics_subscriber._handle_transport_payload)

    def test_mpc_base_owns_default_optimization_hook(self):
        agent = MpcCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(transport=Mock()),
            agent_id="agent-mpc-optimization",
            agent_code="MPC_CENTRAL",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="MPC Central",
            context=SimulationContext(biz_scene_instance_id="scene-mpc-optimization"),
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )

        self.assertTrue(hasattr(agent, "on_optimization"))

    def test_mpc_base_uses_mpc_control_command_builder_without_rebinding_dispatcher(self):
        agent = MpcCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(transport=Mock()),
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

    def test_mpc_base_termination_releases_task_scoped_runtime(self):
        context = SimulationContext(biz_scene_instance_id="scene-mpc-terminate")
        agent = MpcCentralSchedulingAgentForTest(
            sim_coordination_client=Mock(transport=Mock()),
            agent_id="agent-mpc-terminate",
            agent_code="MPC_CENTRAL",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="MPC Central",
            context=context,
            hydros_cluster_id="cluster",
            hydros_node_id="node",
        )
        agent._agent_command_gateway.shutdown = Mock()
        agent.discard_control_execution_waiters = Mock()
        agent._mpc_dispatch_tracker.discard_by_biz_scene_instance_id = Mock()
        agent._mpc_rolling_runtime.close = Mock()

        response = agent.on_terminate(
            SimTaskTerminateRequest(command_id="terminate-mpc", context=context)
        )

        agent._agent_command_gateway.shutdown.assert_called_once_with()
        agent.discard_control_execution_waiters.assert_called_once_with()
        discard_mpc_records = (
            agent._mpc_dispatch_tracker.discard_by_biz_scene_instance_id
        )
        discard_mpc_records.assert_called_once_with(context.biz_scene_instance_id)
        agent._mpc_rolling_runtime.close.assert_called_once_with()
        self.assertEqual(agent.agent_status, AgentStatus.TERMINATED)
        self.assertEqual(response.command_status, CommandStatus.SUCCEED)


if __name__ == "__main__":
    unittest.main()
