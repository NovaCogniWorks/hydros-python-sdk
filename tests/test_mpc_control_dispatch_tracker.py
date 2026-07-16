from hydros_agent_sdk.mpc.control_dispatch_tracker import (
    MpcControlDispatchTracker,
    MpcControlExecutionError,
)
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


def build_agent(agent_id: str, context: SimulationContext) -> HydroAgentInstance:
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


def build_command():
    context = SimulationContext(biz_scene_instance_id="scene-terminal-barrier")
    source = build_agent("central", context)
    target = build_agent("station", context)
    command = HydroStationTargetValueRequest(
        command_id="AGTCMD_BARRIER",
        context=context,
        source=source,
        target=target,
        object_id=101,
        object_type="GateStation",
        target_value=3.5,
        target_value_type="water_level",
    )
    return context, source, target, command


def test_ack_is_not_terminal_and_edge_report_completes_barrier():
    context, source, target, command = build_command()
    tracker = MpcControlDispatchTracker()
    record = tracker.register(command, context.biz_scene_instance_id, 4, 1)

    transition = tracker.handle_response(
        HydroStationTargetValueResponse.from_request(
            command,
            command_status=CommandStatus.SUCCEED,
            success=True,
        )
    )

    assert transition[1] == "STARTED"
    assert not record.completion.is_set()
    assert record.biz_idem_key == "MPC_DETAIL:4:1:101:101:water_level"
    assert record.dispatch_key == "MPC_CTRL:scene-terminal-barrier:4:1:101:water_level"

    terminal = tracker.handle_execution_report(
        EdgeControlExecutionReport(
            command_id="SIMCMD_EDGE_TERMINAL",
            context=context,
            broadcast=True,
            source_agent_instance=target,
            target_agent_instance=source,
            exec_command_id=command.command_id,
            object_type=command.object_type,
            object_id=command.object_id,
            target_value_type=command.target_value_type,
            target_value=command.target_value,
            exec_status="COMPLETED",
        )
    )

    assert terminal[1] == "COMPLETED"
    tracker.await_all([record], timeout_seconds=0.01)


def test_ack_failure_terminates_barrier_as_failed():
    context, _source, _target, command = build_command()
    tracker = MpcControlDispatchTracker()
    record = tracker.register(command, context.biz_scene_instance_id, 4, 1)

    tracker.handle_response(
        HydroStationTargetValueResponse.from_request(
            command,
            command_status=CommandStatus.FAILED,
            success=False,
            error_code="EDGE_REJECTED",
            error_message="rejected",
        )
    )

    try:
        tracker.await_all([record], timeout_seconds=0.01)
    except MpcControlExecutionError as error:
        assert "EDGE_REJECTED" in str(error)
    else:
        raise AssertionError("failed ACK must fail the terminal barrier")


def test_missing_edge_terminal_report_times_out():
    context, _source, _target, command = build_command()
    tracker = MpcControlDispatchTracker()
    record = tracker.register(command, context.biz_scene_instance_id, 4, 1)

    tracker.handle_response(
        HydroStationTargetValueResponse.from_request(
            command,
            command_status=CommandStatus.SUCCEED,
            success=True,
        )
    )

    try:
        tracker.await_all([record], timeout_seconds=0.001)
    except MpcControlExecutionError as error:
        assert "timed out" in str(error)
    else:
        raise AssertionError("ACK without edge terminal report must time out")
