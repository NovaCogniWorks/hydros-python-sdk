import unittest
from queue import Empty, Queue
from unittest.mock import Mock

from hydros_agent_sdk.agents.mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.multi_agent import MultiAgentCallback
from hydros_agent_sdk.protocol.commands import (
    HydroEventAckResponse,
    HydroEventCommand,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.events import (
    OutflowTimeSeriesDataChangedEvent,
    TimeSeriesDataChangedEvent,
)
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    AgentStatus,
    CommandStatus,
    ObjectTimeSeries,
    SimulationContext,
    TimeSeriesValue,
)
from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.scenario_config import BizScenarioConfiguration, SimAgentProperties
from hydros_agent_sdk.state_manager import AgentStateManager


class CentralSchedulingEventAgent(MpcCentralSchedulingAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.optimization_steps = []

    def on_init(self, request):
        object.__setattr__(self, "agent_status", AgentStatus.ACTIVE)
        return ResponseFactory.init_succeed(self, request)

    def on_terminate(self, request):
        object.__setattr__(self, "agent_status", AgentStatus.TERMINATED)
        return ResponseFactory.terminate_succeed(self, request)

    def on_optimization(self, step: int):
        self.optimization_steps.append(step)
        return None


class CentralSchedulingEventInjectionTest(unittest.TestCase):
    def setUp(self):
        ContextManager.clear()

    def tearDown(self):
        ContextManager.clear()

    def test_hydro_event_time_series_injection_activates_central_mpc_and_returns_ack(self):
        context = SimulationContext(biz_scene_instance_id="scene-event-inject-success")
        client, agent, outbound = self._build_registered_central_agent(
            context, with_rolling_config=True
        )
        event = self._build_time_series_event(auto_schedule_at_step=5)

        client._task_runtime_registry.get_or_create(context.biz_scene_instance_id).handle(
            HydroEventCommand(
                command_id="event-ts-001",
                context=context,
                broadcast=True,
                payload=event,
            )
        )

        ack = self._single_response_of_type(outbound, HydroEventAckResponse)
        self.assertEqual(ack.command_id, "event-ts-001")
        self.assertEqual(ack.command_status, CommandStatus.SUCCEED)
        self.assertEqual(ack.source_agent_instance.agent_code, "CENTRAL_SCHEDULING_AGENT")
        self.assertEqual(agent.optimization_steps, [5])
        runtime = agent._mpc_rolling_runtime
        self.assertTrue(runtime.is_mpc_optimizing_on_the_loop())
        self.assertEqual(runtime.task_state.current_step, 5)
        self.assertEqual(runtime.task_state.hydro_events, [event])

    def test_hydro_event_time_series_injection_returns_failed_ack_when_rolling_config_missing(self):
        context = SimulationContext(biz_scene_instance_id="scene-event-inject-missing-config")
        client, agent, outbound = self._build_registered_central_agent(
            context, with_rolling_config=False
        )

        with self.assertLogs(
            "hydros_agent_sdk.agents.mpc_central_scheduling_agent",
            level="ERROR",
        ) as logs:
            client._task_runtime_registry.get_or_create(context.biz_scene_instance_id).handle(
                HydroEventCommand(
                    command_id="event-ts-missing-config",
                    context=context,
                    broadcast=True,
                    payload=self._build_time_series_event(auto_schedule_at_step=5),
                )
            )

        ack = self._single_response_of_type(outbound, HydroEventAckResponse)
        self.assertEqual(ack.command_id, "event-ts-missing-config")
        self.assertEqual(ack.command_status, CommandStatus.FAILED)
        self.assertTrue(
            any("Missing integer property: roll_steps" in message for message in logs.output)
        )
        self.assertIsNone(agent._mpc_rolling_runtime.task_state)
        self.assertEqual(agent.optimization_steps, [])

    def test_direct_time_series_update_request_reaches_central_agent_through_multi_agent_callback(self):
        context = SimulationContext(biz_scene_instance_id="scene-direct-update")
        client, agent, outbound = self._build_registered_central_agent(
            context, with_rolling_config=True
        )
        event = self._build_time_series_event(auto_schedule_at_step=7)

        client._task_runtime_registry.get_or_create(context.biz_scene_instance_id).handle(
            TimeSeriesDataUpdateRequest(
                command_id="direct-ts-001",
                context=context,
                broadcast=False,
                time_series_data_changed_event=event,
            )
        )

        response = self._single_response_of_type(outbound, TimeSeriesDataUpdateResponse)
        self.assertEqual(response.command_id, "direct-ts-001")
        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        self.assertEqual(agent.optimization_steps, [7])
        self.assertEqual(agent._mpc_rolling_runtime.task_state.hydro_events, [event])

    def test_outflow_data_event_injection_keeps_default_central_noop_ack_without_mpc_activation(self):
        context = SimulationContext(biz_scene_instance_id="scene-outflow-noop")
        client, agent, outbound = self._build_registered_central_agent(
            context, with_rolling_config=True
        )

        client._task_runtime_registry.get_or_create(context.biz_scene_instance_id).handle(
            HydroEventCommand(
                command_id="event-outflow-data-001",
                context=context,
                broadcast=True,
                payload=OutflowTimeSeriesDataChangedEvent(
                    hydro_event_source_type="OUTFLOW_PLAN",
                    auto_schedule_at_step=9,
                    source_agent_code="OUTFLOW_PLAN_AGENT",
                    object_type="GateStation",
                    object_time_series=[
                        ObjectTimeSeries(
                            object_id=2001,
                            object_name="gate-station-2001",
                            object_type="GateStation",
                            metrics_code="planned_outflow",
                            time_series=[TimeSeriesValue(step=9, value=120.0)],
                        )
                    ],
                ),
            )
        )

        ack = self._single_response_of_type(outbound, HydroEventAckResponse)
        self.assertEqual(ack.command_id, "event-outflow-data-001")
        self.assertEqual(ack.command_status, CommandStatus.SUCCEED)
        self.assertIsNone(agent._mpc_rolling_runtime.task_state)
        self.assertEqual(agent.optimization_steps, [])

    def _build_registered_central_agent(self, context, with_rolling_config):
        state_manager = AgentStateManager()
        state_manager.set_cluster_id("demo-cluster")
        state_manager.set_node_id("node-a")
        callback = MultiAgentCallback()
        client = SimCoordinationClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
            sim_coordination_callback=callback,
            state_manager=state_manager,
        )
        callback.set_client(client)
        outbound = Queue()
        client._task_runtime_registry.outbound_submitter = outbound.put

        if with_rolling_config:
            ContextManager.create(
                context=context,
                scenario_config=BizScenarioConfiguration(
                    sim_agent_properties=SimAgentProperties(
                        roll_steps=3,
                        total_steps=20,
                        output_step_size=7200,
                    )
                ),
            )

        agent = CentralSchedulingEventAgent(
            sim_coordination_client=client,
            agent_id="agent-central-event",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Central Scheduling Agent",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            agent_status=AgentStatus.ACTIVE,
            drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
        )
        agent._metrics_subscriber.transport = Mock()
        state_manager.activate_task(context, [agent])
        return client, agent, outbound

    @staticmethod
    def _build_time_series_event(auto_schedule_at_step):
        return TimeSeriesDataChangedEvent(
            hydro_event_source_type="WEATHER_FORECAST",
            auto_schedule_at_step=auto_schedule_at_step,
            object_time_series=[
                ObjectTimeSeries(
                    object_id=1001,
                    object_name="node-1001",
                    metrics_code="water_flow",
                    time_series=[
                        TimeSeriesValue(step=auto_schedule_at_step, value=12.0),
                    ],
                )
            ],
        )

    @staticmethod
    def _single_response_of_type(outbound, response_type):
        matches = []
        while True:
            try:
                item = outbound.get_nowait()
            except Empty:
                break
            if isinstance(item, response_type):
                matches.append(item)
        if len(matches) != 1:
            raise AssertionError(
                f"Expected exactly one {response_type.__name__}, got {len(matches)}"
            )
        return matches[0]


if __name__ == "__main__":
    unittest.main()
