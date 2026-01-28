# 字段命名规范迁移说明

## 概述

本次重构将所有 Pydantic 模型的字段命名从 **camelCase** 统一改为 **snake_case**，以匹配从 MQTT 接收的 JSON 消息格式，并将 `CommandStatus` 改造为枚举类型以匹配 Java 实现。

## 修改的文件

### 1. `hydros_agent_sdk/protocol/models.py`

#### SimulationContext
- `bizSceneInstanceId` → `biz_scene_instance_id`
- `taskId` → `task_id`

#### HydroAgent
- `agentCode` → `agent_code`
- `agentType` → `agent_type`
- `agentName` → `agent_name`
- `agentConfigurationUrl` → `agent_configuration_url`

#### HydroAgentInstance
- `agentId` → `agent_id`
- `bizSceneInstanceId` → `biz_scene_instance_id`
- `hydrosClusterId` → `hydros_cluster_id`
- `hydrosNodeId` → `hydros_node_id`

#### ObjectTimeSeries
- `timeSeriesName` → `time_series_name`
- `objectId` → `object_id`
- `objectType` → `object_type`
- `objectName` → `object_name`
- `metricsCode` → `metrics_code`
- `timeSeries` → `time_series`

#### CommandStatus (重要变更)
从 Pydantic 模型改为 Python 枚举：
```python
# 之前
class CommandStatus(HydroBaseModel):
    status: str

# 现在
class CommandStatus(str, Enum):
    INIT = "INIT"
    PROCESSING = "PROCESSING"
    SUCCEED = "SUCCEED"
    FAILED = "FAILED"
```

### 2. `hydros_agent_sdk/protocol/commands.py`

#### SimCoordinationResponse
- `commandStatus` → `command_status`
- `errorCode` → `error_code`
- `errorMessage` → `error_message`
- `sourceAgentInstance` → `source_agent_instance`

#### SimTaskInitRequest
- `agentList` → `agent_list`
- `bizSceneConfigurationUrl` → `biz_scene_configuration_url`

#### SimTaskInitResponse
- `createdAgentInstances` → `created_agent_instances`
- `managedTopObjects` → `managed_top_objects`

#### TickCmdRequest
- `tickId` → `tick_id`
- `deltaTime` → `delta_time`

#### TimeSeriesCalculationRequest
- `targetAgentInstance` → `target_agent_instance`
- `hydroEvent` → `hydro_event`

#### TimeSeriesCalculationResponse
- `hydroEvent` → `hydro_event`
- `objectTimeSeriesList` → `object_time_series_list`

#### TimeSeriesDataUpdateRequest
- `timeSeriesDataChangedEvent` → `time_series_data_changed_event`

### 3. `hydros_agent_sdk/protocol/events.py`

#### BaseHydroEvent
- `hydroEventId` → `hydro_event_id`
- `hydroEventName` → `hydro_event_name`
- `createdTime` → `created_time`
- `autoScheduleAtStep` → `auto_schedule_at_step`
- `hydroEventSourceType` → `hydro_event_source_type`
- `hydroEventSource` → `hydro_event_source`
- `hydroEventDescription` → `hydro_event_description`

#### TimeSeriesDataChangedEvent
- `objectTimeSeries` → `object_time_series`

### 4. `tests/manual_mqtt_stub.py`

- 修复了 `HydroAgentInstance` 的创建，添加了所有必需字段
- 更新了所有字段名为 snake_case
- 使用 `CommandStatus.SUCCEED` 枚举值替代字符串 `"SUCCEED"`

### 5. `tests/test_protocol_commands.py`

- 更新了测试代码中的所有字段名为 snake_case
- 修复了 `HydroAgentInstance` 的创建

## 迁移指南

### 如果你的代码使用了这些模型

#### 1. 更新字段访问
```python
# 之前
context.bizSceneInstanceId
agent.agentCode
response.createdAgentInstances

# 现在
context.biz_scene_instance_id
agent.agent_code
response.created_agent_instances
```

#### 2. 更新对象创建
```python
# 之前
SimulationContext(
    bizSceneInstanceId="scene1",
    taskId="task1"
)

# 现在
SimulationContext(
    biz_scene_instance_id="scene1",
    task_id="task1"
)
```

#### 3. 使用 CommandStatus 枚举
```python
# 之前
response.commandStatus = "SUCCEED"

# 现在
from hydros_agent_sdk.protocol.models import CommandStatus
response.command_status = CommandStatus.SUCCEED
```

#### 4. 创建 HydroAgentInstance 时提供所有必需字段
```python
# 之前（不完整，会导致验证错误）
HydroAgentInstance(
    agentId="agent1",
    context=context
)

# 现在（完整）
HydroAgentInstance(
    agent_id="agent1",
    agent_code="AGENT_CODE",
    agent_type="AGENT_TYPE",
    agent_configuration_url="http://config.url",
    biz_scene_instance_id="scene1",
    hydros_cluster_id="cluster1",
    hydros_node_id="node1",
    context=context
)
```

## 测试验证

运行以下测试以验证迁移成功：

```bash
# 基础协议测试
python tests/test_protocol_commands.py

# MQTT 集成测试（验证实际 MQTT 消息解析）
python tests/test_mqtt_integration.py
```

## 兼容性说明

- **JSON 序列化/反序列化**: 所有字段现在使用 snake_case，与 MQTT 消息格式完全匹配
- **CommandStatus**: 现在是强类型枚举，提供更好的类型安全性
- **向后兼容性**: 此次修改不向后兼容，所有使用旧字段名的代码都需要更新

## 解决的问题

1. ✅ 修复了 MQTT 消息解析时的字段名不匹配错误
2. ✅ 修复了 `HydroAgentInstance` 缺少必需字段的验证错误
3. ✅ 将 `CommandStatus` 改为枚举类型，提供类型安全
4. ✅ 统一了代码风格，使用 Python 社区推荐的 snake_case 命名

## 相关问题

如果遇到以下错误：
```
ValidationError: 6 validation errors for HydroAgentInstance
agent_code
  Field required
```

这表示你在创建 `HydroAgentInstance` 时缺少必需字段。请参考上面的"创建 HydroAgentInstance"示例。
