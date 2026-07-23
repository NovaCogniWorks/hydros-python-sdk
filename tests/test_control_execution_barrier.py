from threading import Event, Thread
from unittest.mock import Mock

from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.protocol.agent_commands import (
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.protocol.commands import EdgeControlExecutionReport
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    CommandStatus,
    HydroAgentInstance,
    SimulationContext,
)


class GenericCentralForTest(CentralSchedulingAgent):
    def on_init(self, request):
        return None

    def on_terminate(self, request):
        return None


def _build_agent(agent_id: str, context: SimulationContext) -> HydroAgentInstance:
    return HydroAgentInstance(
        agent_id=agent_id,
        agent_code=agent_id,
        agent_type="STATION_AGENT",
        agent_name=agent_id,
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster-a",
        hydros_node_id="node-a",
        context=context,
        drive_mode=AgentDriveMode.PROACTIVE,
    )


def _build_central_and_command():
    context = SimulationContext(biz_scene_instance_id="scene-generic-terminal-barrier")
    client = Mock(state_manager=Mock(), transport=Mock())
    central = GenericCentralForTest(
        sim_coordination_client=client,
        agent_id="central",
        agent_code="CENTRAL_SCHEDULING_AGENT",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Central",
        context=context,
        hydros_cluster_id="cluster-a",
        hydros_node_id="node-a",
        control_execution_timeout_seconds=1,
    )
    target = _build_agent("station", context)
    command = HydroStationTargetValueRequest(
        command_id="AGTCMD_GENERIC_BARRIER",
        context=context,
        source=central,
        target=target,
        object_id=101,
        object_type="PumpStation",
        target_value=36.0,
        target_value_type="water_flow",
        group_id="pump-station-flow:8",
        group_size=1,
        main_step_index=8,
    )
    return context, central, target, command


def test_generic_central_waits_for_edge_terminal_report_not_acceptance_response():
    context, central, target, command = _build_central_and_command()
    command_dispatched = Event()
    tick_completed = Event()
    failure = []

    def send_command(dispatched_command):
        assert dispatched_command is command
        central._handle_control_command_response(
            HydroStationTargetValueResponse.from_request(
                command,
                command_status=CommandStatus.SUCCEED,
                success=True,
            )
        )
        command_dispatched.set()

    central._control_command_dispatcher.send_command = send_command

    def run_dispatch():
        try:
            central.dispatch_control_commands_and_await_execution([command])
        except Exception as error:  # pragma: no cover - asserted below
            failure.append(error)
        finally:
            tick_completed.set()

    worker = Thread(target=run_dispatch)
    worker.start()
    assert command_dispatched.wait(0.2)
    assert not tick_completed.is_set(), "accepted response must not complete the tick"

    central.on_station_control_execution(
        EdgeControlExecutionReport(
            command_id="SIMCMD_EDGE_GENERIC_TERMINAL",
            context=context,
            broadcast=True,
            source_agent_instance=target,
            target_agent_instance=central,
            exec_command_id=command.command_id,
            object_type=command.object_type,
            object_id=command.object_id,
            target_value_type=command.target_value_type,
            target_value=command.target_value,
            exec_status="COMPLETED",
        )
    )

    worker.join(timeout=0.2)
    assert not worker.is_alive()
    assert not failure
    assert tick_completed.is_set()


def test_generic_central_fails_after_edge_terminal_failure():
    context, central, target, command = _build_central_and_command()

    def send_command(dispatched_command):
        central.on_station_control_execution(
            EdgeControlExecutionReport(
                command_id="SIMCMD_EDGE_GENERIC_FAILED",
                context=context,
                broadcast=True,
                source_agent_instance=target,
                target_agent_instance=central,
                exec_command_id=dispatched_command.command_id,
                object_type=dispatched_command.object_type,
                object_id=dispatched_command.object_id,
                target_value_type=dispatched_command.target_value_type,
                target_value=dispatched_command.target_value,
                exec_status="FAILED",
                error_code="EDGE_CONTROL_FAILED",
                error_message="compute step failed",
            )
        )

    central._control_command_dispatcher.send_command = send_command

    try:
        central.dispatch_control_commands_and_await_execution([command])
    except RuntimeError as error:
        assert "EDGE_CONTROL_FAILED" in str(error)
    else:
        raise AssertionError("edge terminal failure must fail the current tick")
