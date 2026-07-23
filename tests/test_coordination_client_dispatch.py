import json
import time
from queue import Queue
from threading import Event
from types import SimpleNamespace

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.multi_agent import MultiAgentCallback
from hydros_agent_sdk.protocol.commands import (
    EdgeControlExecutionReport,
    HydroEventAckResponse,
    HydroEventCommand,
    OutflowTimeSeriesResponse,
    OutflowTimeSeriesDataUpdateResponse,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    SimCommandEnvelope,
    TickCmdRequest,
    TickCmdResponse,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.events import (
    OutflowTimeSeriesDataChangedEvent,
    OutflowTimeSeriesEvent,
    TimeSeriesDataChangedEvent,
)
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
from hydros_agent_sdk.transport.in_memory import InMemoryTransport


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
            completed_step=request.step,
            broadcast=False,
        )


class RaisingCallback(ReturningCallback):
    def on_tick(self, request):
        raise RuntimeError("boom")


class HydroEventCallback(ReturningCallback):
    def __init__(self, agent):
        super().__init__(agent)
        self.time_series_updates = []
        self.outflow_data_updates = []
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

    def on_outflow_time_series_data_update(self, request):
        self.outflow_data_updates.append(request)
        return OutflowTimeSeriesDataUpdateResponse(
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


class BlockingTickCallback(ReturningCallback):
    def __init__(self, agent):
        super().__init__(agent)
        self.tick_started = Event()
        self.tick_release = Event()
        self.tick_finished = Event()

    def on_tick(self, request):
        self.tick_started.set()
        self.tick_release.wait(timeout=5)
        self.tick_finished.set()
        return super().on_tick(request)


class CompletionWaitingCallback(ReturningCallback):
    def __init__(self, agent, state_manager):
        super().__init__(agent)
        self.state_manager = state_manager
        self.first_tick_started = Event()
        self.second_tick_started = Event()
        self.completion_received = Event()

    def is_remote_agent(self, agent_instance) -> bool:
        return self.state_manager.is_remote_agent(agent_instance)

    def on_tick(self, request):
        if request.step == 1:
            self.first_tick_started.set()
            if not self.completion_received.wait(timeout=5):
                raise RuntimeError("completion signal was blocked by the task command mailbox")
        else:
            self.second_tick_started.set()
        return super().on_tick(request)

    def on_station_control_execution(self, report):
        self.completion_received.set()


class BlockingTickAndInitCallback(BlockingTickCallback):
    def __init__(self, agent):
        super().__init__(agent)
        self.init_handled = Event()

    def on_sim_task_init(self, request):
        init_agent = make_agent(request.context)
        self.init_handled.set()
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=init_agent,
            created_agent_instances=[init_agent],
            managed_top_objects={},
            broadcast=False,
        )


class FailingInitCallback(ReturningCallback):
    def __init__(self, agent):
        super().__init__(agent)
        self.init_handled = Event()

    def on_sim_task_init(self, request):
        self.init_handled.set()
        raise RuntimeError("init failed")


class TaskIsolatedBlockingCallback(ReturningCallback):
    def __init__(self, agents_by_context, blocked_context_id):
        first_agent = next(iter(agents_by_context.values()))
        super().__init__(first_agent)
        self.agents_by_context = agents_by_context
        self.blocked_context_id = blocked_context_id
        self.blocked_tick_started = Event()
        self.blocked_tick_release = Event()
        self.fast_tick_handled = Event()

    def on_tick(self, request):
        context_id = request.context.biz_scene_instance_id
        if context_id == self.blocked_context_id:
            self.blocked_tick_started.set()
            self.blocked_tick_release.wait(timeout=5)
        else:
            self.fast_tick_handled.set()

        agent = self.agents_by_context[context_id]
        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=agent,
            completed_step=request.step,
            broadcast=False,
        )


class LifecycleCallback(SimCoordinationCallback):
    def __init__(self, state_manager):
        self.state_manager = state_manager

    def get_component(self) -> str:
        return "TEST_AGENT"

    def on_sim_task_init(self, request):
        agent = make_agent(request.context).model_copy(
            update={"agent_id": f"AGT_{request.context.biz_scene_instance_id}"}
        )
        self.state_manager.activate_task(request.context, [agent])
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=agent,
            created_agent_instances=[agent],
            managed_top_objects={},
            broadcast=False,
        )

    def on_tick(self, request):
        return None

    def on_task_terminate(self, request):
        self.state_manager.terminate_task(request.context)
        return []


def make_client(callback, state_manager):
    return SimCoordinationClient(
        broker_url="tcp://localhost",
        broker_port=1883,
        topic="/hydros/commands/coordination/test",
        sim_coordination_callback=callback,
        state_manager=state_manager,
        transport=InMemoryTransport(),
    )


def task_runtime(client, context):
    return client._task_runtime_registry.get_or_create(context.biz_scene_instance_id)


def start_inbound_workers(client, *contexts):
    for context in contexts:
        task_runtime(client, context)
    client._task_runtime_registry.start()
    client.transport.start()


def stop_inbound_workers(client):
    client._task_runtime_registry.stop()
    client.transport.stop()


def deliver_raw_command(client, command):
    client.transport.deliver(
        "/hydros/commands/coordination/test",
        command.model_dump_json(by_alias=True),
    )


def capture_outbound(client):
    responses = Queue()
    client._task_runtime_registry.outbound_submitter = responses.put
    return responses


def test_callback_returned_response_is_enqueued():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    client = make_client(ReturningCallback(agent), state_manager)
    outbound = capture_outbound(client)

    request = TickCmdRequest(command_id="CMD_TICK", context=context, step=1)
    runtime = task_runtime(client, context)
    runtime.handle(request)

    response = outbound.get_nowait()
    assert isinstance(response, TickCmdResponse)
    assert response.command_status == CommandStatus.SUCCEED
    assert response.command_id == "CMD_TICK"
    assert runtime.router.handlers


def test_client_does_not_expose_paho_or_transport_callback_internals():
    client = make_client(ReturningCallback(make_agent(make_context())), AgentStateManager())

    for legacy_name in (
        "mqtt_client",
        "connected",
        "publish",
        "_on_connect",
        "_on_disconnect",
        "_on_message",
        "out_message_queue",
        "queue_thread",
        "send_command",
        "task_runtime",
        "task_runtimes",
    ):
        assert not hasattr(client, legacy_name)


def test_remote_init_response_is_cached_while_local_task_is_initializing():
    context = make_context()
    state_manager = AgentStateManager()
    state_manager.set_node_id("central-node")
    callback = MultiAgentCallback()
    client = make_client(callback, state_manager)
    callback.set_client(client)
    state_manager.begin_task_initialization(context)

    gate_agent = HydroAgentInstance(
        agent_code="GATE_STATION_AGENT",
        agent_type="GATE_STATION_AGENT",
        agent_name="Gate Station Agent",
        agent_configuration_url="",
        agent_id="AGT_GATE",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster",
        hydros_node_id="edge-node",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )
    response = SimTaskInitResponse(
        command_id="CMD_EDGE_INIT",
        context=context,
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=gate_agent,
        created_agent_instances=[gate_agent],
        managed_top_objects={},
        broadcast=True,
    )

    start_inbound_workers(client, context)
    try:
        deliver_raw_command(client, response)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            cached_agent = callback.get_sibling_agent_instance(
                "GATE_STATION_AGENT",
                biz_scene_instance_id=context.biz_scene_instance_id,
            )
            if cached_agent is not None and cached_agent.agent_id == gate_agent.agent_id:
                break
            time.sleep(0.01)

        cached_gate_agent = callback.get_sibling_agent_instance(
            "GATE_STATION_AGENT",
            biz_scene_instance_id=context.biz_scene_instance_id,
        )
        assert cached_gate_agent is not None
        assert cached_gate_agent.agent_id == gate_agent.agent_id
        assert cached_gate_agent.agent_code == gate_agent.agent_code
        assert client.message_filter.should_process_message(
            TickCmdRequest(command_id="CMD_EARLY_TICK", context=context, step=1)
        ) is False
    finally:
        stop_inbound_workers(client)


def test_handler_exception_becomes_failed_response_when_agent_context_exists():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    client = make_client(RaisingCallback(agent), state_manager)
    outbound = capture_outbound(client)

    request = TickCmdRequest(command_id="CMD_TICK", context=context, step=1)
    task_runtime(client, context).handle(request)

    response = outbound.get_nowait()
    assert isinstance(response, TickCmdResponse)
    assert response.command_status == CommandStatus.FAILED
    assert response.error_code == "AGENT_TICK_FAILURE"
    assert "boom" in response.error_message


def test_transport_payload_is_enqueued_and_returns_before_slow_tick_finishes():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    callback = BlockingTickCallback(agent)
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)
    start_inbound_workers(client, context)

    try:
        request = TickCmdRequest(command_id="CMD_SLOW_TICK", context=context, step=1)
        started_at = time.monotonic()
        deliver_raw_command(client, request)
        elapsed_ms = (time.monotonic() - started_at) * 1000

        assert elapsed_ms < 200
        assert callback.tick_started.wait(timeout=1)
        assert outbound.empty()

        callback.tick_release.set()
        response = outbound.get(timeout=1)
        assert callback.tick_finished.is_set()
        assert isinstance(response, TickCmdResponse)
        assert response.command_id == "CMD_SLOW_TICK"
    finally:
        callback.tick_release.set()
        stop_inbound_workers(client)


def test_edge_completion_bypasses_blocked_task_command_mailbox():
    context = make_context()
    local_agent = make_agent(context)
    remote_agent = make_agent(context).model_copy(
        update={
            "agent_id": "AGT_EDGE",
            "agent_code": "EDGE_AGENT",
            "hydros_node_id": "edge-node",
        }
    )
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [local_agent])
    callback = CompletionWaitingCallback(local_agent, state_manager)
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)
    start_inbound_workers(client, context)

    try:
        deliver_raw_command(
            client,
            TickCmdRequest(command_id="CMD_WAITING_TICK", context=context, step=1),
        )
        assert callback.first_tick_started.wait(timeout=1)

        deliver_raw_command(
            client,
            TickCmdRequest(command_id="CMD_QUEUED_TICK", context=context, step=2),
        )
        assert not callback.second_tick_started.wait(timeout=0.1)

        deliver_raw_command(
            client,
            EdgeControlExecutionReport(
                command_id="CMD_EDGE_COMPLETION",
                context=context,
                broadcast=True,
                source_agent_instance=remote_agent,
                target_agent_instance=local_agent,
                exec_command_id="AGTCMD_WAITING_CONTROL",
                object_type="GateStation",
                object_id=101,
                target_value_type="water_level",
                target_value=3.5,
                exec_status="COMPLETED",
            ),
        )

        assert callback.completion_received.wait(timeout=1)
        first_response = outbound.get(timeout=1)
        second_response = outbound.get(timeout=1)
        assert first_response.command_id == "CMD_WAITING_TICK"
        assert first_response.command_status == CommandStatus.SUCCEED
        assert second_response.command_id == "CMD_QUEUED_TICK"
        assert second_response.command_status == CommandStatus.SUCCEED
        assert callback.second_tick_started.is_set()
    finally:
        callback.completion_received.set()
        stop_inbound_workers(client)


def test_task_init_is_processed_while_business_tick_is_blocked():
    old_context = make_context()
    new_context = SimulationContext(biz_scene_instance_id="TASK_NEW")
    agent = make_agent(old_context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(old_context, [agent])
    callback = BlockingTickAndInitCallback(agent)
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)
    start_inbound_workers(client, old_context)

    try:
        tick_request = TickCmdRequest(command_id="CMD_BLOCKING_TICK", context=old_context, step=1)
        deliver_raw_command(client, tick_request)
        assert callback.tick_started.wait(timeout=1)

        init_request = SimTaskInitRequest(
            command_id="CMD_INIT_NEW",
            context=new_context,
            agent_list=[],
        )
        deliver_raw_command(client, init_request)

        assert callback.init_handled.wait(timeout=1)
        init_response = outbound.get(timeout=1)
        assert isinstance(init_response, SimTaskInitResponse)
        assert init_response.command_id == "CMD_INIT_NEW"

        callback.tick_release.set()
        tick_response = outbound.get(timeout=1)
        assert isinstance(tick_response, TickCmdResponse)
        assert tick_response.command_id == "CMD_BLOCKING_TICK"
    finally:
        callback.tick_release.set()
        stop_inbound_workers(client)


def test_business_commands_are_isolated_by_task_context():
    slow_context = make_context()
    fast_context = SimulationContext(biz_scene_instance_id="TASK_FAST")
    slow_agent = make_agent(slow_context)
    fast_agent = make_agent(fast_context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    for context, agent in ((slow_context, slow_agent), (fast_context, fast_agent)):
        state_manager.activate_task(context, [agent])

    callback = TaskIsolatedBlockingCallback(
        {
            slow_context.biz_scene_instance_id: slow_agent,
            fast_context.biz_scene_instance_id: fast_agent,
        },
        blocked_context_id=slow_context.biz_scene_instance_id,
    )
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)
    start_inbound_workers(client, slow_context, fast_context)

    try:
        slow_tick = TickCmdRequest(command_id="CMD_SLOW_TASK_TICK", context=slow_context, step=1)
        fast_tick = TickCmdRequest(command_id="CMD_FAST_TASK_TICK", context=fast_context, step=1)
        deliver_raw_command(client, slow_tick)
        assert callback.blocked_tick_started.wait(timeout=1)

        deliver_raw_command(client, fast_tick)

        assert callback.fast_tick_handled.wait(timeout=1)
        fast_response = outbound.get(timeout=1)
        assert isinstance(fast_response, TickCmdResponse)
        assert fast_response.command_id == "CMD_FAST_TASK_TICK"

        callback.blocked_tick_release.set()
        slow_response = outbound.get(timeout=1)
        assert isinstance(slow_response, TickCmdResponse)
        assert slow_response.command_id == "CMD_SLOW_TASK_TICK"
    finally:
        callback.blocked_tick_release.set()
        stop_inbound_workers(client)


def test_registry_creates_distinct_runtimes_and_releases_terminated_task():
    first_context = make_context()
    second_context = SimulationContext(biz_scene_instance_id="TASK_002")
    state_manager = AgentStateManager()
    callback = LifecycleCallback(state_manager)
    client = make_client(callback, state_manager)
    capture_outbound(client)
    start_inbound_workers(client)

    try:
        for context in (first_context, second_context):
            deliver_raw_command(
                client,
                SimTaskInitRequest(
                    command_id=f"CMD_INIT_{context.biz_scene_instance_id}",
                    context=context,
                    agent_list=[],
                ),
            )

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if all(
                state_manager.has_active_context(context)
                for context in (first_context, second_context)
            ):
                break
            time.sleep(0.01)

        assert client._task_runtime_registry.context_ids() == {"TASK_001", "TASK_002"}
        first_runtime = client._task_runtime_registry.get("TASK_001")
        second_runtime = client._task_runtime_registry.get("TASK_002")
        assert first_runtime is not None
        assert second_runtime is not None
        assert first_runtime is not second_runtime
        assert first_runtime.context_id == "TASK_001"
        assert second_runtime.context_id == "TASK_002"

        deliver_raw_command(
            client,
            SimTaskTerminateRequest(
                command_id="CMD_TERMINATE_TASK_001",
                context=first_context,
            ),
        )
        deadline = time.monotonic() + 1
        while (
            time.monotonic() < deadline
            and client._task_runtime_registry.get("TASK_001") is not None
        ):
            time.sleep(0.01)

        assert client._task_runtime_registry.get("TASK_001") is None
        assert client._task_runtime_registry.get("TASK_002") is second_runtime
    finally:
        stop_inbound_workers(client)


def test_registry_releases_runtime_when_init_creates_no_active_task():
    context = make_context()
    state_manager = AgentStateManager()
    callback = BlockingTickAndInitCallback(make_agent(context))
    client = make_client(callback, state_manager)
    capture_outbound(client)
    start_inbound_workers(client)

    try:
        deliver_raw_command(
            client,
            SimTaskInitRequest(
                command_id="CMD_INIT_WITHOUT_ACTIVE_TASK",
                context=context,
                agent_list=[],
            ),
        )
        assert callback.init_handled.wait(timeout=1)

        deadline = time.monotonic() + 1
        while (
            time.monotonic() < deadline
            and client._task_runtime_registry.get("TASK_001") is not None
        ):
            time.sleep(0.01)

        assert client._task_runtime_registry.get("TASK_001") is None
    finally:
        stop_inbound_workers(client)


def test_registry_releases_runtime_when_init_fails():
    context = make_context()
    state_manager = AgentStateManager()
    callback = FailingInitCallback(make_agent(context))
    client = make_client(callback, state_manager)
    capture_outbound(client)
    start_inbound_workers(client)

    try:
        deliver_raw_command(
            client,
            SimTaskInitRequest(
                command_id="CMD_FAILED_INIT",
                context=context,
                agent_list=[],
            ),
        )
        assert callback.init_handled.wait(timeout=1)

        deadline = time.monotonic() + 1
        while (
            time.monotonic() < deadline
            and client._task_runtime_registry.get("TASK_001") is not None
        ):
            time.sleep(0.01)

        assert client._task_runtime_registry.get("TASK_001") is None
    finally:
        stop_inbound_workers(client)


def test_monitor_rule_update_messages_are_ignored_before_envelope_parsing():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    client = make_client(ReturningCallback(agent), state_manager)
    client._task_runtime_registry.enqueue = _fail_if_called
    client.transport.start()

    try:
        for command_type, agent_field in (
            ("update_monitor_rule_request", "target_agent_instance"),
            ("update_monitor_rule_response", "source_agent_instance"),
        ):
            payload = {
                "command_id": "CMD_MONITOR_RULE",
                "command_type": command_type,
                "context": context.model_dump(mode="json"),
                agent_field: agent.model_dump(mode="json", by_alias=True),
                "monitoring_rules": [
                    {
                        "ruleId": "MRULE_001",
                        "ruleName": "Water level warning",
                        "bizStatus": "NORMAL",
                        "triggerConditions": {},
                    }
                ],
            }

            client.transport.deliver(
                "/hydros/commands/coordination/test",
                json.dumps(payload),
            )
    finally:
        client.transport.stop()

    assert not hasattr(client, "out_message_queue")


def test_station_control_execution_report_is_ignored_before_envelope_parsing():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    client = make_client(ReturningCallback(agent), state_manager)
    client._handle_incoming_message = _fail_if_called

    payload = {
        "command_id": "CMD_STATION_CONTROL_REPORT",
        "command_type": "station_control_execution_report",
        "context": context.model_dump(mode="json"),
        "source_agent_instance": agent.model_dump(mode="json", by_alias=True),
        "command_status": CommandStatus.SUCCEED.value,
        "execution_results": [],
    }

    client._on_message(
        None,
        None,
        SimpleNamespace(
            topic="/hydros/commands/coordination/test",
            payload=json.dumps(payload).encode("utf-8"),
        ),
    )

    assert client.out_message_queue.empty()


def test_edge_control_execution_report_is_ignored_before_envelope_parsing():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.init_task(context, [agent])
    state_manager.add_local_agent(agent)
    client = make_client(ReturningCallback(agent), state_manager)
    client._handle_incoming_message = _fail_if_called

    payload = {
        "command_id": "CMD_EDGE_CONTROL_REPORT",
        "command_type": "edge_control_execution_report",
        "context": context.model_dump(mode="json"),
        "source_agent_instance": agent.model_dump(mode="json", by_alias=True),
        "command_status": CommandStatus.SUCCEED.value,
        "execution_results": [],
    }

    client._on_message(
        None,
        None,
        SimpleNamespace(
            topic="/hydros/commands/coordination/test",
            payload=json.dumps(payload).encode("utf-8"),
        ),
    )

    assert client.out_message_queue.empty()


def _fail_if_called(command):
    raise AssertionError(f"ignored command reached handler: {command.command_type}")


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

    assert client.outbox_publisher.should_send(response) is True


def test_hydro_event_command_routes_time_series_payload_and_returns_ack():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    callback = HydroEventCallback(agent)
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)

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

    task_runtime(client, context).handle(request)

    assert len(callback.time_series_updates) == 1
    forwarded = callback.time_series_updates[0]
    assert forwarded.command_id == "CMD_EVENT"
    assert forwarded.time_series_data_changed_event.object_time_series[0].object_id == 1001

    response = outbound.get_nowait()
    assert isinstance(response, HydroEventAckResponse)
    assert response.command_type == "hydro_event_ack_response"
    assert response.command_id == "CMD_EVENT"
    assert response.command_status == CommandStatus.SUCCEED


def test_hydro_event_command_routes_outflow_event_to_outflow_plan_path():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    callback = HydroEventCallback(agent)
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)

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

    task_runtime(client, context).handle(request)

    assert len(callback.outflow_requests) == 1
    forwarded = callback.outflow_requests[0]
    assert forwarded.command_id == "CMD_OUTFLOW"
    assert forwarded.target_agent_instance.agent_id == agent.agent_id
    assert forwarded.hydro_event.event_content_url == "https://example.test/outflow.yaml"

    response = outbound.get_nowait()
    assert isinstance(response, OutflowTimeSeriesResponse)
    assert response.command_type == "outflow_time_series_response"
    assert response.command_id == "CMD_OUTFLOW"
    assert response.command_status == CommandStatus.SUCCEED


def test_hydro_event_command_routes_outflow_event_without_content_url():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    callback = HydroEventCallback(agent)
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)

    event = OutflowTimeSeriesEvent(hydro_event_type="OUTFLOW_TIME_SERIES")
    request = HydroEventCommand(
        command_id="CMD_OUTFLOW_NO_URL",
        context=context,
        broadcast=False,
        target_agent_instance=agent,
        payload=event,
    )

    task_runtime(client, context).handle(request)

    assert len(callback.outflow_requests) == 1
    forwarded = callback.outflow_requests[0]
    assert forwarded.command_id == "CMD_OUTFLOW_NO_URL"
    assert forwarded.hydro_event.event_content_url is None

    response = outbound.get_nowait()
    assert isinstance(response, OutflowTimeSeriesResponse)
    assert response.command_id == "CMD_OUTFLOW_NO_URL"
    assert response.command_status == CommandStatus.SUCCEED


def test_hydro_event_command_routes_outflow_data_updated_payload_and_returns_ack():
    context = make_context()
    agent = make_agent(context)
    state_manager = AgentStateManager()
    state_manager.set_node_id("node")
    state_manager.activate_task(context, [agent])
    callback = HydroEventCallback(agent)
    client = make_client(callback, state_manager)
    outbound = capture_outbound(client)

    event = OutflowTimeSeriesDataChangedEvent(
        hydro_event_type="OUTFLOW_TIME_SERIES_DATA_UPDATED",
        source_agent_code="OUTFLOW_PLAN_AGENT_PUMP",
        object_type="GateStation",
        object_time_series=[
            ObjectTimeSeries(
                object_id=20000,
                object_type="GateStation",
                metrics_code="planned_outflow",
                time_series=[TimeSeriesValue(step=1, value=100.0)],
            )
        ],
    )
    request = HydroEventCommand(
        command_id="CMD_OUTFLOW_UPDATED",
        context=context,
        broadcast=False,
        target_agent_instance=agent,
        payload=event,
    )

    task_runtime(client, context).handle(request)

    assert len(callback.outflow_data_updates) == 1
    forwarded = callback.outflow_data_updates[0]
    assert forwarded.command_id == "CMD_OUTFLOW_UPDATED"
    assert forwarded.outflow_time_series_data_changed_event.source_agent_code == "OUTFLOW_PLAN_AGENT_PUMP"
    assert forwarded.outflow_time_series_data_changed_event.object_type == "GateStation"
    assert forwarded.outflow_time_series_data_changed_event.object_time_series[0].object_id == 20000

    response = outbound.get_nowait()
    assert isinstance(response, HydroEventAckResponse)
    assert response.command_id == "CMD_OUTFLOW_UPDATED"
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


def test_hydro_event_command_can_deserialize_java_outflow_payload_without_content_url():
    context = make_context()
    agent = make_agent(context)
    envelope = SimCommandEnvelope(
        command={
            "command_id": "CMD_OUTFLOW_JSON_NO_URL",
            "command_type": "hydro_event_command",
            "context": context.model_dump(mode="json"),
            "broadcast": False,
            "target_agent_instance": agent.model_dump(mode="json"),
            "payload": {
                "hydro_event_type": "OUTFLOW_TIME_SERIES",
                "hydro_event_id": "EVENT_OUTFLOW",
                "hydro_event_name": "出流规划事件",
            },
        }
    )

    assert isinstance(envelope.command, HydroEventCommand)
    assert isinstance(envelope.command.payload, OutflowTimeSeriesEvent)
    assert envelope.command.payload.event_content_url is None


def test_hydro_event_command_can_deserialize_java_outflow_data_updated_payload_shape():
    context = make_context()
    agent = make_agent(context)
    envelope = SimCommandEnvelope(
        command={
            "command_id": "CMD_OUTFLOW_UPDATED_JSON",
            "command_type": "hydro_event_command",
            "context": context.model_dump(mode="json"),
            "broadcast": False,
            "target_agent_instance": agent.model_dump(mode="json"),
            "payload": {
                "hydro_event_type": "OUTFLOW_TIME_SERIES_DATA_UPDATED",
                "sourceAgentCode": "OUTFLOW_PLAN_AGENT_PUMP",
                "objectType": "GateStation",
                "objectTimeSeries": [
                    {
                        "object_id": 20000,
                        "object_type": "GateStation",
                        "metrics_code": "planned_outflow",
                        "time_series": [{"step": 1, "value": 100.0}],
                    }
                ],
            },
        }
    )

    assert isinstance(envelope.command, HydroEventCommand)
    assert isinstance(envelope.command.payload, OutflowTimeSeriesDataChangedEvent)
    assert envelope.command.payload.source_agent_code == "OUTFLOW_PLAN_AGENT_PUMP"
    assert envelope.command.payload.object_type == "GateStation"
    assert envelope.command.payload.object_time_series[0].object_id == 20000
    assert '"sourceAgentCode":"OUTFLOW_PLAN_AGENT_PUMP"' in envelope.command.model_dump_json(by_alias=True)
