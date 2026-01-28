"""
Integration test to verify MQTT message parsing with snake_case fields
"""
import json
from hydros_agent_sdk.protocol.commands import SimCommandEnvelope, SimTaskInitRequest
from hydros_agent_sdk.protocol.models import CommandStatus

def test_mqtt_payload_parsing():
    """Test parsing the actual MQTT payload from the error log"""

    # This is the actual payload from the error log
    mqtt_payload = {
        "context": {
            "tenant": {
                "tenant_id": "1111",
                "tenant_name": "河北工程大学水利学院"
            },
            "biz_scenario": {
                "biz_scenario_id": "100008",
                "biz_scenario_name": "京石段-SDK-测试"
            },
            "waterway": {
                "waterway_id": "50",
                "waterway_name": "京石段"
            },
            "biz_scene_instance_id": "TASK202601281447VTSA9JDYWJPN",
            "valid": True
        },
        "agent_list": [
            {
                "agent_code": "TWINS_SIMULATION_AGENT",
                "agent_type": "TWINS_SIMULATION_AGENT",
                "agent_name": "孪生智能体",
                "agent_configuration_url": "http://47.97.1.45:9000/hydros/mdm/京石段/agents/twins_simulation/agent_config.yaml"
            }
        ],
        "command_id": "SIMCMD202601281447AQSXQJFIPTWY",
        "broadcast": True,
        "biz_scene_configuration_url": "http://192.168.1.25:8081/hydros/api/1.0/scenarios/configuration?hydro_biz_scenario_id=100008&format=json",
        "command_type": "task_init_request"
    }

    print("Testing MQTT payload parsing...")
    print(f"Payload: {json.dumps(mqtt_payload, indent=2, ensure_ascii=False)}")

    try:
        # Parse the command using the envelope
        envelope = SimCommandEnvelope(command=mqtt_payload)
        command = envelope.command

        print(f"\n✓ Successfully parsed command!")
        print(f"  Command type: {command.command_type}")
        print(f"  Command ID: {command.command_id}")
        print(f"  Context biz_scene_instance_id: {command.context.biz_scene_instance_id}")
        print(f"  Number of agents: {len(command.agent_list)}")
        print(f"  First agent code: {command.agent_list[0].agent_code}")
        print(f"  First agent type: {command.agent_list[0].agent_type}")

        assert isinstance(command, SimTaskInitRequest)
        assert command.command_id == "SIMCMD202601281447AQSXQJFIPTWY"
        assert command.context.biz_scene_instance_id == "TASK202601281447VTSA9JDYWJPN"
        assert len(command.agent_list) == 1
        assert command.agent_list[0].agent_code == "TWINS_SIMULATION_AGENT"

        print("\n✓ All assertions passed!")
        return True

    except Exception as e:
        print(f"\n✗ Failed to parse command: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_command_status_enum():
    """Test CommandStatus enum"""
    print("\n\nTesting CommandStatus enum...")

    # Test enum values
    assert CommandStatus.INIT.value == "INIT"
    assert CommandStatus.PROCESSING.value == "PROCESSING"
    assert CommandStatus.SUCCEED.value == "SUCCEED"
    assert CommandStatus.FAILED.value == "FAILED"

    # Test enum comparison
    status = CommandStatus.SUCCEED
    assert status == CommandStatus.SUCCEED
    assert status.value == "SUCCEED"

    # Test JSON serialization
    from hydros_agent_sdk.protocol.commands import SimTaskInitResponse
    from hydros_agent_sdk.protocol.models import HydroAgentInstance, SimulationContext

    response = SimTaskInitResponse(
        context=SimulationContext(biz_scene_instance_id="test"),
        command_id="test_cmd",
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=HydroAgentInstance(
            agent_id="test_agent",
            agent_code="TEST",
            agent_type="TEST",
            agent_configuration_url="http://test.url",
            biz_scene_instance_id="test",
            hydros_cluster_id="cluster1",
            hydros_node_id="node1",
            context=SimulationContext(biz_scene_instance_id="test")
        ),
        created_agent_instances=[],
        managed_top_objects={},
        broadcast=False
    )

    json_str = response.model_dump_json(by_alias=True)
    parsed = json.loads(json_str)

    print(f"  Command status in JSON: {parsed.get('command_status')}")
    assert parsed.get('command_status') == "SUCCEED"

    print("✓ CommandStatus enum tests passed!")
    return True

if __name__ == "__main__":
    success = True
    success = test_mqtt_payload_parsing() and success
    success = test_command_status_enum() and success

    if success:
        print("\n" + "="*50)
        print("✓ All integration tests passed!")
        print("="*50)
    else:
        print("\n" + "="*50)
        print("✗ Some tests failed!")
        print("="*50)
        exit(1)
