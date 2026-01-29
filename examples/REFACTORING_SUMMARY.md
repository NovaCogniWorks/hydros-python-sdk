# 配置文件重构总结

## 改动概述

将 MySampleHydroAgent 从硬编码配置改为完全从 `agent.properties` 文件加载配置。

## 主要变更

### 1. 删除的参数

**MySampleHydroAgent 构造函数：**
- ❌ 删除 `component_name` 参数
- ❌ 删除 `hydros_cluster_id` 参数
- ❌ 删除 `hydros_node_id` 参数
- ✅ 保留 `config_file` 参数（必需）

**MySampleAgentFactory 构造函数：**
- ❌ 删除 `component_name` 参数
- ❌ 删除 `node_id` 参数
- ✅ 保留 `config_file` 参数

**MultiAgentCoordinationCallback 构造函数：**
- ❌ 删除 `component_name` 参数
- ✅ 新增 `config_file` 参数
- ✅ 内部从配置文件加载 component_name

### 2. 必须从配置文件加载的属性

以下属性**必须**在 `agent.properties` 中定义，否则会抛出异常：

```properties
# 必需属性
agent_code=TWINS_SIMULATION_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Twins Simulation Agent
agent_configuration_url=http://example.com/config/twins-agent.yaml
```

### 3. 可选配置属性

以下属性有默认值，可以不在配置文件中定义：

```properties
# 可选属性（有默认值）
drive_mode=SIM_TICK_DRIVEN                    # 默认: SIM_TICK_DRIVEN
hydros_cluster_id=default_cluster             # 默认: default_cluster
hydros_node_id=default_central                # 默认: default_node
```

## 代码使用示例

### 之前的用法（已废弃）

```python
# ❌ 旧方式 - 需要传递多个参数
agent_factory = MySampleAgentFactory(
    component_name="TWINS_SIMULATION_AGENT",
    node_id="default_central",
    config_file="examples/agent.properties"
)

callback = MultiAgentCoordinationCallback(
    component_name="TWINS_SIMULATION_AGENT",
    agent_factory=agent_factory
)
```

### 现在的用法（推荐）

```python
# ✅ 新方式 - 所有配置从文件加载
agent_factory = MySampleAgentFactory(
    config_file="examples/agent.properties"
)

callback = MultiAgentCoordinationCallback(
    agent_factory=agent_factory,
    config_file="examples/agent.properties"
)
```

## 配置文件示例

完整的 `agent.properties` 文件示例：

```properties
# Hydro Agent Configuration
# This file contains the configuration for the sample agent

# Agent identification (必需)
agent_code=TWINS_SIMULATION_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Twins Simulation Agent

# Agent configuration URL (必需)
agent_configuration_url=http://example.com/config/twins-agent.yaml

# Agent drive mode (可选，默认: SIM_TICK_DRIVEN)
# 可选值: SIM_TICK_DRIVEN, EVENT_DRIVEN, PROACTIVE
drive_mode=SIM_TICK_DRIVEN

# Cluster and node configuration (可选)
hydros_cluster_id=default_cluster
hydros_node_id=default_central
```

## 错误处理

### 配置文件不存在

```python
# 会抛出 FileNotFoundError
agent = MySampleHydroAgent(
    sim_coordination_client=client,
    context=context,
    config_file="non_existent.properties"
)
```

### 缺少必需属性

```python
# 会抛出 ValueError，提示缺少哪些属性
# 例如: ValueError: Missing required properties in agent.properties: agent_code, agent_name
```

## 验证配置

运行测试脚本验证配置文件：

```bash
python3 examples/test_config.py
```

输出示例：
```
Testing Agent Configuration Loading
============================================================
✓ Config file found: examples/agent.properties
✓ Config file parsed successfully

Configuration Values:
------------------------------------------------------------
✓ agent_code                     = TWINS_SIMULATION_AGENT
✓ agent_type                     = TWINS_SIMULATION_AGENT
✓ agent_name                     = Twins Simulation Agent
✓ agent_configuration_url        = http://example.com/config/twins-agent.yaml

Optional Configuration:
------------------------------------------------------------
  drive_mode                     = SIM_TICK_DRIVEN
  hydros_cluster_id              = default_cluster
  hydros_node_id                 = default_central

============================================================
✓ All required configuration properties are present
============================================================
```

## 优势

1. **配置集中管理**：所有 agent 配置在一个文件中
2. **无硬编码**：代码中不再有硬编码的 agent 属性
3. **易于修改**：修改配置不需要改代码
4. **类型安全**：配置加载时会验证必需属性
5. **清晰的错误提示**：缺少配置时会明确指出

## 迁移指南

如果你有现有代码使用旧的 API：

1. 创建 `agent.properties` 文件
2. 将所有 agent 相关配置写入文件
3. 删除代码中的 `component_name`、`node_id` 等参数
4. 只传递 `config_file` 参数
5. 运行 `test_config.py` 验证配置

## 相关文件

- `examples/agent.properties` - 配置文件
- `examples/agent_example.py` - 示例代码
- `examples/test_config.py` - 配置验证脚本
- `examples/AGENT_CONFIG.md` - 配置文件详细说明
