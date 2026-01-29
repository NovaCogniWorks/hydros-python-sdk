# Quick Start Guide - Hydro Agent with Configuration File

## 快速开始

### 1. 准备配置文件

编辑 `examples/agent.properties`：

```bash
vim examples/agent.properties
```

确保包含以下必需配置：

```properties
# 必需配置
agent_code=YOUR_AGENT_CODE
agent_type=YOUR_AGENT_TYPE
agent_name=Your Agent Name
agent_configuration_url=http://your-server.com/config.yaml

# 可选配置
drive_mode=SIM_TICK_DRIVEN
hydros_cluster_id=your_cluster
hydros_node_id=your_node
```

### 2. 验证配置

```bash
python3 examples/test_config.py
```

应该看到：
```
✓ All required configuration properties are present
```

### 3. 运行示例

```bash
python3 examples/agent_example.py
```

## 配置说明

### agent_code
- **说明**：Agent 的唯一标识代码
- **示例**：`TWINS_SIMULATION_AGENT`
- **用途**：用于标识 agent 类型，会作为 agent_id 的前缀

### agent_type
- **说明**：Agent 的类型分类
- **示例**：`TWINS_SIMULATION_AGENT`
- **用途**：用于 agent 分类和管理

### agent_name
- **说明**：Agent 的可读名称
- **示例**：`Twins Simulation Agent`
- **用途**：日志和监控中显示的名称

### agent_configuration_url
- **说明**：Agent 详细配置文件的 URL
- **示例**：`http://example.com/config/twins-agent.yaml`
- **用途**：指向包含 agent 详细配置的远程文件

### drive_mode
- **说明**：Agent 的驱动模式
- **可选值**：
  - `SIM_TICK_DRIVEN` - 时钟节拍驱动（默认）
  - `EVENT_DRIVEN` - 事件驱动
  - `PROACTIVE` - 主动模式
- **默认值**：`SIM_TICK_DRIVEN`

### hydros_cluster_id
- **说明**：Hydros 集群 ID
- **默认值**：`default_cluster`

### hydros_node_id
- **说明**：Hydros 节点 ID
- **默认值**：`default_node`

## 常见问题

### Q: 配置文件找不到怎么办？

**A:** 确保配置文件路径正确，默认路径是 `examples/agent.properties`。如果使用自定义路径：

```python
agent_factory = MySampleAgentFactory(
    config_file="path/to/your/config.properties"
)
```

### Q: 缺少必需配置会怎样？

**A:** 程序会抛出 `ValueError` 异常，明确指出缺少哪些配置：

```
ValueError: Missing required properties in agent.properties: agent_code, agent_name
```

### Q: 可以在代码中覆盖配置吗？

**A:** 不可以。所有配置必须从配置文件加载，这是为了保证配置的一致性和可追溯性。

### Q: 如何使用多个不同的 agent 配置？

**A:** 创建多个配置文件，然后在创建 factory 时指定不同的配置文件：

```python
# Agent 1
factory1 = MySampleAgentFactory(config_file="agent1.properties")

# Agent 2
factory2 = MySampleAgentFactory(config_file="agent2.properties")
```

### Q: 配置文件支持注释吗？

**A:** 支持。使用 `#` 开头的行会被视为注释：

```properties
# 这是注释
agent_code=TWINS_SIMULATION_AGENT  # 行尾注释也支持
```

## 完整示例

### 配置文件 (agent.properties)

```properties
# Hydro Agent Configuration
agent_code=TWINS_SIMULATION_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Twins Simulation Agent
agent_configuration_url=http://example.com/config/twins-agent.yaml
drive_mode=SIM_TICK_DRIVEN
hydros_cluster_id=production_cluster
hydros_node_id=node_001
```

### Python 代码

```python
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from examples.agent_example import MySampleAgentFactory, MultiAgentCoordinationCallback

# 配置
BROKER_URL = "tcp://192.168.1.24"
BROKER_PORT = 1883
TOPIC = "/hydros/commands/coordination/my_topic"
CONFIG_FILE = "examples/agent.properties"

# 创建 factory 和 callback
agent_factory = MySampleAgentFactory(config_file=CONFIG_FILE)
callback = MultiAgentCoordinationCallback(
    agent_factory=agent_factory,
    config_file=CONFIG_FILE
)

# 创建并启动客户端
client = SimCoordinationClient(
    broker_url=BROKER_URL,
    broker_port=BROKER_PORT,
    topic=TOPIC,
    callback=callback
)

callback.set_sim_coordination_client(client)
client.start()

# 保持运行
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.stop()
```

## 下一步

- 阅读 [AGENT_CONFIG.md](AGENT_CONFIG.md) 了解配置详情
- 阅读 [REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md) 了解重构细节
- 查看 [agent_example.py](agent_example.py) 了解完整实现

## 获取帮助

如果遇到问题：

1. 运行 `python3 examples/test_config.py` 验证配置
2. 检查日志输出中的错误信息
3. 确认配置文件格式正确（无多余空格、正确的键值对）
