# 02 配置模板

## 1. 文档说明

本文是对外交付包中的配置模板说明，用于帮助外部团队快速准备最小可用配置。

说明：

- 本文属于执行侧交付材料，不重新定义架构边界或配置体系设计
- 配置职责边界以上游架构文档和当前工程实现为准
- 本文只保留对外交付时最常用、最小化的配置说明

## 2. env.properties

```properties
mqtt_broker_url=tcp://127.0.0.1
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/default_cluster
hydros_cluster_id=default_cluster
hydros_node_id=external_node_001
mqtt_username=
mqtt_password=
```

字段说明：

- `mqtt_broker_url`: MQTT 服务地址
- `mqtt_broker_port`: MQTT 服务端口
- `mqtt_topic`: 协调命令主主题
- `hydros_cluster_id`: 集群标识
- `hydros_node_id`: 节点标识
- `mqtt_username`: 可选用户名
- `mqtt_password`: 可选密码

## 3. agent.properties

```properties
agent_code=DEMO_TWINS_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Demo Twins Agent
```

字段说明：

- `agent_code`: Agent 唯一业务编码
- `agent_type`: Agent 类型
- `agent_name`: Agent 显示名称

## 4. 配置职责约束

- `env.properties` 只放环境运行参数
- `agent.properties` 只放 Agent 最小身份信息
- 远程 YAML 只放建模、业务、控制相关的正式参数

## 5. 常见错误

- 在 `agent.properties` 中重复放 `hydros_cluster_id`
- 在 `env.properties` 中写入大量业务参数
- `agent_code` 与中央侧期望编码不一致
- `mqtt_topic` 与中央侧投递主题不一致

## 6. 关联说明

如需查看更完整的集成上下文，可参考：

- `01-external-integration-readme.md`
- `03-startup-checklist.md`
- `05-delivery-acceptance-checklist.md`
