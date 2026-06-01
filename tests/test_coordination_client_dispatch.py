from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.protocol.commands import (
    HydroEventAckResponse,
    HydroEventCommand,
    OutflowTimeSeriesResponse,
    SimTaskTerminateResponse,
    SimCommandEnvelope,
    TickCmdRequest,
    TickCmdResponse,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.events import OutflowTimeSeriesEvent, TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    AgentDriveMode,
    CommandStatus,
    HydroAgentInstance,
    ObjectTimeSeries,
    SimulationContext,
    TimeSeriesValue,
)
from hydros_agent_sdk.state_manager import AgentStateManager


def make_context():
    return SimulationContext(biz_scene_instance_id="TASK_001")


def make_agent(context):
    return HydroAgentInstance(
        agent_code="TEST_AGENT",
        agent_type="TEST_AGENT",
        agent_name="Test Agent",
        agent_configuration_url="",
        agent_id="AGT_TEST",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )


class ReturningCallback(SimCoordinationCallback):
    def __init__(self, agent):
        self.agent = agent

    def get_component(self) -> str:
        return "TEST_AGENT"

    def on_sim_task_init(self, request):
        return None

    def on_tick(self, request):
        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.agent,
            broadcast=False,
        )


class RaisingCallback(ReturningCallback):
    def on_tick(self, request):
        raise RuntimeError("boom")


class HydroEventCallback(ReturningCallback):
    def __init__(self, agent):
        super().__init__(agent)
        self.time_series_updates = []
        self.outflow_requests = []

    def on_time_series_data_update(self, request):
        self.time_series_updates.append(request)
        return TimeSeriesDataUpdateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.agent,
            broadcast=False,
        )

    def on_outflow_time_series(self, request):
        self.outflow_requests.append(request)
        return OutflowTimeSeriesResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.agent,
            broadcast=False,
            hydro_event=request.hydro_event,
            outflow_time_series_map={},
        )


def make_client(callback, state_manager):
    return SimCoordinationClient(
        broker_url="tcp://localhost",
        broker_port=1883,
        topic="/hydros/commands/coordination/test",
        sim_coordination_callback=callback,
        state_manager=state_manager,
    )


def test_callback_returned_response_is_enqueued():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    client = make_client(ReturningCallback(agent), state_manager)

    request = TickCmdRequest(command_id="CMD_TICK", context=context, step=1)
    client._handle_incoming_message(request)

    response = client.out_message_queue.get_nowait()
    assert isinstance(response, TickCmdResponse)
    assert response.command_status == CommandStatus.SUCCEED
    assert response.command_id == "CMD_TICK"


def test_handler_exception_becomes_failed_response_when_agent_context_exists():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    client = make_client(RaisingCallback(agent), state_manager)

    request = TickCmdRequest(command_id="CMD_TICK", context=context, step=1)
    client._handle_incoming_message(request)

    response = client.out_message_queue.get_nowait()
    assert isinstance(response, TickCmdResponse)
    assert response.command_status == CommandStatus.FAILED
    assert response.error_code == "AGENT_TICK_FAILURE"
    assert "boom" in response.error_message


def test_terminate_response_from_same_node_is_sendable_after_local_agent_removed():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    client = make_client(ReturningCallback(agent), state_manager)

    response = SimTaskTerminateResponse(
        command_id="CMD_TERM",
        context=context,
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=agent,
        broadcast=False,
    )

    assert client._should_send(response) is True


def test_hydro_event_command_routes_time_series_payload_and_returns_ack():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    callback = HydroEventCallback(agent)
    client = make_client(callback, state_manager)

    event = TimeSeriesDataChangedEvent(
        hydro_event_type="TIME_SERIES_DATA_UPDATED",
        object_time_series=[
            ObjectTimeSeries(
                object_id=1001,
                object_type="Gate",
                metrics_code="gate_opening",
                time_series=[TimeSeriesValue(step=1, value=1.2)],
            )
        ],
    )
    request = HydroEventCommand(
        command_id="CMD_EVENT",
        context=context,
        broadcast=True,
        payload=event,
    )

    client._handle_incoming_message(request)

    assert len(callback.time_series_updates) == 1
    forwarded = callback.time_series_updates[0]
    assert forwarded.command_id == "CMD_EVENT"
    assert forwarded.time_series_data_changed_event.object_time_series[0].object_id == 1001

    response = client.out_message_queue.get_nowait()
    assert isinstance(response, HydroEventAckResponse)
    assert response.command_type == "hydro_event_ack_response"
    assert response.command_id == "CMD_EVENT"
    assert response.command_status == CommandStatus.SUCCEED


def test_hydro_event_command_routes_outflow_event_to_outflow_plan_path():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    callback = HydroEventCallback(agent)
    client = make_client(callback, state_manager)

    event = OutflowTimeSeriesEvent(
        hydro_event_type="OUTFLOW_TIME_SERIES",
        event_content_url="https://example.test/outflow.yaml",
    )
    request = HydroEventCommand(
        command_id="CMD_OUTFLOW",
        context=context,
        broadcast=False,
        target_agent_instance=agent,
        payload=event,
    )

    client._handle_incoming_message(request)

    assert len(callback.outflow_requests) == 1
    forwarded = callback.outflow_requests[0]
    assert forwarded.command_id == "CMD_OUTFLOW"
    assert forwarded.target_agent_instance.agent_id == agent.agent_id
    assert forwarded.hydro_event.event_content_url == "https://example.test/outflow.yaml"

    response = client.out_message_queue.get_nowait()
    assert isinstance(response, OutflowTimeSeriesResponse)
    assert response.command_type == "outflow_time_series_response"
    assert response.command_id == "CMD_OUTFLOW"
    assert response.command_status == CommandStatus.SUCCEED


def test_hydro_event_command_can_be_deserialized_from_java_payload_shape():
    context = make_context()
    envelope = SimCommandEnvelope(
        command={
            "command_id": "CMD_EVENT_JSON",
            "command_type": "hydro_event_command",
            "context": context.model_dump(mode="json"),
            "broadcast": True,
            "target_agent_instance": None,
            "payload": {
                "hydro_event_type": "TIME_SERIES_DATA_UPDATED",
                "object_time_series": [
                    {
                        "object_id": 1001,
                        "object_type": "Gate",
                        "metrics_code": "gate_opening",
                        "time_series": [{"step": 1, "value": 1.2}],
                    }
                ],
            },
        }
    )

    assert isinstance(envelope.command, HydroEventCommand)
    assert isinstance(envelope.command.payload, TimeSeriesDataChangedEvent)
    assert envelope.command.payload.object_time_series[0].object_id == 1001


def test_hydro_event_command_can_be_deserialized_from_java_outflow_payload_shape():
    context = make_context()
    agent = make_agent(context)
    envelope = SimCommandEnvelope(
        command={
            "command_id": "CMD_OUTFLOW_JSON",
            "command_type": "hydro_event_command",
            "context": context.model_dump(mode="json"),
            "broadcast": False,
            "target_agent_instance": agent.model_dump(mode="json"),
            "payload": {
                "hydro_event_type": "OUTFLOW_TIME_SERIES",
                "eventContentUrl": "https://example.test/outflow.yaml",
            },
        }
    )

    assert isinstance(envelope.command, HydroEventCommand)
    assert isinstance(envelope.command.payload, OutflowTimeSeriesEvent)
    assert envelope.command.payload.event_content_url == "https://example.test/outflow.yaml"
