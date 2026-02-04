# 配置重构文档

## 概述

本次重构将 `hydros_cluster_id` 和 `hydros_node_id` 从各个 agent 的 `agent.properties` 文件移至共享的 `examples/env.properties` 文件，实现配置的集中管理。

## 变更日期

2026-02-04

## 变更内容

### 1. 配置文件变更

#### 1.1 `examples/env.properties` - 新增配置项

```properties
# Hydros Cluster and Node Configuration
# These settings are shared by all agents in this deployment
hydros_cluster_id=default_cluster
hydros_node_id=default_central
```

**说明**: 这两个配置项现在由所有 agent 共享，统一在 `env.properties` 中配置。

#### 1.2 各个 `agent.properties` 文件 - 移除配置项

以下文件已移除 `hydros_cluster_id` 和 `hydros_node_id` 配置项：

- `examples/agents/twins/agent.properties`
- `examples/agents/ontology/agent.properties`
- `examples/agents/centralscheduling/agent.properties`

**说明**: 添加了注释说明这些配置项现在在 `env.properties` 中配置。

### 2. 代码变更

#### 2.1 `examples/agents/common.py` - HydroAgentFactory

**变更 1: 构造函数新增 `env_config` 参数**

```python
def __init__(
    self,
    agent_class: Type[AgentType],
    config_file: str = "./agent.properties",
    env_config: Optional[Dict[str, str]] = None  # 新增参数
):
```

**变更 2: `create_agent` 方法更新配置加载逻辑**

```python
def create_agent(self, sim_coordination_client, context):
    # 加载 agent 配置
    config = self._load_config(self.config_file)

    # 如果没有提供 env_config，则加载
    if self.env_config is None:
        script_dir = os.path.dirname(self.config_file)
        env_file = os.path.join(script_dir, "env.properties")
        self.env_config = load_env_config_with_fallback(env_file)

    # 从 env_config 获取 cluster_id 和 node_id
    # 如果 env_config 中没有，则回退到 agent config（向后兼容）
    hydros_cluster_id = self.env_config.get(
        'hydros_cluster_id',
        config.get('hydros_cluster_id', 'default_cluster')
    )
    hydros_node_id = self.env_config.get(
        'hydros_node_id',
        config.get('hydros_node_id', 'default_node')
    )

    # 创建 agent 时使用合并后的配置
    agent = self.agent_class(
        sim_coordination_client=sim_coordination_client,
        agent_id=agent_id,
        agent_code=config['agent_code'],
        agent_type=config['agent_type'],
        agent_name=config['agent_name'],
        context=context,
        hydros_cluster_id=hydros_cluster_id,
        hydros_node_id=hydros_node_id
    )
```

**变更 3: `_load_config` 方法更新**

```python
def _load_config(self, config_file: str) -> Dict[str, str]:
    # ... 省略部分代码 ...

    # hydros_cluster_id 和 hydros_node_id 现在是可选的
    result = {
        'agent_code': config.get('DEFAULT', 'agent_code'),
        'agent_type': config.get('DEFAULT', 'agent_type'),
        'agent_name': config.get('DEFAULT', 'agent_name'),
    }

    # 可选字段（向后兼容）
    cluster_id = config.get('DEFAULT', 'hydros_cluster_id', fallback=None)
    if cluster_id:
        result['hydros_cluster_id'] = cluster_id

    node_id = config.get('DEFAULT', 'hydros_node_id', fallback=None)
    if node_id:
        result['hydros_node_id'] = node_id

    return result
```

**变更 4: `_load_properties_file` 方法更新**

```python
def _load_properties_file(file_path: str) -> Dict[str, str]:
    # ... 省略部分代码 ...

    result = {}
    # 新增加载 hydros_cluster_id 和 hydros_node_id
    for key in ['mqtt_broker_url', 'mqtt_broker_port', 'mqtt_topic',
                'hydros_cluster_id', 'hydros_node_id']:
        value = config.get('DEFAULT', key, fallback=None)
        if value:
            result[key] = value

    return result
```

#### 2.2 使用 `HydroAgentFactory` 的文件更新

以下文件在创建 `HydroAgentFactory` 时传递 `env_config` 参数：

**`examples/simple_multi_agent_example.py`**

```python
# 加载环境配置
env_config = load_env_config_with_fallback()

# 创建 factory 时传递 env_config
twins_factory = HydroAgentFactory(
    agent_class=MyTwinsSimulationAgent,
    config_file=os.path.join(EXAMPLES_DIR, "agents/twins/agent.properties"),
    env_config=env_config  # 传递 env_config
)
```

**`examples/multi_agent_launcher.py`**

```python
# 加载环境配置
env_config = load_env_config_with_fallback(env_file)

# 创建 factory 时传递 env_config
agent_factory = HydroAgentFactory(
    agent_class=agent_info['agent_class'],
    config_file=config_file,
    env_config=env_config  # 传递 env_config
)
```

**`examples/agents/twins/twins_agent.py`**

```python
# 加载环境配置
env_config = load_env_config_with_fallback(ENV_FILE)

# 创建 factory 时传递 env_config
agent_factory = HydroAgentFactory(
    agent_class=MyTwinsSimulationAgent,
    config_file=CONFIG_FILE,
    env_config=env_config  # 传递 env_config
)
```

**`examples/agents/ontology/ontology_agent.py`**

```python
# 加载环境配置
env_config = load_env_config_with_fallback(ENV_FILE)

# 创建 factory 时传递 env_config
agent_factory = HydroAgentFactory(
    agent_class=MyOntologySimulationAgent,
    config_file=CONFIG_FILE,
    env_config=env_config  # 传递 env_config
)
```

## 配置优先级

重构后的配置加载优先级如下：

1. **env.properties** (最高优先级)
   - 共享配置，所有 agent 使用相同的 `hydros_cluster_id` 和 `hydros_node_id`

2. **agent.properties** (向后兼容)
   - 如果 `env.properties` 中没有配置，则从 `agent.properties` 读取
   - 如果两者都没有，使用默认值 `default_cluster` 和 `default_node`

## 向后兼容性

本次重构保持了完全的向后兼容性：

1. **旧配置仍然有效**: 如果 `agent.properties` 中仍包含 `hydros_cluster_id` 和 `hydros_node_id`，代码仍能正常工作

2. **配置优先级**: `env.properties` 中的配置会覆盖 `agent.properties` 中的配置

3. **默认值**: 如果两个文件都没有配置，使用默认值

## 优势

1. **集中管理**: 所有 agent 的 cluster 和 node 配置集中在一个文件中，便于管理

2. **减少重复**: 不需要在每个 agent 的配置文件中重复配置相同的值

3. **易于部署**: 部署到不同环境时，只需修改 `env.properties` 一个文件

4. **向后兼容**: 不会破坏现有的配置文件和代码

## 测试验证

所有变更已通过以下测试：

1. ✓ `env.properties` 包含所有必需的配置项
2. ✓ 所有 `agent.properties` 文件已正确移除 cluster/node 配置
3. ✓ `HydroAgentFactory` 配置合并逻辑正确
4. ✓ 向后兼容性测试通过
5. ✓ 配置优先级测试通过

## 迁移指南

### 对于新项目

直接在 `examples/env.properties` 中配置 `hydros_cluster_id` 和 `hydros_node_id`，不需要在各个 `agent.properties` 中配置。

### 对于现有项目

1. 将 `hydros_cluster_id` 和 `hydros_node_id` 添加到 `examples/env.properties`
2. 从各个 `agent.properties` 中移除这两个配置项（可选，保留也能正常工作）
3. 更新代码，在创建 `HydroAgentFactory` 时传递 `env_config` 参数

## 相关文件

### 配置文件
- `examples/env.properties`
- `examples/agents/twins/agent.properties`
- `examples/agents/ontology/agent.properties`
- `examples/agents/centralscheduling/agent.properties`

### 代码文件
- `examples/agents/common.py`
- `examples/simple_multi_agent_example.py`
- `examples/multi_agent_launcher.py`
- `examples/agents/twins/twins_agent.py`
- `examples/agents/ontology/ontology_agent.py`

## 注意事项

1. 如果需要为不同的 agent 配置不同的 cluster_id 或 node_id，可以在各自的 `agent.properties` 中配置，这些配置会被 `env.properties` 覆盖

2. 建议在生产环境中使用环境变量或配置管理工具来管理 `env.properties`

3. 本次重构不影响 `agent_configuration_url` 的加载逻辑，该配置仍从 `SimTaskInitRequest.agent_list` 动态加载
