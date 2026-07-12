from hydros_agent_sdk.protocol.agent_commands import (
    AgentCommandCatalog,
    HydroStationTargetValueRequest,
    HydroStationTargetValueResponse,
)
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.protocol.agent_commands.base import AgentCommand
from hydros_agent_sdk.protocol.base import HydroCmd
from hydros_agent_sdk.protocol.commands import SimCommand
from hydros_agent_sdk.protocol.system_commands import SystemCmd
from hydros_agent_sdk.agent_commands.transport.codec import AgentCommandDecoder


def test_agent_command_dtos_are_owned_by_protocol() -> None:
    command = HydroStationTargetValueRequest(
        command_id="cmd-1",
        object_id=101,
        object_type="PumpStation",
        target_value_type=DeviceValueTypeEnum.WATER_LEVEL.code,
        target_value=12.3,
    )

    decoded = AgentCommandDecoder().decode(command.model_dump())

    assert isinstance(decoded, HydroStationTargetValueRequest)
    assert AgentCommandCatalog.AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST in AgentCommandCatalog.values()
    assert HydroStationTargetValueRequest.__module__ == "hydros_agent_sdk.protocol.agent_commands.commands"


def test_agent_command_runtime_owns_decoding_while_protocol_exports_only_dtos() -> None:
    import hydros_agent_sdk.protocol.agent_commands as protocol_agent_commands

    assert not hasattr(protocol_agent_commands, "AgentCommand")
    assert not hasattr(protocol_agent_commands, "parse_agent_command")
    assert not hasattr(protocol_agent_commands, "AgentCommandEnvelope")


def test_all_command_families_share_one_protocol_hydro_cmd() -> None:
    assert issubclass(SimCommand, HydroCmd)
    assert issubclass(SystemCmd, HydroCmd)
    assert issubclass(AgentCommand, HydroCmd)


def test_station_target_value_dtos_include_java_direct_fields() -> None:
    assert {
        "object_id",
        "object_type",
        "target_value_type",
        "target_value",
        "target_value_map",
        "group_id",
        "group_size",
        "main_step_index",
    } <= HydroStationTargetValueRequest.model_fields.keys()
    assert {"object_id", "target_value_type", "target_value", "target_value_map"} <= (
        HydroStationTargetValueResponse.model_fields.keys()
    )
