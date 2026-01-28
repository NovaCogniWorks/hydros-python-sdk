#!/usr/bin/env python3
"""
快速验证脚本 - 验证重构后的代码是否正常工作
"""
import json
import sys
from typing import List

def test_imports():
    """测试所有导入是否正常"""
    print("=" * 60)
    print("测试 1: 验证所有导入")
    print("=" * 60)

    try:
        from hydros_agent_sdk.mqtt import HydrosMqttClient, CommandDispatcher
        from hydros_agent_sdk.protocol.commands import (
            SimTaskInitRequest, SimTaskInitResponse,
            TickCmdRequest, TickCmdResponse,
            TimeSeriesCalculationRequest, TimeSeriesCalculationResponse,
            TimeSeriesDataUpdateRequest, TimeSeriesDataUpdateResponse,
            SimCommandEnvelope
        )
        from hydros_agent_sdk.protocol.models import (
            SimulationContext, HydroAgent, HydroAgentInstance,
            TopHydroObject, CommandStatus, ObjectTimeSeries, TimeSeriesValue
        )
        from hydros_agent_sdk.protocol.events import (
            HydroEvent, TimeSeriesDataChangedEvent
        )
        print("✓ 所有导入成功")
        return True
    except Exception as e:
        print(f"✗ 导入失败: {e}")
        return False

def test_command_status_enum():
    """测试 CommandStatus 枚举"""
    print("\n" + "=" * 60)
    print("测试 2: 验证 CommandStatus 枚举")
    print("=" * 60)

    try:
        from hydros_agent_sdk.protocol.models import CommandStatus

        # 测试所有枚举值
        assert CommandStatus.INIT.value == "INIT"
        assert CommandStatus.PROCESSING.value == "PROCESSING"
        assert CommandStatus.SUCCEED.value == "SUCCEED"
        assert CommandStatus.FAILED.value == "FAILED"

        # 测试枚举比较
        status = CommandStatus.SUCCEED
        assert status == CommandStatus.SUCCEED
        assert status != CommandStatus.FAILED

        # 测试字符串转换
        assert str(status.value) == "SUCCEED"

        print(f"✓ CommandStatus 枚举值:")
        for s in CommandStatus:
            print(f"  - {s.name} = {s.value}")

        return True
    except Exception as e:
        print(f"✗ CommandStatus 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_snake_case_fields():
    """测试 snake_case 字段名"""
    print("\n" + "=" * 60)
    print("测试 3: 验证 snake_case 字段名")
    print("=" * 60)

    try:
        from hydros_agent_sdk.protocol.models import (
            SimulationContext, HydroAgent, HydroAgentInstance
        )

        # 测试 SimulationContext
        context = SimulationContext(
            biz_scene_instance_id="test_scene",
            task_id="test_task"
        )
        assert context.biz_scene_instance_id == "test_scene"
        assert context.task_id == "test_task"
        print("✓ SimulationContext 字段正确")

        # 测试 HydroAgent
        agent = HydroAgent(
            agent_code="TEST_AGENT",
            agent_type="TEST_TYPE",
            agent_name="Test Agent",
            agent_configuration_url="http://test.url"
        )
        assert agent.agent_code == "TEST_AGENT"
        assert agent.agent_type == "TEST_TYPE"
        assert agent.agent_name == "Test Agent"
        assert agent.agent_configuration_url == "http://test.url"
        print("✓ HydroAgent 字段正确")

        # 测试 HydroAgentInstance
        instance = HydroAgentInstance(
            agent_id="agent_001",
            agent_code="TEST_AGENT",
            agent_type="TEST_TYPE",
            agent_configuration_url="http://test.url",
            biz_scene_instance_id="test_scene",
            hydros_cluster_id="cluster_1",
            hydros_node_id="node_1",
            context=context
        )
        assert instance.agent_id == "agent_001"
        assert instance.biz_scene_instance_id == "test_scene"
        assert instance.hydros_cluster_id == "cluster_1"
        assert instance.hydros_node_id == "node_1"
        print("✓ HydroAgentInstance 字段正确")

        return True
    except Exception as e:
        print(f"✗ snake_case 字段测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_json_serialization():
    """测试 JSON 序列化"""
    print("\n" + "=" * 60)
    print("测试 4: 验证 JSON 序列化/反序列化")
    print("=" * 60)

    try:
        from hydros_agent_sdk.protocol.commands import SimTaskInitRequest
        from hydros_agent_sdk.protocol.models import SimulationContext, HydroAgent

        # 创建命令
        request = SimTaskInitRequest(
            command_id="test_cmd_123",
            context=SimulationContext(
                biz_scene_instance_id="test_scene",
                task_id="test_task"
            ),
            agent_list=[
                HydroAgent(
                    agent_code="AGENT_1",
                    agent_type="TYPE_1",
                    agent_configuration_url="http://config1.url"
                ),
                HydroAgent(
                    agent_code="AGENT_2",
                    agent_type="TYPE_2",
                    agent_configuration_url="http://config2.url"
                )
            ],
            biz_scene_configuration_url="http://scene.config.url"
        )

        # 序列化
        json_str = request.model_dump_json(by_alias=True)
        parsed = json.loads(json_str)

        # 验证 snake_case 字段
        assert "command_id" in parsed
        assert "command_type" in parsed
        assert "agent_list" in parsed
        assert "biz_scene_configuration_url" in parsed
        assert parsed["command_id"] == "test_cmd_123"
        assert parsed["command_type"] == "task_init_request"
        assert len(parsed["agent_list"]) == 2

        print("✓ JSON 序列化使用 snake_case")
        print(f"  示例字段: command_id, agent_list, biz_scene_configuration_url")

        # 反序列化
        from hydros_agent_sdk.protocol.commands import SimCommandEnvelope
        envelope = SimCommandEnvelope(command=parsed)
        assert envelope.command.command_id == "test_cmd_123"
        assert len(envelope.command.agent_list) == 2

        print("✓ JSON 反序列化成功")

        return True
    except Exception as e:
        print(f"✗ JSON 序列化测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_mqtt_payload():
    """测试实际 MQTT 消息解析"""
    print("\n" + "=" * 60)
    print("测试 5: 验证实际 MQTT 消息解析")
    print("=" * 60)

    try:
        from hydros_agent_sdk.protocol.commands import SimCommandEnvelope, SimTaskInitRequest

        # 实际的 MQTT 消息（来自错误日志）
        mqtt_payload = {
            "context": {
                "biz_scene_instance_id": "TASK202601281447VTSA9JDYWJPN",
                "task_id": None
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
            "biz_scene_configuration_url": "http://192.168.1.25:8081/hydros/api/1.0/scenarios/configuration",
            "command_type": "task_init_request"
        }

        # 解析
        envelope = SimCommandEnvelope(command=mqtt_payload)
        command = envelope.command

        # 验证
        assert isinstance(command, SimTaskInitRequest)
        assert command.command_id == "SIMCMD202601281447AQSXQJFIPTWY"
        assert command.context.biz_scene_instance_id == "TASK202601281447VTSA9JDYWJPN"
        assert len(command.agent_list) == 1
        assert command.agent_list[0].agent_code == "TWINS_SIMULATION_AGENT"

        print("✓ MQTT 消息解析成功")
        print(f"  Command ID: {command.command_id}")
        print(f"  Scene ID: {command.context.biz_scene_instance_id}")
        print(f"  Agents: {len(command.agent_list)}")

        return True
    except Exception as e:
        print(f"✗ MQTT 消息解析失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_response_creation():
    """测试响应创建"""
    print("\n" + "=" * 60)
    print("测试 6: 验证响应创建")
    print("=" * 60)

    try:
        from hydros_agent_sdk.protocol.commands import SimTaskInitResponse
        from hydros_agent_sdk.protocol.models import (
            SimulationContext, HydroAgentInstance, CommandStatus
        )

        context = SimulationContext(
            biz_scene_instance_id="test_scene",
            task_id="test_task"
        )

        # 创建响应
        response = SimTaskInitResponse(
            command_id="response_123",
            context=context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=HydroAgentInstance(
                agent_id="agent_001",
                agent_code="TEST_AGENT",
                agent_type="TEST_TYPE",
                agent_configuration_url="http://test.url",
                biz_scene_instance_id="test_scene",
                hydros_cluster_id="cluster_1",
                hydros_node_id="node_1",
                context=context
            ),
            created_agent_instances=[],
            managed_top_objects={},
            broadcast=False
        )

        # 验证
        assert response.command_id == "response_123"
        assert response.command_status == CommandStatus.SUCCEED
        assert response.source_agent_instance.agent_id == "agent_001"

        # 序列化
        json_str = response.model_dump_json(by_alias=True)
        parsed = json.loads(json_str)

        assert parsed["command_status"] == "SUCCEED"
        assert parsed["source_agent_instance"]["agent_id"] == "agent_001"

        print("✓ 响应创建成功")
        print(f"  Command Status: {response.command_status.value}")
        print(f"  Source Agent: {response.source_agent_instance.agent_id}")

        return True
    except Exception as e:
        print(f"✗ 响应创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_all_command_types():
    """测试所有命令类型"""
    print("\n" + "=" * 60)
    print("测试 7: 验证所有命令类型")
    print("=" * 60)

    try:
        from hydros_agent_sdk.protocol.commands import (
            SimTaskInitRequest, TickCmdRequest,
            TimeSeriesCalculationRequest, TimeSeriesDataUpdateRequest
        )
        from hydros_agent_sdk.protocol.models import (
            SimulationContext, HydroAgent, HydroAgentInstance
        )
        from hydros_agent_sdk.protocol.events import (
            HydroEvent, TimeSeriesDataChangedEvent
        )

        context = SimulationContext(biz_scene_instance_id="test")

        # SimTaskInitRequest
        cmd1 = SimTaskInitRequest(
            command_id="cmd1",
            context=context,
            agent_list=[]
        )
        assert cmd1.command_type == "task_init_request"
        print("✓ SimTaskInitRequest")

        # TickCmdRequest
        cmd2 = TickCmdRequest(
            command_id="cmd2",
            context=context,
            tick_id=100,
            delta_time=0.05
        )
        assert cmd2.command_type == "tick_cmd_request"
        assert cmd2.tick_id == 100
        assert cmd2.delta_time == 0.05
        print("✓ TickCmdRequest")

        # TimeSeriesCalculationRequest
        instance = HydroAgentInstance(
            agent_id="agent1",
            agent_code="CODE",
            agent_type="TYPE",
            agent_configuration_url="http://url",
            biz_scene_instance_id="test",
            hydros_cluster_id="cluster",
            hydros_node_id="node",
            context=context
        )
        cmd3 = TimeSeriesCalculationRequest(
            command_id="cmd3",
            context=context,
            target_agent_instance=instance,
            hydro_event=HydroEvent(hydro_event_type="TEST_EVENT")
        )
        assert cmd3.target_agent_instance.agent_id == "agent1"
        print("✓ TimeSeriesCalculationRequest")

        # TimeSeriesDataUpdateRequest
        cmd4 = TimeSeriesDataUpdateRequest(
            command_id="cmd4",
            context=context,
            time_series_data_changed_event=TimeSeriesDataChangedEvent(
                object_time_series=[]
            )
        )
        assert cmd4.time_series_data_changed_event is not None
        print("✓ TimeSeriesDataUpdateRequest")

        return True
    except Exception as e:
        print(f"✗ 命令类型测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "重构验证测试套件" + " " * 25 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    tests = [
        ("导入测试", test_imports),
        ("CommandStatus 枚举", test_command_status_enum),
        ("snake_case 字段", test_snake_case_fields),
        ("JSON 序列化", test_json_serialization),
        ("MQTT 消息解析", test_mqtt_payload),
        ("响应创建", test_response_creation),
        ("所有命令类型", test_all_command_types),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ 测试 '{name}' 发生异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 打印总结
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 22 + "测试总结" + " " * 26 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"  {status:8} - {name}")

    print()
    print(f"  总计: {passed}/{total} 测试通过")

    if passed == total:
        print()
        print("  " + "=" * 54)
        print("  🎉 所有测试通过！重构成功完成！")
        print("  " + "=" * 54)
        print()
        return 0
    else:
        print()
        print("  " + "=" * 54)
        print(f"  ⚠️  {total - passed} 个测试失败，请检查错误信息")
        print("  " + "=" * 54)
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())
