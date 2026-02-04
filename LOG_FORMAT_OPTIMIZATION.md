# 日志格式优化说明

## 问题

原日志格式包含两个无用的预留字段，导致出现 `|||`：

```
default_cluster|default_central|2026-02-04 10:16:52|INFO |TASK202602041016M2IQ5XG8BIEE|AGT2026020410161K91BN_TWINS_SIMULATION_AGENT|||tickable_agent.py:181|发布协调指令成功
                                                                                                                            ^^^
                                                                                                                            无意义的预留字段
```

## 优化方案

移除两个无用的预留字段，简化日志格式。

### 优化前（10 个字段）

```
CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|RESERVED1|RESERVED2|SOURCE|MESSAGE
```

示例：
```
default_cluster|default_central|2026-02-04 10:16:52|INFO |TASK202602041016M2IQ5XG8BIEE|AGT2026020410161K91BN_TWINS_SIMULATION_AGENT|||tickable_agent.py:181|发布协调指令成功
```

### 优化后（8 个字段）

```
CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|SOURCE|MESSAGE
```

示例：
```
default_cluster|default_central|2026-02-04 10:40:40|INFO |TASK202602041016M2IQ5XG8BIEE|AGT2026020410161K91BN_TWINS_SIMULATION_AGENT|tickable_agent.py:181|发布协调指令成功
```

## 字段说明

### Agent 业务逻辑日志（有任务上下文）

| 位置 | 字段名 | 示例值 | 说明 |
|-----|-------|--------|------|
| 1 | `hydros_cluster_id` | `default_cluster` | 集群 ID |
| 2 | `hydros_node_id` | `default_central` | 节点 ID |
| 3 | `timestamp` | `2026-02-04 10:40:40` | 时间戳 (yyyy-MM-dd HH:mm:ss) |
| 4 | `level` | `INFO ` | 日志级别（5字符左对齐） |
| 5 | `biz_scene_instance_id` | `TASK202602041016M2IQ5XG8BIEE` | 仿真任务 ID |
| 6 | `agent_id` | `AGT2026020410161K91BN_TWINS_SIMULATION_AGENT` | Agent 实例 ID |
| 7 | `source_location` | `tickable_agent.py:181` | 源代码位置（可点击） |
| 8 | `message` | `发布协调指令成功...` | 日志消息 |

### 基础设施日志（无任务上下文）

| 位置 | 字段名 | 示例值 | 说明 |
|-----|-------|--------|------|
| 1 | `hydros_cluster_id` | `default_cluster` | 集群 ID |
| 2 | `hydros_node_id` | `default_central` | 节点 ID |
| 3 | `timestamp` | `2026-02-04 10:40:40` | 时间戳 |
| 4 | `level` | `INFO ` | 日志级别 |
| 5 | `biz_component` | `SIM_SDK` | 组件名称 |
| 6 | `-` | `-` | 无 agent_id |
| 7 | `source_location` | `coordination_client.py:123` | 源代码位置 |
| 8 | `message` | `SDK 初始化完成` | 日志消息 |

## 代码变更

### 修改文件

`hydros_agent_sdk/logging_config.py`

### 变更内容

1. **移除预留字段定义**：
   ```python
   # 优化前
   parts = [
       hydros_cluster_id,
       hydros_node_id,
       timestamp,
       level,
       biz_scene_instance_id,
       biz_component,
       "",  # Reserved field 1 ❌
       "",  # Reserved field 2 ❌
       source_location,
       message
   ]

   # 优化后
   parts = [
       hydros_cluster_id,
       hydros_node_id,
       timestamp,
       level,
       biz_scene_instance_id,
       biz_component,
       source_location,  # ✅ 直接跟在 agent_id 后面
       message
   ]
   ```

2. **更新文档字符串**：
   - 移除预留字段的说明
   - 更新示例日志格式

## 测试结果

### 测试 1: 基础设施日志

```python
logger.info('SDK 初始化完成')
```

**输出**：
```
default_cluster|default_central|2026-02-04 10:40:40|INFO |Common|-|<string>:27|SDK 初始化完成
```

### 测试 2: Agent 业务逻辑日志

```python
set_biz_scene_instance_id('TASK202602041016M2IQ5XG8BIEE')
set_biz_component('AGT2026020410161K91BN_TWINS_SIMULATION_AGENT')
logger.info('发布协调指令成功,commandId=SIMCMD2026020410160I52CL9RAJK8')
```

**输出**：
```
default_cluster|default_central|2026-02-04 10:40:40|INFO |TASK202602041016M2IQ5XG8BIEE|AGT2026020410161K91BN_TWINS_SIMULATION_AGENT|<string>:36|发布协调指令成功,commandId=SIMCMD2026020410160I52CL9RAJK8
```

## 优势

1. **更简洁**：从 10 个字段减少到 8 个字段
2. **更清晰**：所有字段都有实际意义，没有空字段
3. **更易读**：减少了视觉干扰（`|||` → `|`）
4. **更高效**：减少了字符串拼接操作
5. **更实用**：不为未来可能永远不会用到的功能预留字段

## 兼容性

### 向后兼容性

- ✅ **API 兼容**：所有日志 API 保持不变
- ✅ **功能兼容**：所有日志功能正常工作
- ⚠️ **格式变更**：日志格式发生变化，如果有日志解析工具需要更新

### 日志解析工具更新

如果有工具解析日志文件，需要更新字段索引：

```python
# 优化前
fields = line.split('|')
cluster_id = fields[0]
node_id = fields[1]
timestamp = fields[2]
level = fields[3]
task_id = fields[4]
agent_id = fields[5]
# fields[6] 和 fields[7] 是空的预留字段
source = fields[8]
message = fields[9]

# 优化后
fields = line.split('|')
cluster_id = fields[0]
node_id = fields[1]
timestamp = fields[2]
level = fields[3]
task_id = fields[4]
agent_id = fields[5]
source = fields[6]  # ✅ 索引从 8 改为 6
message = fields[7]  # ✅ 索引从 9 改为 7
```

## 总结

- ✅ 移除了无意义的 `|||`
- ✅ 日志格式更简洁清晰
- ✅ 所有字段都有实际意义
- ✅ 测试通过，功能正常
- ⚠️ 如有日志解析工具需要更新字段索引

---

**优化完成时间**: 2026-02-04
**影响范围**: 日志格式
**兼容性**: API 兼容，格式变更
