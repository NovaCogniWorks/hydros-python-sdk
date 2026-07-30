from hydros_agent_sdk.error_codes import ErrorCodes
from hydros_agent_sdk.error_handling import handle_agent_errors
from hydros_agent_sdk.protocol.commands import TickCmdRequest, TickCmdResponse
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    AgentInstanceStatus,
    AgentStatus,
    CommandStatus,
    HydroAgentInstance,
    SimulationContext,
)


class _FailingTickAgent(HydroAgentInstance):
    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_tick_simulation(self, request: TickCmdRequest):
        raise RuntimeError("control failed")


def test_tick_error_response_preserves_required_completed_step():
    context = SimulationContext(biz_scene_instance_id="TASK_ERROR_RESPONSE")
    agent = _FailingTickAgent(
        agent_code="CENTRAL_SCHEDULING_AGENT_POWER",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Power scheduling agent",
        agent_id="AGT_POWER",
        biz_scene_instance_id=context.biz_scene_instance_id,
        cluster_id="cluster-a",
        node_id="central-a",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        agent_instance_status=AgentInstanceStatus.RUNNING,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )

    response = agent.on_tick_simulation(
        TickCmdRequest(command_id="SIMCMD_TICK", context=context, step=7)
    )

    assert isinstance(response, TickCmdResponse)
    assert response.command_status == CommandStatus.FAILED
    assert response.completed_step == 7
    assert response.error_code == ErrorCodes.SIMULATION_EXECUTION_FAILURE.code
    assert "control failed" in response.error_message
