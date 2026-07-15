from unittest.mock import Mock

from hydros_agent_sdk.agent_commands.dispatching import ControlCommandDispatcher
from hydros_agent_sdk.agent_commands.target_value_builder import StationTargetValueCommandBuilder
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.protocol.models import AgentDriveMode, HydroAgentInstance, SimulationContext


def build_agent(agent_id: str, context: SimulationContext) -> HydroAgentInstance:
    return HydroAgentInstance(
        agent_id=agent_id,
        agent_code=agent_id,
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name=agent_id,
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster-a",
        hydros_node_id="node-a",
        context=context,
        drive_mode=AgentDriveMode.PROACTIVE,
    )


def test_station_flow_command_preserves_group_fields_through_builder_and_dispatcher():
    context = SimulationContext(biz_scene_instance_id="scene-station-flow")
    source = build_agent("source-agent", context)
    target = build_agent("STATION_AGENT", context)
    builder = StationTargetValueCommandBuilder(
        source_agent=source,
        get_sibling_agent_instance=lambda agent_code: target if agent_code == "STATION_AGENT" else None,
        resolve_target_agent_for_object=lambda _object_id, _object_type: target,
    )
    send_command = Mock()
    dispatcher = ControlCommandDispatcher(
        send_command=send_command,
        build_station_target_value_request=builder.build_station_target_value_request,
    )

    dispatcher.dispatch(
        [
            {
                "target_agent_code": "STATION_AGENT",
                "target_command_type": DeviceValueTypeEnum.WATER_FLOW.code,
                "target_value": "123.45",
                "object_id": 1001,
                "object_type": "PumpStation",
                "group_id": "pump-station-flow:8",
                "group_size": 1,
                "main_step_index": 8,
            }
        ]
    )

    request = send_command.call_args.args[0]
    assert request.target.agent_code == "STATION_AGENT"
    assert request.object_id == 1001
    assert request.object_type == "PumpStation"
    assert request.target_value_type == "water_flow"
    assert request.target_value == 123.45
    assert request.group_id == "pump-station-flow:8"
    assert request.group_size == 1
    assert request.main_step_index == 8
