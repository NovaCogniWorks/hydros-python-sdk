# Examples Directory - README

本目录包含 Hydros Agent SDK 的示例代码、配置文件和工具脚本。

## 📁 文件清单

### 核心示例文件

| 文件 | 说明 |
|------|------|
| `agent_example.py` | 完整的 Agent 实现示例，展示如何使用配置文件创建和管理 Agent |
| `agent.properties` | Agent 配置文件（agent_code, agent_type, agent_name 等） |
| `env.properties` | 环境配置文件（MQTT broker 连接设置） |
| `agent_alternative.properties` | 替代配置示例（DATA_ANALYSIS_AGENT） |

### 工具脚本

| 文件 | 说明 | 用法 |
|------|------|------|
| `test_config.py` | Agent 配置文件验证工具 | `python3 examples/test_config.py` |
| `test_env.py` | 环境配置文件验证工具 | `python3 examples/test_env.py` |
| `generate_config.py` | 交互式配置文件生成器 | `python3 examples/generate_config.py` |

### 文档文件

| 文件 | 说明 |
|------|------|
| `QUICKSTART.md` | 快速开始指南 |
| `AGENT_CONFIG.md` | 配置文件详细说明 |
| `REFACTORING_SUMMARY.md` | 配置重构总结 |
| `CHANGELOG.md` | 详细变更日志 |
| `README.md` | 本文件 |

---

## 🚀 快速开始

### 1. 使用默认配置运行示例

```bash
# 验证 Agent 配置
python3 examples/test_config.py

# 验证环境配置
python3 examples/test_env.py

# 运行示例（需要 MQTT broker）
python3 examples/agent_example.py
```

### 2. 创建自定义配置

#### 配置 Agent 属性

**方式 A: 使用配置生成器（推荐）**

```bash
python3 examples/generate_config.py
```

按照提示输入配置信息，工具会自动生成配置文件。

**方式 B: 手动创建**

```bash
cp examples/agent.properties examples/my_agent.properties
vim examples/my_agent.properties
```

编辑配置文件，修改以下必需字段：
- `agent_code`
- `agent_type`
- `agent_name`
- `agent_configuration_url`

#### 配置 MQTT 连接

编辑 `examples/env.properties`：

```bash
vim examples/env.properties
```

修改以下字段：
- `mqtt_broker_url` - MQTT broker 地址
- `mqtt_broker_port` - MQTT broker 端口
- `mqtt_topic` - MQTT 主题

### 3. 使用自定义配置

```python
from examples.agent_example import MySampleAgentFactory, MultiAgentCoordinationCallback

# 使用自定义配置文件
factory = MySampleAgentFactory(config_file="examples/my_agent.properties")
callback = MultiAgentCoordinationCallback(
    agent_factory=factory,
    config_file="examples/my_agent.properties"
)
```

---

## 📋 配置文件格式

### Agent 配置 (agent.properties)

**必需字段：**

```properties
agent_code=YOUR_AGENT_CODE
agent_type=YOUR_AGENT_TYPE
agent_name=Your Agent Name
agent_configuration_url=http://your-server.com/config.yaml
```

**可选字段：**

```properties
drive_mode=SIM_TICK_DRIVEN
hydros_cluster_id=default_cluster
hydros_node_id=default_node
```

详见：[AGENT_CONFIG.md](AGENT_CONFIG.md)

### 环境配置 (env.properties)

**必需字段：**

```properties
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/your_topic
```

详见：[ENV_CONFIG.md](ENV_CONFIG.md)

---

## 🛠️ 工具使用说明

### test_config.py - 配置验证工具

验证配置文件是否包含所有必需字段。

```bash
# 验证默认配置
python3 examples/test_config.py

# 输出示例
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

============================================================
✓ All required configuration properties are present
============================================================
```

### generate_config.py - 配置生成器

交互式创建新的配置文件。

```bash
python3 examples/generate_config.py

# 示例交互
======================================================================
Hydro Agent Configuration Generator
======================================================================

This wizard will help you create a new agent.properties file.
Press Ctrl+C at any time to cancel.

Required Configuration:
----------------------------------------------------------------------
Agent Code (unique identifier) [MY_AGENT]: DATA_PROCESSOR
Agent Type (classification) [DATA_PROCESSOR]:
Agent Name (human-readable) [Data Processor]: Data Processing Agent
Configuration URL [http://example.com/config/data_processor.yaml]:

Optional Configuration:
----------------------------------------------------------------------
Drive Mode options: SIM_TICK_DRIVEN, EVENT_DRIVEN, PROACTIVE
Drive Mode [SIM_TICK_DRIVEN]: EVENT_DRIVEN
Hydros Cluster ID [default_cluster]: processing_cluster
Hydros Node ID [default_node]: processor_01

======================================================================
Configuration Preview:
======================================================================
# Hydro Agent Configuration
# Generated for: Data Processing Agent

# Agent identification (Required)
agent_code=DATA_PROCESSOR
agent_type=DATA_PROCESSOR
agent_name=Data Processing Agent
...
```

---

## 📖 文档指南

### 新手入门

1. **QUICKSTART.md** - 从这里开始
   - 5分钟快速上手
   - 配置说明
   - 常见问题

### 深入了解

2. **AGENT_CONFIG.md** - 配置详解
   - 所有配置项的详细说明
   - 配置示例
   - 最佳实践

3. **REFACTORING_SUMMARY.md** - 重构说明
   - 为什么要使用配置文件
   - 新旧 API 对比
   - 迁移指南

4. **CHANGELOG.md** - 变更历史
   - 详细的变更记录
   - 破坏性变更说明
   - 回滚指南

---

## 💡 使用场景

### 场景 1: 开发环境测试

```bash
# 使用默认配置快速测试
python3 examples/agent_example.py
```

### 场景 2: 多环境部署

```bash
# 为不同环境创建配置
examples/
  ├── agent.dev.properties      # 开发环境
  ├── agent.staging.properties  # 测试环境
  └── agent.prod.properties     # 生产环境
```

```python
import os

env = os.getenv('ENV', 'dev')
config_file = f"examples/agent.{env}.properties"

factory = MySampleAgentFactory(config_file=config_file)
```

### 场景 3: 多 Agent 系统

```python
# 创建多个不同类型的 Agent
agents = [
    MySampleAgentFactory(config_file="examples/agent_twins.properties"),
    MySampleAgentFactory(config_file="examples/agent_analysis.properties"),
    MySampleAgentFactory(config_file="examples/agent_monitor.properties"),
]
```

---

## ⚠️ 注意事项

### 配置文件安全

- ❌ 不要在配置文件中存储敏感信息（密码、密钥等）
- ✅ 使用环境变量或密钥管理服务存储敏感信息
- ✅ 将包含敏感信息的配置文件添加到 `.gitignore`

### 配置文件位置

- 默认位置：`examples/agent.properties`
- 可以使用相对路径或绝对路径
- 确保运行时配置文件可访问

### MQTT Broker 配置

示例代码中的 MQTT broker 配置是硬编码的：

```python
BROKER_URL = "tcp://192.168.1.24"
BROKER_PORT = 1883
TOPIC = "/hydros/commands/coordination/weijiahao"
```

在生产环境中，建议：
- 使用环境变量配置 MQTT broker
- 或者扩展配置文件支持 MQTT 配置

---

## 🔧 故障排查

### 问题 1: 配置文件找不到

```
FileNotFoundError: Config file not found: examples/agent.properties
```

**解决方案：**
- 检查文件路径是否正确
- 确保从正确的目录运行脚本
- 使用绝对路径

### 问题 2: 缺少必需配置

```
ValueError: Missing required properties in agent.properties: agent_code, agent_name
```

**解决方案：**
- 运行 `python3 examples/test_config.py` 检查配置
- 确保所有必需字段都已定义
- 参考 `agent.properties` 示例

### 问题 3: 配置格式错误

```
Error loading config file: ...
```

**解决方案：**
- 检查配置文件格式（key=value）
- 确保没有多余的空格或特殊字符
- 使用 `generate_config.py` 生成标准格式

---

## 📚 相关资源

### SDK 文档

- [CLAUDE.md](../CLAUDE.md) - SDK 架构和开发指南
- [DEVELOPMENT.md](../DEVELOPMENT.md) - 开发环境设置

### 外部资源

- [Paho MQTT Python Client](https://www.eclipse.org/paho/index.php?page=clients/python/index.php)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Python ConfigParser](https://docs.python.org/3/library/configparser.html)

---

## 🤝 贡献

如果你有改进建议或发现问题：

1. 创建 Issue 描述问题
2. 提交 Pull Request 修复问题
3. 更新相关文档

---

## 📝 许可证

本项目使用 MIT 许可证。详见 [LICENSE](../LICENSE) 文件。

---

## 📞 获取帮助

- 查看文档：从 `QUICKSTART.md` 开始
- 运行测试：`python3 examples/test_config.py`
- 生成配置：`python3 examples/generate_config.py`
- 查看示例：`python3 examples/agent_example.py --help`

---

**最后更新**: 2026-01-29
