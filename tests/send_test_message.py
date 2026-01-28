#!/usr/bin/env python3
"""
测试脚本 - 模拟发送 MQTT 消息来测试 stub
"""
import json
import time
import paho.mqtt.client as mqtt

# MQTT 配置（与 manual_mqtt_stub.py 相同）
BROKER_HOST = "192.168.1.24"
BROKER_PORT = 1883
TOPIC = "/hydros/commands/coordination/weijiahao"

# 模拟的 MQTT 消息（来自实际日志）
test_payload = {
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

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✓ 已连接到 MQTT broker: {BROKER_HOST}:{BROKER_PORT}")
        print(f"✓ 准备发送测试消息到主题: {TOPIC}")
    else:
        print(f"✗ 连接失败，返回码: {rc}")

def on_publish(client, userdata, mid):
    print(f"✓ 消息已发送 (message id: {mid})")

def main():
    print("=" * 70)
    print("MQTT 消息发送测试")
    print("=" * 70)
    print()
    print("此脚本将发送一条测试消息到 MQTT broker")
    print(f"Broker: {BROKER_HOST}:{BROKER_PORT}")
    print(f"Topic: {TOPIC}")
    print()
    print("请确保:")
    print("  1. MQTT broker 正在运行")
    print("  2. manual_mqtt_stub.py 正在另一个终端运行")
    print()

    input("按 Enter 继续...")
    print()

    # 创建客户端
    client = mqtt.Client(client_id="test_publisher", protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_publish = on_publish

    try:
        # 连接
        print(f"正在连接到 {BROKER_HOST}:{BROKER_PORT}...")
        client.connect(BROKER_HOST, BROKER_PORT, 60)
        client.loop_start()

        # 等待连接
        time.sleep(2)

        # 发送消息
        print()
        print("发送测试消息...")
        print("-" * 70)
        print(json.dumps(test_payload, indent=2, ensure_ascii=False))
        print("-" * 70)
        print()

        payload_str = json.dumps(test_payload)
        result = client.publish(TOPIC, payload_str)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print("✓ 消息发送成功")
        else:
            print(f"✗ 消息发送失败: {result.rc}")

        # 等待消息发送完成
        time.sleep(2)

        print()
        print("=" * 70)
        print("测试完成")
        print("=" * 70)
        print()
        print("请检查 manual_mqtt_stub.py 的输出，应该看到:")
        print("  1. 收到消息的日志")
        print("  2. 成功解析命令（没有验证错误）")
        print("  3. 发送响应的日志")
        print()

    except ConnectionRefusedError:
        print()
        print("✗ 连接被拒绝")
        print()
        print("可能的原因:")
        print("  1. MQTT broker 未运行")
        print("  2. Broker 地址或端口不正确")
        print("  3. 防火墙阻止连接")
        print()
        print("请检查 MQTT broker 是否在 192.168.1.24:1883 运行")
        print()
        return 1

    except Exception as e:
        print(f"✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        client.loop_stop()
        client.disconnect()

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
