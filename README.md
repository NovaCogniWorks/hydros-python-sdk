# Hydros Agent SDK

Hydros Agent SDK 是 Hydros 生态的 Python Agent 开发包，用于编写、启动和调试通过 MQTT 与协调器通信的仿真智能体。

本仓库的推荐接入路径是：

1. 安装 SDK 最小依赖。
2. 准备本地 `env.properties`。
3. 用统一 launcher 列出并启动示例 agent。
4. 基于 `examples/agents/` 中真实存在的示例创建自己的 agent。
5. 用测试基线脚本验证 SDK 主链路。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

准备本地环境配置：

```bash
$EDITOR env.properties
$EDITOR examples/env.properties
```

编辑 `env.properties` 或 `examples/env.properties`，至少填写：

```properties
mqtt_broker_url=tcp://127.0.0.1
mqtt_broker_port=1883
hydros_cluster_id=local-dev
hydros_node_id=local
```

列出当前示例：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples -- --list
```

当前 `examples/agents/` 下维护的示例是：

- `template`：最小 `TickableAgent` 模板，适合作为新 Agent 起点。
- `twins`：孪生仿真 agent 示例。
- `ontology`：本体推理仿真 agent 示例。
- `centralscheduling`：中央调度 agent 示例，复用 SDK 默认 MPC 路径。

检查示例目录：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples -- --check
```

启动一个示例：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples -- template
```

也可以使用脚本包装：

```bash
cd examples
./start_agents.sh --list
./start_agents.sh --check
./start_agents.sh twins ontology
```

安装后也可以使用 console script：

```bash
hydros-agent --launcher-dir examples -- --list
```

## 创建自己的 Agent

推荐目录结构：

```text
my-app/
├── env.properties
└── agents/
    └── myagent/
        ├── agent.properties
        └── my_agent.py
```

`agent.properties` 至少包含：

```properties
agent_code=MY_AGENT
agent_type=MY_AGENT
agent_name=My Agent
```

`my_agent.py` 中实现根包公开的 `CustomAgent`，通过 `AgentExecutionContext` 读取 Agent 身份、任务上下文和配置。最小模板可参考 `examples/agents/template`；SDK 内建的高级 Agent 基类只从 `hydros_agent_sdk.agents` 显式导入。

启动自定义目录：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir my-app -- myagent
```

launcher 会自动发现 `launcher-dir/agents/<agent>/agent.properties` 和目录内的 `CustomAgent` 实现。

## 依赖分层

最小 SDK 安装：

```bash
pip install -e .
```

按需安装附加依赖：

```bash
pip install -e ".[debug]"
pip install -e ".[build]"
pip install -e ".[pump]"
pip install -e ".[power]"
```

`requirements.txt` 只保留 SDK 运行依赖；业务仿真、构建发布、远程调试依赖通过 `pyproject.toml` 的 optional dependencies 按需安装，避免第一次接入时安装完整业务栈。

## 测试基线

日常 SDK 绿线：

```bash
python scripts/run_test_baseline.py sdk
python scripts/run_test_baseline.py compile
```

修改 router、multi-agent、protocol event/command 时：

```bash
python scripts/run_test_baseline.py central-router
python scripts/run_test_baseline.py compile
```

查看全部基线：

```bash
python scripts/run_test_baseline.py list
```

## 文档入口

- [文档中心](docs/README.md)
- [新手智能体开发指南](docs/新手智能体开发指南.md)
- [示例工程导航](examples/README.md)
- [测试基线](docs/TESTING_BASELINE.md)
- [故障排查指南](docs/故障排查指南.md)

## 配置文件约定

真实 `env.properties` 只属于本地或部署环境，不应提交到仓库。新增示例或自定义 Agent 时，在 README 中说明必需配置项即可，不再提交环境配置模板。

如果本地已有被 Git 跟踪的真实配置，需要在提交中将其从索引移除但保留本地文件：

```bash
git rm --cached env.properties examples/env.properties custom-agent/pump/env.properties custom-agent/power/env.properties
```

执行前请确认这些文件没有需要提交的模板内容。
