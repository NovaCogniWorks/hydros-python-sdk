# Hydros Agent SDK Examples

本目录只保留可以被当前 SDK launcher 自动发现并启动的示例。示例用于展示推荐的 Agent 目录布局、配置文件和业务逻辑拆分方式。

## 目录结构

```text
examples/
├── env.properties.example
├── start_agents.sh
├── error_handling_example.py
└── agents/
    ├── centralscheduling/
    │   ├── agent.properties
    │   └── central_scheduling_agent.py
    ├── template/
    │   ├── README.md
    │   ├── agent.properties
    │   └── template_agent.py
    ├── ontology/
    │   ├── README.md
    │   ├── agent.properties
    │   ├── ontology_agent.py
    │   └── ontology_rule_engine.py
    └── twins/
        ├── README.md
        ├── agent.properties
        ├── twins_agent.py
        ├── hydraulic_solver.py
        └── simulation_states.py
```

当前真实可用的示例：

- `template`：最小 `TickableAgent` 模板，适合复制成新 Agent。
- `twins`：孪生仿真 Agent，展示 `TwinsSimulationAgent` 与业务 solver 拆分。
- `ontology`：本体推理仿真 Agent，展示 `OntologySimulationAgent` 与规则引擎拆分。
- `centralscheduling`：中央调度 Agent，展示 `MpcCentralSchedulingAgent` 的生产化薄封装。

## 快速运行

从仓库根目录准备示例环境配置：

```bash
cp examples/env.properties.example examples/env.properties
```

编辑 `examples/env.properties`，填写 MQTT broker、cluster 和 node。

列出可用示例：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples -- --list
```

启动前检查：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples -- --check
```

启动单个示例：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples -- template
```

启动多个示例：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples -- twins ontology
```

也可以使用脚本包装：

```bash
cd examples
./start_agents.sh --list
./start_agents.sh --check
./start_agents.sh twins ontology
./start_agents.sh --debug twins
```

## 如何新增示例 Agent

1. 在 `examples/agents/` 下创建新目录，例如 `myagent/`。
2. 添加 `agent.properties`，包含 `agent_code`、`agent_type`、`agent_name`。
3. 添加 Python 文件，实现 `BaseHydroAgent` 的子类。
4. 将业务算法放入独立模块，不要塞进 launcher。
5. 运行 `python -m hydros_agent_sdk.launcher --launcher-dir examples -- myagent`。

最小 `agent.properties`：

```properties
agent_code=MY_AGENT
agent_type=MY_AGENT
agent_name=My Agent
```

launcher 的发现规则是：`examples/agents/<agent>/` 内存在 `agent.properties`，并且目录中有继承 `BaseHydroAgent` 的 Python 类。

## SDK 代码和示例代码边界

`hydros_agent_sdk/` 是 SDK 框架代码，示例开发者通常不应修改。

可以修改或复制的内容：

- `examples/agents/<agent>/agent.properties`
- `examples/agents/<agent>/*_agent.py`
- `examples/agents/<agent>/` 下的业务 solver、rule engine、adapter 模块
- `examples/env.properties` 的本地副本

真实环境配置不应提交；提交 `env.properties.example` 模板即可。

## 调试

安装 debug 依赖：

```bash
pip install -e ".[debug]"
```

启动远程调试：

```bash
./start_agents.sh --debug twins
```

然后用 IDE attach 到 `localhost:5678`。更多信息见 [DEBUG_GUIDE.md](DEBUG_GUIDE.md)。

## 相关文档

- [根 README](../README.md)
- [文档中心](../docs/README.md)
- [新手智能体开发指南](../docs/新手智能体开发指南.md)
- [测试基线](../docs/TESTING_BASELINE.md)
