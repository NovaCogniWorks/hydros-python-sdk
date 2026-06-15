import json
import os
import tempfile
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from hydros_agent_sdk import HydroObjectType, generate_agent_command_id, get_default_env_config_path, load_env_config
from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.agent_commands import (
    AgentCommandClient,
    AgentCommandEnvelope,
    AgentCommandHandler,
    AgentCommandRuntime,
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.agent_commands.models import DeviceValueTypeEnum
from hydros_agent_sdk.agents.mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from hydros_agent_sdk.context_manager import ContextManager, HydroModelContextRepository
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.mpc.client import MpcPlanningClient, MpcPlanningError
from hydros_agent_sdk.mpc.config import MpcConfigResolver
from hydros_agent_sdk.mpc.control_command_builder import MpcControlCommandBuilder
from hydros_agent_sdk.mpc.models import (
    ControlObjectResult,
    HorizonStep,
    MpcOptimizeResponse,
    PredictedResult,
)
from hydros_agent_sdk.mpc.mpc_result_reporter import MpcResultReporter
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.protocol.commands import (
    MpcResultReport,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    AgentDriveMode,
    BizScenario,
    HydroAgent,
    CommandStatus,
    HydroAgentInstance,
    ObjectTimeSeries,
    SimulationContext,
    Tenant,
    TimeSeriesValue,
    TopHydroObject,
    Waterway,
)
from hydros_agent_sdk.runtime import RuntimeEnvSettings
from hydros_agent_sdk.scenario_config import BizScenarioConfiguration, SimAgentProperties
from hydros_agent_sdk.sensor_data import SensorData
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.utils import (
    SimpleChildObject,
    TopHydroObject as TopologyTopHydroObject,
    WaterwayTopology,
)


def build_agent_instance(agent_id: str, agent_code: str, node_id: str, context: SimulationContext) -> HydroAgentInstance:
    return HydroAgentInstance(
        agent_id=agent_id,
        agent_code=agent_code,
        agent_type=agent_code,
        agent_name=agent_code,
        agent_configuration_url="",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="demo-cluster",
        hydros_node_id=node_id,
        context=context,
        agent_status=AgentStatus.INIT,
        drive_mode=AgentDriveMode.PROACTIVE,
    )


class StationTargetValueHandler(AgentCommandHandler[HydroStationTargetValueRequest, HydroStationTargetValueResponse]):
    def get_command(self) -> str:
        return "update_station_target_value_request"

    @property
    def response_type(self):
        return HydroStationTargetValueResponse

    def execute(self, request: HydroStationTargetValueRequest) -> HydroStationTargetValueResponse:
        return HydroStationTargetValueResponse.from_request(
            request,
            command_status=CommandStatus.SUCCEED,
            success=True,
            target_value_type=request.target_value_type,
            target_value=request.target_value,
        )


class CentralSchedulingAgentForTest(MpcCentralSchedulingAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.optimization_steps = []
        self.optimization_result = None

    def load_agent_configuration(self, request):
        # 测试里不走外部配置，直接给一个空 properties 就够了。
        return None

    def on_init(self, request: SimTaskInitRequest):
        self._agent_command_gateway.start()
        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False,
        )

    def on_optimization(self, step: int):
        self.optimization_steps.append(step)
        return self.optimization_result

    def on_terminate(self, request: SimTaskTerminateRequest):
        self._agent_command_gateway.shutdown()
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )


class ProductionCentralSchedulingAgentForTest(MpcCentralSchedulingAgent):
    def load_agent_configuration(self, request):
        return None

    def on_init(self, request: SimTaskInitRequest):
        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False,
        )

    def on_terminate(self, request: SimTaskTerminateRequest):
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )


class FakeMpcPlanningClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def execute_optimization(self, mpc_task_state, sensor_data, sensor_provider=None):
        self.calls.append(
            {
                "state": mpc_task_state,
                "sensor_data": list(sensor_data),
                "sensor_provider": sensor_provider,
            }
        )
        return self.responses


class FakeMpcResultReporter:
    def __init__(self):
        self.published = []

    def publish(self, source_agent_instance, mpc_task_state, responses):
        self.published.append(
            {
                "source": source_agent_instance,
                "state": mpc_task_state,
                "responses": list(responses),
            }
        )
        return None


class TestSiblingCacheCallback(SimCoordinationCallback):
    def get_component(self) -> str:
        return "TEST_CALLBACK"

    def on_sim_task_init(self, request: SimTaskInitRequest):
        return None

    def on_tick(self, request):
        return None

    def is_remote_agent(self, agent_instance) -> bool:
        return True


def build_time_series_update_request(
    context: SimulationContext,
    command_id: str = "ts-update-001",
    auto_schedule_at_step: int = 1,
) -> TimeSeriesDataUpdateRequest:
    return TimeSeriesDataUpdateRequest(
        command_id=command_id,
        context=context,
        time_series_data_changed_event=TimeSeriesDataChangedEvent(
            auto_schedule_at_step=auto_schedule_at_step,
            hydro_event_source_type="WEATHER_FORECAST",
            object_time_series=[
                ObjectTimeSeries(
                    object_id=1001,
                    object_name="node-1001",
                    metrics_code="water_flow",
                    time_series=[
                        TimeSeriesValue(step=auto_schedule_at_step, value=12.0),
                        TimeSeriesValue(step=auto_schedule_at_step + 3, value=15.0),
                    ],
                )
            ],
        ),
    )


def register_sim_agent_properties(
    context: SimulationContext,
    roll_steps: int = 3,
    total_steps: int = 20,
    output_step_size: int | None = 7200,
    topology: WaterwayTopology | None = None,
) -> None:
    ContextManager.create(
        context=context,
        topology=topology,
        scenario_config=BizScenarioConfiguration(
            sim_agent_properties=SimAgentProperties(
                roll_steps=roll_steps,
                total_steps=total_steps,
                output_step_size=output_step_size,
            )
        ),
    )


class AgentCommandsRefactorTest(unittest.TestCase):
    def setUp(self):
        ContextManager.clear()
        self._temp_dir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._temp_dir.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._temp_dir.cleanup()
        ContextManager.clear()

    def test_agent_command_envelope_uses_registry_parser(self):
        context = SimulationContext(biz_scene_instance_id="scene-001")
        source = build_agent_instance("source-001", "SOURCE_AGENT", "node-a", context)
        target = build_agent_instance("target-001", "TARGET_AGENT", "node-b", context)

        envelope = AgentCommandEnvelope(
            command={
                "command_id": "cmd-001",
                "command_type": "update_station_target_value_request",
                "source": source.model_dump(mode="json"),
                "target": target.model_dump(mode="json"),
                "object_id": 501,
                "object_type": "Gate",
                "target_value_type": "gate_opening",
                "target_value": 0.75,
            }
        )

        self.assertIsInstance(envelope.command, HydroStationTargetValueRequest)
        self.assertEqual(envelope.command.command_id, "cmd-001")
        self.assertAlmostEqual(envelope.command.target_value, 0.75)

    def test_context_repository_keeps_instance_state_isolated(self):
        context = SimulationContext(biz_scene_instance_id="scene-repository")
        repository_a = HydroModelContextRepository()
        repository_b = HydroModelContextRepository()

        model_context = repository_a.create(context=context)

        self.assertIs(repository_a.get_context(context), model_context)
        self.assertIsNone(repository_b.get_context(context))

    def test_context_manager_delegates_to_injected_repository(self):
        original_repository = ContextManager.repository()
        injected_repository = HydroModelContextRepository()
        context = SimulationContext(biz_scene_instance_id="scene-injected-repository")
        try:
            ContextManager.set_repository(injected_repository)
            model_context = ContextManager.create(context=context)

            self.assertIs(injected_repository.get_context(context), model_context)
            self.assertIs(ContextManager.get_context(context), model_context)
            self.assertIsNone(original_repository.get_context(context))
        finally:
            ContextManager.set_repository(original_repository)

    def test_scenario_config_parses_sim_agent_properties(self):
        config = BizScenarioConfiguration.model_validate(
            {
                "hydros_objects_modeling_url": "https://example.test/objects.yaml",
                "sim_agent_properties": {
                    "roll_steps": "60",
                    "total_steps": 36,
                    "sim_step_size": 120,
                    "output_step_size": 7200,
                },
            }
        )

        self.assertEqual(config.hydros_objects_modeling_url, "https://example.test/objects.yaml")
        self.assertIsNotNone(config.sim_agent_properties)
        self.assertEqual(config.sim_agent_properties.roll_steps, 60)
        self.assertEqual(config.sim_agent_properties.total_steps, 36)
        self.assertEqual(config.sim_agent_properties.sim_step_size, 120)
        self.assertEqual(config.sim_agent_properties.output_step_size, 7200)

    def test_context_repository_keeps_scenario_config_without_modeling_url(self):
        context = SimulationContext(biz_scene_instance_id="scene-sim-agent-only")
        repository = HydroModelContextRepository()
        request = SimpleNamespace(
            context=context,
            biz_scene_configuration_url="https://example.test/scenario.yaml",
        )

        with patch(
            "hydros_agent_sdk.context_manager.YamlLoader.from_url",
            return_value={
                "sim_agent_properties": {
                    "roll_steps": 60,
                    "total_steps": 36,
                },
            },
        ):
            model_context = repository.create_from_init_request(request)

        self.assertIsNotNone(model_context)
        self.assertIsNone(model_context.topology)
        self.assertEqual(model_context.sim_agent_properties.roll_steps, 60)
        self.assertEqual(model_context.sim_agent_properties.total_steps, 36)

    def test_client_on_message_no_longer_filters_remote_target_early(self):
        client = AgentCommandClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
        )
        client.runtime.handle_incoming_command = Mock()

        context = SimulationContext(biz_scene_instance_id="scene-002")
        source = build_agent_instance("source-002", "SOURCE_AGENT", "node-a", context)
        remote_target = build_agent_instance("target-002", "TARGET_AGENT", "node-remote", context)
        payload = {
            "command_id": "cmd-002",
            "command_type": "update_station_target_value_request",
            "source": source.model_dump(mode="json"),
            "target": remote_target.model_dump(mode="json"),
            "object_id": 501,
            "object_type": "Gate",
            "target_value_type": "gate_opening",
            "target_value": 0.31,
        }

        client._on_message(None, None, SimpleNamespace(payload=json.dumps(payload).encode("utf-8")))

        client.runtime.handle_incoming_command.assert_called_once()

    def test_client_start_cleans_up_when_connection_times_out(self):
        client = AgentCommandClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
        )
        client.mqtt_client.connect = Mock()
        client.mqtt_client.loop_start = Mock()
        client.mqtt_client.loop_stop = Mock()
        client.mqtt_client.disconnect = Mock()
        client._connected.wait = Mock(return_value=False)
        client.runtime.start = Mock()

        with self.assertRaises(RuntimeError):
            client.start()

        client.mqtt_client.loop_stop.assert_called_once()
        client.mqtt_client.disconnect.assert_called_once()
        client.runtime.start.assert_not_called()
        self.assertTrue(client._intentional_disconnect)

    def test_client_lazy_builds_runtime(self):
        client = AgentCommandClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
        )

        self.assertIsNone(client._runtime)
        self.assertFalse(os.path.exists(os.path.join("data", "agent_data.db")))

        runtime = client.runtime

        self.assertIsNotNone(runtime)
        self.assertIsNotNone(client._runtime)
        self.assertFalse(os.path.exists(os.path.join("data", "agent_data.db")))

    def test_runtime_executes_command_without_persistence_side_effect(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        context = SimulationContext(
            biz_scene_instance_id="scene-010",
            biz_scenario=BizScenario(
                biz_scenario_id="biz-scenario-010",
                biz_scenario_name="Demo Scenario",
            ),
        )
        source = build_agent_instance("source-010", "SOURCE_AGENT", "node-a", context)
        target = build_agent_instance("target-010", "TARGET_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        state_manager.add_local_agent(target)

        runtime = AgentCommandRuntime(
            state_manager=state_manager,
            sender=lambda command: None,
            max_workers=1,
        )
        completed_event = Event()

        class RecordingStationTargetValueHandler(StationTargetValueHandler):
            def execute(self, request: HydroStationTargetValueRequest) -> HydroStationTargetValueResponse:
                response = super().execute(request)
                completed_event.set()
                return response

        runtime.register_handler(RecordingStationTargetValueHandler())

        runtime.start()
        try:
            runtime.send_command(
                HydroStationTargetValueRequest(
                    command_id="cmd-010",
                    source=source,
                    target=target,
                    object_id=501,
                    object_type="Gate",
                    target_value_type="gate_opening",
                    target_value=0.42,
                )
            )

            self.assertTrue(completed_event.wait(timeout=2.0))
        finally:
            runtime.stop()

    def test_runtime_can_restart_after_stop(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        context = SimulationContext(biz_scene_instance_id="scene-003")
        source = build_agent_instance("source-003", "SOURCE_AGENT", "node-a", context)
        target = build_agent_instance("target-003", "TARGET_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        state_manager.add_local_agent(target)

        sent_commands = []
        runtime = AgentCommandRuntime(
            state_manager=state_manager,
            sender=sent_commands.append,
            max_workers=1,
        )
        completed = []
        completed_event = Event()

        class RecordingStationTargetValueHandler(StationTargetValueHandler):
            def execute(self, request: HydroStationTargetValueRequest) -> HydroStationTargetValueResponse:
                response = super().execute(request)
                completed.append(response)
                completed_event.set()
                return response

        runtime.register_handler(RecordingStationTargetValueHandler())

        def send_and_wait(command_id: str, target_value: float):
            completed_event.clear()
            runtime.send_command(
                HydroStationTargetValueRequest(
                    command_id=command_id,
                    source=source,
                    target=target,
                    object_id=501,
                    object_type="Gate",
                    target_value_type="gate_opening",
                    target_value=target_value,
                )
            )
            self.assertTrue(completed_event.wait(timeout=2.0))
            self.assertEqual(completed[-1].command_id, command_id)
            self.assertEqual(completed[-1].command_status, CommandStatus.SUCCEED)

        runtime.start()
        send_and_wait("cmd-003a", 0.12)
        runtime.stop()
        self.assertFalse(os.path.exists(os.path.join("data", "agent_data.db")))

        runtime.start()
        send_and_wait("cmd-003b", 0.24)
        runtime.stop()

        self.assertEqual(sent_commands, [])

    def test_central_scheduling_agent_starts_agent_command_client(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            mqtt_username="cmd-user",
            mqtt_password="cmd-pass",
        )

        context = SimulationContext(biz_scene_instance_id="scene-004")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-004",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        request = SimTaskInitRequest(
            command_id="init-004",
            context=context,
            agent_list=[
                HydroAgent(
                    agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
                    agent_type="CENTRAL_SCHEDULING_AGENT",
                    agent_name="中央调度智能体",
                )
            ],
        )

        with patch("hydros_agent_sdk.agents.central_scheduling_agent.AgentCommandClient") as mock_client_cls:
            mock_client = Mock()
            mock_client_cls.return_value = mock_client

            agent.on_init(request)
            agent._agent_command_gateway.send_command(Mock())
            agent.on_terminate(SimTaskTerminateRequest(command_id="term-004", context=context))

            mock_client_cls.assert_called_once_with(
                broker_url="127.0.0.1",
                broker_port=1883,
                hydros_cluster_id="demo-cluster",
                state_manager=state_manager,
                mqtt_username="cmd-user",
                mqtt_password="cmd-pass",
            )
            mock_client.start.assert_called_once()
            mock_client.send_command.assert_called_once()
            mock_client.stop.assert_called_once()

    def test_central_scheduling_agent_builds_station_target_value_request(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-006")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-006",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        target = build_agent_instance("target-006", "PUMP_AGENT_001", "node-b", context)

        with patch.object(agent._control_command_builder, "get_sibling_agent_instance", return_value=target):
            request = agent._control_command_builder.build_station_target_value_request(
                target_agent_code="PUMP_AGENT_001",
                target_command_type=DeviceValueTypeEnum.GATE_OPENING.code,
                target_value=1.25,
                object_id=1023,
                object_type=HydroObjectType.PUMP,
            )

        self.assertIsNotNone(request)
        self.assertEqual(request.command_type, "update_station_target_value_request")
        self.assertEqual(request.target.agent_code, "PUMP_AGENT_001")
        self.assertEqual(request.target_value_type, DeviceValueTypeEnum.GATE_OPENING.code)
        self.assertEqual(request.target_value, 1.25)

    def test_station_target_value_request_requires_target_fields(self):
        valid_request = HydroStationTargetValueRequest(
            command_id=generate_agent_command_id(),
            object_type="Gate",
            target_value_type="gate_opening",
            target_value=0.0,
        )

        self.assertEqual(valid_request.object_type, "Gate")
        self.assertEqual(valid_request.target_value_type, "gate_opening")
        self.assertEqual(valid_request.target_value, 0.0)

        invalid_payloads = [
            {
                "command_id": generate_agent_command_id(),
                "target_value_type": "gate_opening",
                "target_value": 1.0,
            },
            {
                "command_id": generate_agent_command_id(),
                "object_type": " ",
                "target_value_type": "gate_opening",
                "target_value": 1.0,
            },
            {
                "command_id": generate_agent_command_id(),
                "object_type": "Gate",
                "target_value": 1.0,
            },
            {
                "command_id": generate_agent_command_id(),
                "object_type": "Gate",
                "target_value_type": " ",
                "target_value": 1.0,
            },
            {
                "command_id": generate_agent_command_id(),
                "object_type": "Gate",
                "target_value_type": "gate_opening",
                "target_value": None,
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    HydroStationTargetValueRequest(**payload)

    def test_mpc_command_builder_skips_blank_station_target_fields(self):
        context = SimulationContext(biz_scene_instance_id="scene-007")
        source = build_agent_instance("source-007", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        resolver = Mock()
        builder = MpcControlCommandBuilder(
            source_agent=source,
            get_sibling_agent_instance=Mock(),
            resolve_target_agent_for_object=resolver,
        )
        response = MpcOptimizeResponse(
            plan_type="OPTIMAL",
            horizon_controls=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_id=501,
                            object_type=" ",
                            target_value_type="gate_opening",
                            target_value=0.45,
                        ),
                        ControlObjectResult(
                            object_id=502,
                            object_type="Gate",
                            target_value_type=" ",
                            target_value=0.5,
                        ),
                    ],
                )
            ],
        )

        self.assertEqual(builder.build_from_mpc_responses([response]), [])
        resolver.assert_not_called()

    def test_control_command_dispatcher_sends_control_commands(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-008")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-008",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        control_command = {
            "target_agent_code": "PUMP_AGENT_001",
            "target_command_type": DeviceValueTypeEnum.OUTPUT_POWER.code,
            "target_value": 85.5,
            "object_id": 1021,
            "object_type": HydroObjectType.TURBINE,
        }
        pump_request = Mock(name="pump_request")
        with patch.object(
            agent._control_command_dispatcher,
            "build_station_target_value_request",
            return_value=pump_request,
        ) as build_request, patch.object(
            agent._control_command_dispatcher,
            "send_command",
        ) as send_command:
            agent._control_command_dispatcher.dispatch([control_command])

        build_request.assert_called_once_with(
            target_agent_code="PUMP_AGENT_001",
            target_command_type=DeviceValueTypeEnum.OUTPUT_POWER.code,
            target_value=85.5,
            object_id=1021,
            object_type=HydroObjectType.TURBINE,
        )
        send_command.assert_called_once_with(pump_request)

    def test_central_scheduling_agent_caches_recent_field_metrics_by_default_window(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-007")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-007",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        for step_index in range(1, 12):
            agent._metrics_subscriber.handle_payload(
                "metrics/topic",
                {
                    "object_id": 1001,
                    "metrics_code": "flow",
                    "value": float(step_index),
                    "timestamp": f"ts-{step_index}",
                    "step_index": step_index,
                    "position_code": "none",
                },
            )

        self.assertEqual(agent._metrics_data_cache.get_value(1001, "flow"), 11.0)
        self.assertEqual(set(agent._metrics_data_cache.history().keys()), set(range(2, 12)))
        self.assertNotIn(1, agent._metrics_data_cache.history())
        self.assertEqual(agent._metrics_data_cache.by_step(11)["1001_flow"]["value"], 11.0)

    def test_central_scheduling_agent_filters_field_metrics_by_position_code(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-007-position")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-007-position",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        agent._metrics_subscriber.handle_payload(
            "metrics/topic",
            {
                "object_id": 1001,
                "metrics_code": "flow",
                "value": 1.0,
                "step_index": 1,
                "position_code": "upstream",
            },
        )
        agent._metrics_subscriber.handle_payload(
            "metrics/topic",
            {
                "object_id": 1001,
                "metrics_code": "flow",
                "value": 2.0,
                "step_index": 2,
                "position_code": "none",
            },
        )

        self.assertEqual(agent._metrics_data_cache.get_value(1001, "flow"), 2.0)
        self.assertEqual(agent._metrics_data_cache.by_step(1), {})
        self.assertEqual(agent._metrics_data_cache.by_step(2)["1001_flow"]["position_code"], "none")

    def test_central_scheduling_agent_activates_mpc_on_time_series_update(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-011")
        register_sim_agent_properties(context, roll_steps=3, total_steps=20)
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-011",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )

        response = agent.on_time_series_data_update(
            build_time_series_update_request(context, auto_schedule_at_step=5)
        )

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        self.assertEqual(agent.optimization_steps, [5])
        runtime = agent._mpc_rolling_runtime
        self.assertTrue(runtime.is_mpc_optimizing_on_the_loop())
        self.assertEqual(runtime.mpc_task_state.start_step, 5)
        self.assertEqual(runtime.mpc_task_state.current_step, 5)
        self.assertEqual(runtime.mpc_task_state.rolling_interval_steps, 3)
        self.assertEqual(runtime.mpc_task_state.total_steps, 20)
        self.assertEqual(runtime.mpc_task_state.output_step_size, 7200)
        self.assertEqual(runtime.mpc_task_state.mpc_config_url, "http://config/mpc.yaml")
        self.assertEqual(runtime.mpc_task_state.target_and_constrain_config_url, "http://config/control.yaml")
        self.assertEqual(len(runtime.mpc_task_state.hydro_events), 1)
        self.assertEqual(agent.agent_status, AgentStatus.ACTIVE)

    def test_central_scheduling_agent_fails_without_rolling_config(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-011-missing-roll")
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-011-missing-roll",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        response = agent.on_time_series_data_update(
            build_time_series_update_request(context, auto_schedule_at_step=5)
        )

        self.assertEqual(response.command_status, CommandStatus.FAILED)
        self.assertIsNone(agent._mpc_rolling_runtime.mpc_task_state)

    def test_central_scheduling_agent_prefers_scenario_sim_agent_properties(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-011-scenario-config")
        ContextManager.create(
            context=context,
            scenario_config=BizScenarioConfiguration(
                sim_agent_properties=SimAgentProperties(
                    roll_steps=60,
                    total_steps=36,
                    output_step_size=1800,
                )
            ),
        )
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-011-scenario-config",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        agent.properties["roll_steps"] = 10

        response = agent.on_time_series_data_update(
            build_time_series_update_request(context, auto_schedule_at_step=5)
        )

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        runtime = agent._mpc_rolling_runtime
        self.assertEqual(runtime.mpc_task_state.rolling_interval_steps, 60)
        self.assertEqual(runtime.mpc_task_state.total_steps, 36)
        self.assertEqual(runtime.mpc_task_state.output_step_size, 1800)

    def test_central_scheduling_agent_reads_mpc_config_urls_from_configured_property_names(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-011-config-alias")
        register_sim_agent_properties(context, roll_steps=3, total_steps=20, output_step_size=None)
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-011-config-alias",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        agent.properties.update(
            {
                "mpc_config_url": "http://config/mpc.yaml",
                "target_and_constrain_config_url": "http://config/control.yaml",
                "output_step_size": "3600",
            }
        )

        response = agent.on_time_series_data_update(
            build_time_series_update_request(context, auto_schedule_at_step=5)
        )

        self.assertEqual(response.command_status, CommandStatus.SUCCEED)
        runtime = agent._mpc_rolling_runtime
        self.assertEqual(runtime.mpc_task_state.mpc_config_url, "http://config/mpc.yaml")
        self.assertEqual(
            runtime.mpc_task_state.target_and_constrain_config_url,
            "http://config/control.yaml",
        )
        self.assertEqual(runtime.mpc_task_state.output_step_size, 3600)

    def test_central_scheduling_agent_can_opt_into_tick_auto_start_and_rolls(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-012")
        register_sim_agent_properties(context, roll_steps=3, total_steps=20)
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-012",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )
        agent.properties["auto_start_mpc_on_tick"] = True

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-before", context=context, step=0))
        self.assertEqual(agent.optimization_steps, [0])
        runtime = agent._mpc_rolling_runtime
        self.assertTrue(runtime.is_mpc_optimizing_on_the_loop())
        self.assertEqual(runtime.mpc_task_state.start_step, 0)

        agent.on_time_series_data_update(
            build_time_series_update_request(context, command_id="ts-update-012", auto_schedule_at_step=1)
        )
        self.assertEqual(agent.optimization_steps, [0])
        self.assertEqual(len(runtime.mpc_task_state.hydro_events), 1)

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-2", context=context, step=2))
        self.assertEqual(agent.optimization_steps, [0])

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-3", context=context, step=3))
        self.assertEqual(agent.optimization_steps, [0, 3])
        self.assertEqual(runtime.mpc_task_state.current_loop, 3)

    def test_central_scheduling_agent_does_not_auto_start_mpc_on_tick_by_default(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )

        context = SimulationContext(biz_scene_instance_id="scene-012-disabled")
        register_sim_agent_properties(context, roll_steps=3, total_steps=20)
        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-012-disabled",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        agent.on_tick_simulation(TickCmdRequest(command_id="tick-disabled", context=context, step=0))

        self.assertEqual(agent.optimization_steps, [])
        self.assertFalse(agent._mpc_rolling_runtime.is_mpc_optimizing_on_the_loop())

    def test_mpc_config_resolver_reads_mpc_service_base_url_from_environment(self):
        with patch.dict(
            os.environ,
            {"HYDROS_MPC_SERVICE_BASE_URL": "http://mpc.local/hydros/api/v1/mpc/planning/start"},
            clear=False,
        ):
            self.assertEqual(
                MpcConfigResolver.get_mpc_service_base_url(AgentProperties()),
                "http://mpc.local/hydros/api/v1/mpc/planning/start",
            )

    def test_mpc_config_resolver_reads_mpc_request_timeout_from_environment(self):
        with patch.dict(
            os.environ,
            {"HYDROS_MPC_REQUEST_TIMEOUT_SECONDS": "240"},
            clear=False,
        ):
            self.assertEqual(
                MpcConfigResolver.get_mpc_request_timeout_seconds(AgentProperties()),
                240.0,
            )

    def test_mpc_config_resolver_prefers_agent_property_timeout(self):
        properties = AgentProperties({"mpc_request_timeout_seconds": "90"})

        self.assertEqual(
            MpcConfigResolver.get_mpc_request_timeout_seconds(
                properties,
                configured_timeout_seconds=240.0,
            ),
            90.0,
        )

    def test_runtime_env_settings_centralizes_defaults_and_overrides(self):
        with patch.dict(
            os.environ,
            {
                "HYDROS_CLUSTER_ID": "env-cluster",
                "HYDROS_MPC_SERVICE_BASE_URL": "http://mpc.env/hydros/api/v1/mpc/planning/start",
                "HYDROS_MPC_REQUEST_TIMEOUT_SECONDS": "240",
            },
            clear=True,
        ):
            settings = RuntimeEnvSettings.from_config(
                {
                    "hydros_cluster_id": "config-cluster",
                    "metrics_topic": "/hydros/data/edges/{hydros_cluster_id}",
                    "mpc_service_base_url": "http://mpc.config/hydros/api/v1/mpc/planning/start",
                    "mpc_request_timeout_seconds": "120",
                }
            )

        self.assertEqual(settings.hydros_cluster_id, "env-cluster")
        self.assertEqual(settings.mpc_service_base_url, "http://mpc.env/hydros/api/v1/mpc/planning/start")
        self.assertEqual(settings.mpc_request_timeout_seconds, 240.0)
        self.assertEqual(settings.rendered_metrics_topic(), "/hydros/data/edges/env-cluster")

    def test_load_env_config_defaults_to_nearest_application_env_properties(self):
        app_dir = os.path.join(self._temp_dir.name, "app")
        child_dir = os.path.join(app_dir, "agents", "pump")
        os.makedirs(child_dir, exist_ok=True)
        env_path = os.path.join(app_dir, "env.properties")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(
                "\n".join(
                    [
                        "mqtt_broker_url=tcp://127.0.0.1",
                        "mqtt_broker_port=1883",
                        "hydros_cluster_id=test-cluster",
                        "hydros_node_id=test-node",
                        "mpc_service_base_url=http://mpc.local/hydros/api/v1/mpc/planning/start",
                        "mpc_request_timeout_seconds=180",
                    ]
                )
            )

        os.chdir(child_dir)

        self.assertEqual(
            os.path.realpath(get_default_env_config_path()),
            os.path.realpath(os.path.join(child_dir, "env.properties")),
        )
        self.assertEqual(load_env_config(), load_env_config(env_path))
        self.assertEqual(
            load_env_config()["mpc_service_base_url"],
            "http://mpc.local/hydros/api/v1/mpc/planning/start",
        )
        self.assertEqual(load_env_config()["mpc_request_timeout_seconds"], "180")

    def test_system_central_factory_passes_mpc_config_from_env_config(self):
        from hydros_agent_sdk.factory import SystemCentralSchedulingAgentFactory

        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )
        context = SimulationContext(biz_scene_instance_id="scene-012-factory-url")
        factory = SystemCentralSchedulingAgentFactory(
            env_config={
                "hydros_cluster_id": "demo-cluster",
                "hydros_node_id": "node-a",
                "mpc_service_base_url": "http://mpc.local/hydros/api/v1/mpc/planning/start",
                "mpc_request_timeout_seconds": "210",
            }
        )

        agent = factory.create_agent(sim_client, context)
        client = agent._mpc_optimization_service.get_or_create_mpc_planning_client()

        self.assertIsNotNone(client)
        self.assertEqual(client.base_url, "http://mpc.local/hydros/api/v1/mpc/planning/start")
        self.assertEqual(client.timeout_seconds, 210.0)

    def test_system_central_factory_can_create_agent_without_env_properties_file(self):
        from hydros_agent_sdk.factory import SystemCentralSchedulingAgentFactory

        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
        )
        context = SimulationContext(biz_scene_instance_id="scene-012-no-env")
        factory = SystemCentralSchedulingAgentFactory()

        agent = factory.create_agent(sim_client, context)

        self.assertEqual(agent.cluster_id, "demo-cluster")
        self.assertEqual(agent.node_id, "node-a")
        self.assertEqual(agent.agent_code, "CENTRAL_SCHEDULING_AGENT")

    def test_mpc_planning_client_builds_java_compatible_request(self):
        context = SimulationContext(biz_scene_instance_id="scene-013")
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=10,
            current_step=15,
            output_step_size=7200,
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )
        state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="WEATHER_FORECAST",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=1001,
                        object_name="lateral-inflow",
                        time_series=[
                            TimeSeriesValue(step=10, value=100.0),
                            TimeSeriesValue(step=20, value=200.0),
                        ],
                    )
                ],
            )
        )
        state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="DEVICE_FAULT",
                object_time_series=[ObjectTimeSeries(object_id=2001)],
            )
        )
        state.register_hydro_event(
            TimeSeriesDataChangedEvent(
                hydro_event_source_type="WATER_USE",
                object_time_series=[
                    ObjectTimeSeries(
                        object_id=3001,
                        time_series=[
                            TimeSeriesValue(step=15, value=3.0),
                            TimeSeriesValue(step=18, value=4.0),
                        ],
                    )
                ],
            )
        )
        client = MpcPlanningClient(
            base_url="http://mpc.local/hydros/api/v1/mpc/planning/start",
            require_sensor_data=True,
        )

        request = client.build_optimize_request(
            state,
            [SensorData(object_id=9001, metrics_code="water_level", value=12.5, step_index=15)],
        )
        payload = request.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(payload["biz_scene_instance_id"], "scene-013")
        self.assertEqual(payload["step_index"], 15)
        self.assertEqual(payload["mpc_config_url"], "http://config/mpc.yaml")
        self.assertEqual(payload["control_config_url"], "http://config/control.yaml")
        self.assertEqual(payload["horizon_interval_seconds"], 7200)
        self.assertEqual(payload["upstream_boundaries"]["1001"], [150.0, 200.0])
        self.assertEqual(payload["sensor_data"][0]["object_id"], 9001)
        self.assertEqual(payload["sensor_data"][0]["metrics_code"], "water_level")
        self.assertEqual(payload["fixed_controls"], {"2001": 0.0})
        self.assertTrue(payload["include_diversion"])
        self.assertNotIn("bizSceneInstanceId", payload)
        self.assertNotIn("upstreamBoundaries", payload)
        self.assertNotIn("sensorData", payload)
        self.assertNotIn("targets", payload)
        self.assert_snake_case_keys(payload)

    def test_mpc_planning_client_logs_request_and_response_summaries(self):
        context = SimulationContext(biz_scene_instance_id="scene-013-log")
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=2,
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )
        raw_response = {
            "success": True,
            "data": [
                {
                    "plan_type": "OPTIMAL",
                    "loss": 0.5,
                    "horizon_controls": [
                        {
                            "horizon_step": 1,
                            "control_object_list": [
                                {
                                    "object_type": "Gate",
                                    "node_id": 101,
                                    "object_id": 501,
                                    "target_value": 0.8,
                                }
                            ],
                        },
                        {
                            "horizon_step": 2,
                            "control_object_list": [
                                {
                                    "object_type": "Gate",
                                    "node_id": 102,
                                    "object_id": 502,
                                    "target_value": 0.7,
                                }
                            ],
                        },
                        {
                            "horizon_step": 3,
                            "control_object_list": [
                                {
                                    "object_type": "Gate",
                                    "node_id": 103,
                                    "object_id": 503,
                                    "target_value": 0.6,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        class FakeHttpResponse:
            def read(self):
                return json.dumps(raw_response).encode("utf-8")

        def fake_opener(request, timeout_seconds):
            self.assertEqual(request.full_url, "http://mpc.local/hydros/api/v1/mpc/planning/start")
            self.assertIn(b'"biz_scene_instance_id": "scene-013-log"', request.data)
            self.assertIn(b'"sensor_data"', request.data)
            self.assertIn(b'"object_id": 9001', request.data)
            self.assertNotIn(b'"bizSceneInstanceId"', request.data)
            self.assertNotIn(b'"sensorData"', request.data)
            self.assertNotIn(b'"targets"', request.data)
            self.assertEqual(timeout_seconds, 200.0)
            return FakeHttpResponse()

        client = MpcPlanningClient(
            base_url="http://mpc.local/hydros/api/v1/mpc/planning/start",
            opener=fake_opener,
            require_sensor_data=True,
        )

        with self.assertLogs("hydros_agent_sdk.mpc.client", level="INFO") as logs:
            responses = client.execute_optimization(
                state,
                [SensorData(object_id=9001, metrics_code="water_level", value=12.5, step_index=2)],
            )

        log_output = "\n".join(logs.output)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].plan_type, "OPTIMAL")
        self.assertEqual(len(responses[0].horizon_controls), 3)
        self.assertIn("Sending MPC optimization request", log_output)
        self.assertIn("biz_scene_instance_id=scene-013-log", log_output)
        self.assertIn("sensor_data_count=1", log_output)
        self.assertIn("MPC optimization raw response received", log_output)
        self.assertIn("MPC optimization response parsed", log_output)
        self.assertIn("response_count=1", log_output)
        self.assertIn("horizon_control_count=3", log_output)
        self.assertIn("plan_types=OPTIMAL", log_output)
        self.assertNotIn('"sensor_data"', log_output)
        self.assertNotIn('"object_id": 9001', log_output)
        self.assertNotIn('"object_id": 501', log_output)
        self.assertNotIn('"object_id": 502', log_output)
        self.assertNotIn('"object_id": 503', log_output)

    def assert_snake_case_keys(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                self.assertEqual(key, key.lower())
                self.assert_snake_case_keys(child)
            return
        if isinstance(value, list):
            for child in value:
                self.assert_snake_case_keys(child)

    def test_mpc_planning_client_uses_configured_full_planning_start_url(self):
        client = MpcPlanningClient(base_url="http://mpc.local/hydros/api/v1/mpc/planning/start")

        self.assertEqual(
            client.planning_start_url,
            "http://mpc.local/hydros/api/v1/mpc/planning/start",
        )

    def test_mpc_planning_client_logs_empty_sensor_data_before_request(self):
        context = SimulationContext(biz_scene_instance_id="scene-013-empty-sensor")
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=2,
            mpc_config_url="http://config/mpc.yaml",
            target_and_constrain_config_url="http://config/control.yaml",
        )
        opener = Mock()
        client = MpcPlanningClient(
            base_url="http://mpc.local/hydros/api/v1/mpc/planning/start",
            opener=opener,
            require_sensor_data=True,
            empty_sensor_retry_delay_seconds=0,
            empty_sensor_retry_count=1,
        )

        with self.assertLogs("hydros_agent_sdk.mpc.client", level="INFO") as logs:
            with self.assertRaises(MpcPlanningError):
                client.execute_optimization(state, [], sensor_provider=lambda: [])

        log_output = "\n".join(logs.output)
        self.assertIn("MPC sensor_data is empty before retry", log_output)
        self.assertIn("MPC sensor_data is empty; request will not be sent", log_output)
        opener.assert_not_called()

    def test_mpc_result_reporter_builds_result_report_payload(self):
        context = SimulationContext(
            biz_scene_instance_id="scene-014",
            tenant=Tenant(tenant_id="tenant-014", tenant_name="Tenant"),
            biz_scenario=BizScenario(
                biz_scenario_id="scenario-014",
                biz_scenario_name="Scenario",
            ),
            waterway=Waterway(waterway_id="waterway-014", waterway_name="Waterway"),
        )
        source = build_agent_instance("agent-014", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=4,
        )
        response = MpcOptimizeResponse(
            plan_type="OPTIMAL",
            loss=0.12,
            gate_operations=1,
            gate_amplitude=0.4,
            horizon_controls=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=101,
                            object_id=501,
                            target_value=0.45,
                            target_value_type="OPENING",
                        )
                    ],
                    predicted_result_list=[
                        PredictedResult(
                            object_type="Canal",
                            object_id=102,
                            front_water_level=2.1,
                            final_target_water_level=2.3,
                            back_water_level=1.9,
                            out_flow=33.0,
                        )
                    ],
                )
            ],
        )

        report = MpcResultReporter().build_report(source, state, [response])
        payload = report.model_dump(by_alias=True)

        self.assertIsInstance(report, MpcResultReport)
        self.assertEqual(report.command_type, "mpc_result_report")
        self.assertTrue(report.broadcast)
        self.assertEqual(payload["source_agent_instance"]["agent_id"], "agent-014")
        self.assertEqual(payload["mpc_results"][0]["biz_scene_instance_id"], "scene-014")
        self.assertEqual(payload["mpc_results"][0]["waterway_id"], "waterway-014")
        self.assertEqual(payload["mpc_results"][0]["tenant_id"], "tenant-014")
        self.assertEqual(payload["mpc_results"][0]["biz_scenario_id"], "scenario-014")
        self.assertEqual(payload["mpc_results"][0]["details"][0]["command_type"], "OPENING")
        self.assertEqual(payload["mpc_results"][0]["details"][0]["object_type"], "Gate")
        self.assertEqual(payload["mpc_results"][0]["details"][0]["node_id"], 101)
        self.assertEqual(payload["mpc_results"][0]["details"][0]["object_id"], 501)
        self.assertEqual(payload["mpc_results"][0]["details"][0]["target_value"], 0.45)
        self.assertEqual(payload["mpc_results"][0]["details"][1]["command_type"], "WATER_LEVEL")
        self.assertEqual(payload["mpc_results"][0]["details"][1]["node_id"], 102)
        self.assertEqual(payload["mpc_results"][0]["details"][1]["object_id"], 0)
        self.assertEqual(payload["mpc_results"][0]["details"][1]["target_value"], 2.3)
        attributes = json.loads(payload["mpc_results"][0]["details"][1]["attributes"])
        self.assertEqual(attributes["front_water_level"], 2.1)
        self.assertEqual(attributes["back_water_level"], 1.9)
        self.assertEqual(attributes["final_target_water_level"], 2.3)
        self.assertEqual(attributes["out_flow"], 33.0)

    def test_mpc_result_reporter_builds_single_result_from_horizon_steps(self):
        context = SimulationContext(biz_scene_instance_id="scene-014-single-result")
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=4,
        )

        result = MpcResultReporter.build_result(
            mpc_task_state=state,
            horizon_step=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=101,
                            object_id=501,
                            target_value=0.45,
                            target_value_type="OPENING",
                        )
                    ],
                    predicted_result_list=[
                        PredictedResult(
                            object_type="Canal",
                            object_id=102,
                            front_water_level=2.1,
                            final_target_water_level=2.3,
                            back_water_level=1.9,
                            out_flow=33.0,
                        )
                    ],
                )
            ],
            plan_type="OPTIMAL",
            loss=0.12,
            gate_operations=1,
            gate_amplitude=0.4,
        )

        self.assertEqual(result.biz_scene_instance_id, "scene-014-single-result")
        self.assertEqual(result.step, 4)
        self.assertEqual(result.plan_type, "OPTIMAL")
        self.assertEqual(result.loss, 0.12)
        self.assertEqual(result.gate_operations, 1)
        self.assertEqual(result.gate_amplitude, 0.4)
        self.assertEqual(len(result.details), 2)
        self.assertEqual(result.details[0].command_type, "OPENING")
        self.assertEqual(result.details[0].object_type, "Gate")
        self.assertEqual(result.details[0].node_id, 101)
        self.assertEqual(result.details[0].object_id, 501)
        self.assertEqual(result.details[0].target_value, 0.45)
        self.assertEqual(result.details[1].command_type, "WATER_LEVEL")
        self.assertEqual(result.details[1].object_type, "Canal")
        self.assertEqual(result.details[1].node_id, 102)
        self.assertEqual(result.details[1].object_id, 0)
        self.assertEqual(result.details[1].target_value, 2.3)

    def test_mpc_result_reporter_builds_customize_report(self):
        context = SimulationContext(biz_scene_instance_id="scene-014-customize-report")
        source = build_agent_instance("agent-014-customize-report", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=4,
        )

        report = MpcResultReporter().build_customize_report(
            source_agent_instance=source,
            mpc_task_state=state,
            horizon_step=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=101,
                            object_id=501,
                            target_value=0.45,
                            target_value_type="OPENING",
                        )
                    ],
                )
            ],
            plan_type="CUSTOMIZE",
        )

        self.assertIsInstance(report, MpcResultReport)
        self.assertEqual(report.context.biz_scene_instance_id, "scene-014-customize-report")
        self.assertEqual(report.source_agent_instance.agent_id, "agent-014-customize-report")
        self.assertEqual(len(report.mpc_results), 1)
        self.assertEqual(report.mpc_results[0].plan_type, "CUSTOMIZE")
        self.assertEqual(report.mpc_results[0].details[0].object_type, "Gate")
        self.assertEqual(report.mpc_results[0].details[0].node_id, 101)
        self.assertEqual(report.mpc_results[0].details[0].object_id, 501)

    def test_mpc_result_reporter_publishes_customize_report(self):
        context = SimulationContext(biz_scene_instance_id="scene-014-customize-publish")
        source = build_agent_instance("agent-014-customize-publish", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=4,
        )
        enqueued = []
        reporter = MpcResultReporter(sim_coordination_client=SimpleNamespace(enqueue=enqueued.append))

        with self.assertLogs("hydros_agent_sdk.mpc.reporter", level="INFO") as logs:
            report = reporter.publish_customize_report(
                source_agent_instance=source,
                mpc_task_state=state,
                horizon_step=[
                    HorizonStep(
                        horizon_step=1,
                        control_object_list=[
                            ControlObjectResult(
                                object_type="Gate",
                                node_id=101,
                                object_id=501,
                                target_value=0.45,
                                target_value_type="OPENING",
                            )
                        ],
                    )
                ],
                plan_type="CUSTOMIZE",
            )

        self.assertIs(enqueued[0], report)
        self.assertEqual(report.mpc_results[0].plan_type, "CUSTOMIZE")
        log_output = "\n".join(logs.output)
        self.assertIn("MPC customize result report prepared for coordinator", log_output)
        self.assertIn("MPC customize result report enqueued to coordinator", log_output)
        self.assertIn(report.command_id, log_output)
        self.assertIn("result_count=1", log_output)
        self.assertIn("detail_count=1", log_output)

    def test_mpc_result_reporter_accepts_current_predicted_result_fields(self):
        context = SimulationContext(
            biz_scene_instance_id="scene-014-renamed-fields",
            tenant=Tenant(tenant_id="tenant-014", tenant_name="Tenant"),
            biz_scenario=BizScenario(
                biz_scenario_id="scenario-014",
                biz_scenario_name="Scenario",
            ),
            waterway=Waterway(waterway_id="waterway-014", waterway_name="Waterway"),
        )
        source = build_agent_instance("agent-014-renamed-fields", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=4,
        )
        response = MpcOptimizeResponse.model_validate(
            {
                "plan_type": "OPTIMAL",
                "horizon_controls": [
                    {
                        "horizon_step": 1,
                        "predicted_result_list": [
                            {
                                "object_type": "Canal",
                                "object_id": 31400,
                                "front_water_level": 63.0,
                                "final_target_water_level": 63.12,
                                "back_water_level": 62.8,
                                "out_flow": 18.5,
                            }
                        ],
                    }
                ],
            }
        )

        report = MpcResultReporter().build_report(source, state, [response])
        payload = report.model_dump(by_alias=True)
        detail = payload["mpc_results"][0]["details"][0]

        self.assertEqual(response.horizon_controls[0].predicted_result_list[0].final_target_water_level, 63.12)
        self.assertEqual(response.horizon_controls[0].predicted_result_list[0].back_water_level, 62.8)
        self.assertEqual(detail["command_type"], "WATER_LEVEL")
        self.assertEqual(detail["object_type"], "Canal")
        self.assertEqual(detail["node_id"], 31400)
        self.assertEqual(detail["object_id"], 0)
        self.assertEqual(detail["value"], 63.0)
        self.assertEqual(detail["target_value"], 63.12)
        attributes = json.loads(detail["attributes"])
        self.assertEqual(attributes["front_water_level"], 63.0)
        self.assertEqual(attributes["back_water_level"], 62.8)
        self.assertEqual(attributes["final_target_water_level"], 63.12)
        self.assertEqual(attributes["out_flow"], 18.5)

    def test_mpc_result_reporter_logs_coordinator_payload_when_publishing(self):
        context = SimulationContext(biz_scene_instance_id="scene-014-log")
        source = build_agent_instance("agent-014-log", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state = MpcTaskState(
            context=context,
            rolling_interval_steps=3,
            start_step=1,
            current_step=4,
        )
        response = MpcOptimizeResponse(
            plan_type="OPTIMAL",
            horizon_controls=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=101,
                            object_id=501,
                            target_value=0.45,
                            target_value_type="OPENING",
                        )
                    ],
                ),
                HorizonStep(
                    horizon_step=2,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=102,
                            object_id=502,
                            target_value=0.55,
                            target_value_type="OPENING",
                        )
                    ],
                ),
                HorizonStep(
                    horizon_step=3,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=103,
                            object_id=503,
                            target_value=0.65,
                            target_value_type="OPENING",
                        )
                    ],
                )
            ],
        )
        enqueued = []
        reporter = MpcResultReporter(sim_coordination_client=SimpleNamespace(enqueue=enqueued.append))

        with self.assertLogs("hydros_agent_sdk.mpc.reporter", level="INFO") as logs:
            report = reporter.publish(source, state, [response])

        self.assertIs(enqueued[0], report)
        log_output = "\n".join(logs.output)
        self.assertIn("MPC result report prepared for coordinator", log_output)
        self.assertIn("MPC result report enqueued to coordinator", log_output)
        self.assertIn("scene-014-log", log_output)
        self.assertIn(report.command_id, log_output)
        self.assertEqual(len(report.mpc_results[0].details), 3)
        self.assertIn("result_count=1", log_output)
        self.assertIn("detail_count=3", log_output)
        self.assertNotIn('"command_type":"mpc_result_report"', log_output)
        self.assertNotIn('"object_id":501', log_output)
        self.assertNotIn('"object_id":502', log_output)
        self.assertNotIn('"object_id":503', log_output)

    def test_central_scheduling_agent_default_mpc_path_reports_and_sends_opening(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        callback = TestSiblingCacheCallback()

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            sim_coordination_callback=callback,
        )

        context = SimulationContext(biz_scene_instance_id="scene-015")
        register_sim_agent_properties(context, roll_steps=3, total_steps=20)
        target = build_agent_instance("gate-agent-015", "GATE_AGENT_015", "node-b", context)
        callback._store_sibling_agent_instance(target)
        mpc_response = MpcOptimizeResponse(
            plan_type="optimal",
            horizon_controls=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=101,
                            object_id=501,
                            object_name="Gate 501",
                            target_value=0.45,
                            target_value_type="OPENING",
                        )
                    ],
                )
            ],
        )
        mpc_client = FakeMpcPlanningClient([mpc_response])
        reporter = FakeMpcResultReporter()
        agent = ProductionCentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-015",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            mpc_planning_client=mpc_client,
            mpc_result_reporter=reporter,
            object_agent_code_map={501: "GATE_AGENT_015"},
        )
        agent._metrics_subscriber.handle_payload(
            "metrics/topic",
            {
                "object_id": 9001,
                "object_type": "Sensor",
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 1,
                "position_code": "none",
            },
        )
        sent_commands = []

        with patch.object(agent._control_command_dispatcher, "send_command", side_effect=sent_commands.append):
            agent.on_time_series_data_update(
                build_time_series_update_request(context, command_id="ts-update-015", auto_schedule_at_step=1)
            )

        self.assertEqual(len(mpc_client.calls), 1)
        self.assertEqual(mpc_client.calls[0]["state"].current_step, 1)
        self.assertEqual(mpc_client.calls[0]["sensor_data"][0].object_id, 9001)
        self.assertEqual(len(reporter.published), 1)
        self.assertEqual(reporter.published[0]["source"], agent)
        self.assertEqual(len(sent_commands), 1)
        self.assertIsInstance(sent_commands[0], HydroStationTargetValueRequest)
        self.assertEqual(sent_commands[0].target.agent_code, "GATE_AGENT_015")
        self.assertEqual(sent_commands[0].object_id, 501)
        self.assertEqual(sent_commands[0].object_type, "Gate")
        self.assertEqual(sent_commands[0].target_value_type, "OPENING")
        self.assertEqual(sent_commands[0].target_value, 0.45)

    def test_central_scheduling_agent_resolves_mpc_target_from_managed_top_objects(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        callback = TestSiblingCacheCallback()

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            sim_coordination_callback=callback,
        )

        context = SimulationContext(biz_scene_instance_id="scene-015-managed")
        target = build_agent_instance("gate-agent-015-managed", "GATE_AGENT_015_MANAGED", "node-b", context)
        register_sim_agent_properties(
            context=context,
            roll_steps=3,
            total_steps=20,
            topology=WaterwayTopology(
                topObjects=[
                    TopologyTopHydroObject(
                        objectId=20600,
                        objectName="Gate Station 20600",
                        objectType="GateStation",
                        children=[
                            SimpleChildObject(
                                objectId=20601,
                                objectName="Gate 20601",
                                objectType="Gate",
                            )
                        ],
                    )
                ]
            ),
        )
        callback.on_agent_instance_sibling_created(
            SimTaskInitResponse(
                command_id="init-015-managed",
                context=context,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=target,
                created_agent_instances=[target],
                managed_top_objects={
                    target.agent_id: [
                        TopHydroObject(
                            object_id=20600,
                            object_name="Gate Station 20600",
                            object_type="GateStation",
                        )
                    ]
                },
            )
        )

        mpc_response = MpcOptimizeResponse(
            plan_type="optimal",
            horizon_controls=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=20600,
                            object_id=20601,
                            object_name="Gate 20601",
                            target_value=1.68,
                            target_value_type="OPENING",
                        )
                    ],
                )
            ],
        )
        mpc_client = FakeMpcPlanningClient([mpc_response])
        reporter = FakeMpcResultReporter()
        agent = ProductionCentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-015-managed",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            mpc_planning_client=mpc_client,
            mpc_result_reporter=reporter,
        )
        agent._metrics_subscriber.handle_payload(
            "metrics/topic",
            {
                "object_id": 9001,
                "object_type": "Sensor",
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 1,
                "position_code": "none",
            },
        )
        sent_commands = []

        with patch.object(agent._control_command_dispatcher, "send_command", side_effect=sent_commands.append):
            agent.on_time_series_data_update(
                build_time_series_update_request(context, command_id="ts-update-015-managed", auto_schedule_at_step=1)
            )

        self.assertEqual(len(sent_commands), 1)
        self.assertIsInstance(sent_commands[0], HydroStationTargetValueRequest)
        self.assertEqual(sent_commands[0].target.agent_code, "GATE_AGENT_015_MANAGED")
        self.assertEqual(sent_commands[0].object_id, 20601)
        self.assertEqual(sent_commands[0].object_type, "Gate")
        self.assertEqual(sent_commands[0].target_value_type, "OPENING")
        self.assertEqual(sent_commands[0].target_value, 1.68)

    def test_central_scheduling_agent_resolves_mpc_target_from_parent_object_mapping(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        callback = TestSiblingCacheCallback()

        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            sim_coordination_callback=callback,
        )

        context = SimulationContext(biz_scene_instance_id="scene-015-parent-map")
        target = build_agent_instance("gate-agent-015-parent", "GATE_AGENT_015_PARENT", "node-b", context)
        callback._store_sibling_agent_instance(target)
        register_sim_agent_properties(
            context=context,
            roll_steps=3,
            total_steps=20,
            topology=WaterwayTopology(
                topObjects=[
                    TopologyTopHydroObject(
                        objectId=20600,
                        objectName="Gate Station 20600",
                        objectType="GateStation",
                        children=[
                            SimpleChildObject(
                                objectId=20601,
                                objectName="Gate 20601",
                                objectType="Gate",
                            )
                        ],
                    )
                ],
                childToParentMap={20601: 20600},
            ),
        )

        mpc_response = MpcOptimizeResponse(
            plan_type="optimal",
            horizon_controls=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="Gate",
                            node_id=20600,
                            object_id=20601,
                            object_name="Gate 20601",
                            target_value=1.68,
                            target_value_type="OPENING",
                        )
                    ],
                )
            ],
        )
        mpc_client = FakeMpcPlanningClient([mpc_response])
        reporter = FakeMpcResultReporter()
        agent = ProductionCentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-015-parent-map",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
            mpc_planning_client=mpc_client,
            mpc_result_reporter=reporter,
            object_agent_code_map={20600: "GATE_AGENT_015_PARENT"},
        )
        agent._metrics_subscriber.handle_payload(
            "metrics/topic",
            {
                "object_id": 9001,
                "object_type": "Sensor",
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 1,
                "position_code": "none",
            },
        )
        sent_commands = []

        with patch.object(agent._control_command_dispatcher, "send_command", side_effect=sent_commands.append):
            agent.on_time_series_data_update(
                build_time_series_update_request(
                    context,
                    command_id="ts-update-015-parent-map",
                    auto_schedule_at_step=1,
                )
            )

        self.assertEqual(len(sent_commands), 1)
        self.assertIsInstance(sent_commands[0], HydroStationTargetValueRequest)
        self.assertEqual(sent_commands[0].target.agent_code, "GATE_AGENT_015_PARENT")
        self.assertEqual(sent_commands[0].object_id, 20601)
        self.assertEqual(sent_commands[0].object_type, "Gate")
        self.assertEqual(sent_commands[0].target_value_type, "OPENING")
        self.assertEqual(sent_commands[0].target_value, 1.68)

    def test_coordination_client_sends_local_mpc_result_report(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        context = SimulationContext(biz_scene_instance_id="scene-016")
        source = build_agent_instance("agent-016", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        client = SimCoordinationClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
            sim_coordination_callback=TestSiblingCacheCallback(),
            state_manager=state_manager,
        )
        report = MpcResultReport(
            command_id="report-016",
            context=context,
            source_agent_instance=source,
            mpc_results=[],
            broadcast=True,
        )

        self.assertTrue(client._should_send(report))

    def test_coordination_client_logs_mpc_result_report_payload_when_sent(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        context = SimulationContext(biz_scene_instance_id="scene-016-log")
        source = build_agent_instance("agent-016-log", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        client = SimCoordinationClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
            sim_coordination_callback=TestSiblingCacheCallback(),
            state_manager=state_manager,
        )
        publish_result = Mock()
        client.mqtt_client = Mock()
        client.mqtt_client.publish.return_value = publish_result
        report = MpcResultReporter().build_report(
            source,
            MpcTaskState(
                context=context,
                rolling_interval_steps=3,
                start_step=1,
                current_step=4,
            ),
            [
                MpcOptimizeResponse(
                    plan_type="OPTIMAL",
                    horizon_controls=[
                        HorizonStep(
                            horizon_step=1,
                            control_object_list=[
                                ControlObjectResult(
                                    object_type="Gate",
                                    node_id=101,
                                    object_id=501,
                                    target_value=0.45,
                                    target_value_type="OPENING",
                                )
                            ],
                        ),
                        HorizonStep(
                            horizon_step=2,
                            control_object_list=[
                                ControlObjectResult(
                                    object_type="Gate",
                                    node_id=102,
                                    object_id=502,
                                    target_value=0.55,
                                    target_value_type="OPENING",
                                )
                            ],
                        ),
                        HorizonStep(
                            horizon_step=3,
                            control_object_list=[
                                ControlObjectResult(
                                    object_type="Gate",
                                    node_id=103,
                                    object_id=503,
                                    target_value=0.65,
                                    target_value_type="OPENING",
                                )
                            ],
                        ),
                    ],
                )
            ],
        )

        with self.assertLogs("hydros_agent_sdk.coordination_client", level="INFO") as logs:
            client._send_with_retry(report)

        client.mqtt_client.publish.assert_called_once()
        publish_result.wait_for_publish.assert_called_once()
        log_output = "\n".join(logs.output)
        self.assertIn("MPC result report sent to coordinator", log_output)
        self.assertIn(report.command_id, log_output)
        self.assertIn("result_count=1", log_output)
        self.assertIn("detail_count=3", log_output)
        self.assertNotIn('"command_type":"mpc_result_report"', log_output)
        self.assertNotIn('"object_id":501', log_output)
        self.assertNotIn('"object_id":502', log_output)
        self.assertNotIn('"object_id":503', log_output)

    def test_coordination_client_truncates_mpc_result_report_when_enqueued(self):
        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        context = SimulationContext(biz_scene_instance_id="scene-016-enqueue-log")
        source = build_agent_instance("agent-016-enqueue-log", "CENTRAL_SCHEDULING_AGENT", "node-a", context)
        state_manager.add_local_agent(source)
        client = SimCoordinationClient(
            broker_url="tcp://127.0.0.1",
            broker_port=1883,
            hydros_cluster_id="demo-cluster",
            sim_coordination_callback=TestSiblingCacheCallback(),
            state_manager=state_manager,
        )
        report = MpcResultReporter().build_report(
            source,
            MpcTaskState(
                context=context,
                rolling_interval_steps=3,
                start_step=1,
                current_step=4,
            ),
            [
                MpcOptimizeResponse(
                    plan_type="OPTIMAL",
                    horizon_controls=[
                        HorizonStep(
                            horizon_step=1,
                            control_object_list=[
                                ControlObjectResult(
                                    object_type="Gate",
                                    node_id=101,
                                    object_id=501,
                                    target_value=0.45,
                                    target_value_type="OPENING",
                                )
                            ],
                        ),
                        HorizonStep(
                            horizon_step=2,
                            control_object_list=[
                                ControlObjectResult(
                                    object_type="Gate",
                                    node_id=102,
                                    object_id=502,
                                    target_value=0.55,
                                    target_value_type="OPENING",
                                )
                            ],
                        ),
                        HorizonStep(
                            horizon_step=3,
                            control_object_list=[
                                ControlObjectResult(
                                    object_type="Gate",
                                    node_id=103,
                                    object_id=503,
                                    target_value=0.65,
                                    target_value_type="OPENING",
                                )
                            ],
                        ),
                    ],
                )
            ],
        )

        with self.assertLogs("hydros_agent_sdk.coordination_client", level="INFO") as logs:
            client.enqueue(report)

        log_output = "\n".join(logs.output)
        self.assertIn("Enqueued command", log_output)
        self.assertIn('"command_type":"mpc_result_report"', log_output)
        self.assertIn('"result_count":1', log_output)
        self.assertIn('"detail_count":3', log_output)
        self.assertNotIn('"object_id":501', log_output)
        self.assertNotIn('"object_id":502', log_output)
        self.assertNotIn('"object_id":503', log_output)

    def test_central_scheduling_agent_generates_java_style_command_id(self):
        with patch("hydros_agent_sdk.utils.id_generator.datetime") as mock_datetime, \
             patch("hydros_agent_sdk.utils.id_generator.choice", return_value="A"):
            mock_now = Mock()
            mock_now.strftime.return_value = "202601011230"
            mock_datetime.now.return_value = mock_now

            command_id = generate_agent_command_id()

        self.assertEqual(command_id, "AGTCMD202601011230AAAAAAAAAAAA")
        self.assertTrue(command_id.startswith("AGTCMD"))
        self.assertEqual(len(command_id), 30)

    def test_sibling_agent_cache_is_available_to_central_scheduling_agent(self):
        callback = TestSiblingCacheCallback()

        context = SimulationContext(biz_scene_instance_id="scene-005")
        sibling = build_agent_instance("agent-005", "SOURCE_AGENT", "node-a", context)
        response = SimTaskInitResponse(
            command_id="init-005",
            context=context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=sibling,
            created_agent_instances=[sibling],
            managed_top_objects={
                sibling.agent_id: [
                    TopHydroObject(
                        object_id=20600,
                        object_name="Gate Station 20600",
                        object_type="GateStation",
                        children=[
                            {"object_id": 20601, "object_name": "Gate 20601", "object_type": "Gate"},
                            {"object_id": 20602, "object_name": "Gate 20602", "object_type": "Gate"},
                        ],
                    )
                ]
            },
        )

        callback.on_agent_instance_sibling_created(response)
        self.assertIsNone(callback.get_sibling_agent_instance("agent-005"))
        self.assertIs(callback.get_sibling_agent_instance("SOURCE_AGENT"), sibling)
        self.assertIsNone(callback.get_sibling_agent_instance("agent-005", biz_scene_instance_id="other-scene"))
        self.assertIs(callback.get_agent_by_object_id(20600, biz_scene_instance_id="scene-005"), sibling)
        self.assertIs(callback.get_agent_by_object_id(20601, biz_scene_instance_id="scene-005"), sibling)
        self.assertIs(callback.get_agent_by_object_id(20602), sibling)
        self.assertIsNone(callback.get_agent_by_object_id(20601, biz_scene_instance_id="other-scene"))

        state_manager = AgentStateManager()
        state_manager.set_node_id("node-a")
        state_manager.set_cluster_id("demo-cluster")
        sim_client = SimpleNamespace(
            broker_url="127.0.0.1",
            broker_port=1883,
            topic="/hydros/commands/coordination/demo-cluster",
            state_manager=state_manager,
            mqtt_client=Mock(),
            sim_coordination_callback=callback,
        )

        agent = CentralSchedulingAgentForTest(
            sim_coordination_client=sim_client,
            agent_id="agent-006",
            agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id="demo-cluster",
            hydros_node_id="node-a",
        )

        self.assertIs(agent._target_agent_resolver.get_sibling_agent_instance("SOURCE_AGENT"), sibling)

        terminate_request = SimTaskTerminateRequest(command_id="term-005", context=context)
        callback.on_task_terminate(terminate_request)
        self.assertIsNone(callback.get_sibling_agent_instance("agent-005"))
        self.assertIsNone(callback.get_agent_by_object_id(20601))


if __name__ == "__main__":
    unittest.main()
