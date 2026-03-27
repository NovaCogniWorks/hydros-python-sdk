# Hydros Python SDK 对外集成文档

## 1. 文档目的

本文面向 `hydros_agent_sdk` 的外部集成方，提供一份可直接落地的接入说明。目标不是解释 SDK 内部实现细节，而是帮助外部团队完成以下事情：

- 在独立项目中引用 `hydros_agent_sdk`
- 基于脚手架快速生成可运行的外部 Agent 工程
- 以最小改造成本接入 Hydros 协调协议与 MQTT 总线
- 将业务逻辑收敛到少量外部文件，而不是修改 SDK 源码

本文属于对外交付文档。关于架构边界、对象模型和演进路线，应以上游 `architect_agent/outputs/` 与 `engineering_agent` 实现结果为准。

## 2. 适用场景

该文档适用于以下外部团队：

- 需要快速开发新的水网仿真 Agent
- 需要将现有求解器、规则引擎、优化器封装为 Hydros Agent
- 需要在独立仓库中维护业务逻辑，而不是修改 SDK 源码
- 需要与中央协调端通过 MQTT 指令协议协同运行

不建议的方式：

- 直接在 `hydros_agent_sdk/` 包内部编写业务代码
- 将业务求解逻辑直接塞进 SDK 框架层
- 在未区分 `env.properties`、`agent.properties`、远程 YAML 职责的情况下混合配置

## 3. 对外集成原则

### 3.1 推荐边界

外部项目应采用“SDK 负责运行时，业务项目只承载业务逻辑”的分层方式：

- SDK 负责：协议适配、MQTT 通信、Agent 生命周期、统一工厂创建、多 Agent 宿主管理
- 外部项目负责：业务模型、规则引擎、求解器、业务参数配置、少量 Agent 扩展代码

### 3.2 最小集成面

当前脚手架的推荐接入面收敛为 3 处：

- `conf/env.properties`
  配置 MQTT、节点、主题等运行环境参数
- `conf/agent.properties`
  配置 Agent 身份和模板参数
- `agent_app/user_logic.py`
  编写求解器调用、规则推理、优化计划或事件处理逻辑

默认情况下，外部用户不需要修改以下文件：

- `agent_app/runtime.py`
- `agent_app/support.py`
- `agent_app/business_engine.py`
- `agent_app/agent_impl.py`

只有在需要高级运行时定制、生命周期扩展或协议钩子扩展时，才建议继续修改这些文件。

### 3.3 配置职责口径

建议严格按以下口径拆分配置：

- `env.properties`
  只负责 MQTT、集群、节点等运行环境参数
- `agent.properties`
  只负责 Agent 实例身份和脚手架级别的轻量参数
- 远程 YAML
  负责正式业务建模参数、控制参数、运行场景参数

## 4. 一键生成项目

### 4.1 交付物

本目录同时提供脚手架脚本：

- [generate-hydros-agent-project.ps1](/F:/sl/sdk/hydros-python-sdk/agent_workspace/execution_agent/outputs/scripts/generate-hydros-agent-project.ps1)

该脚本会生成一个最小可运行的外部 Agent 项目骨架，包含：

- `pyproject.toml`
- `README.md`
- `conf/env.properties`
- `conf/agent.properties`
- `agent_app/user_logic.py`
- `agent_app/business_engine.py`
- `agent_app/agent_impl.py`
- `agent_app/runtime.py`
- `agent_app/support.py`
- `agent_app/service.py`
- `scripts/bootstrap.ps1`
- `scripts/run.ps1`
- `tests/test_scaffold_import.py`
- `launcher.py`

### 4.2 执行命令

在 PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\agent_workspace\execution_agent\outputs\scripts\generate-hydros-agent-project.ps1 `
  -ProjectName demo_hydros_agent `
  -OutputDir .\generated_projects `
  -AgentClass DemoTwinsAgent `
  -AgentCode TWINS_SIMULATION_AGENT_demo001 `
  -AgentType TWINS_SIMULATION_AGENT `
  -BaseClass TwinsSimulationAgent `
  -Template twins
```

```powershell
powershell -ExecutionPolicy Bypass -File .\generate-hydros-agent-project.ps1 `
  -ProjectName demo_hydros_agent `
  -OutputDir .\generated_projects `
  -AgentClass DemoTwinsAgent `
  -AgentCode CENTRAL_SCHEDULING_AGENT_POWER `
  -AgentType CENTRAL_SCHEDULING_AGENT `
  -BaseClass CentralSchedulingAgent `
  -Template central
```

执行完成后会生成目录：

```text
.\generated_projects\demo_hydros_agent
```

### 4.3 参数说明

- `ProjectName`
  外部项目目录名，同时会写入 `pyproject.toml`
- `OutputDir`
  项目输出根目录
- `AgentClass`
  生成的 Agent Python 类名
- `AgentCode`
  Agent 唯一业务编码
- `AgentType`
  Agent 类型，需与实际场景约定一致
- `BaseClass`
  继承的 SDK 基类
- `Template`
  脚手架模板，可选 `auto`、`twins`、`ontology`、`central`
- `SdkRoot`
  可选，手工指定 SDK 源码根目录

### 4.4 当前脚手架支持的基类模板

脚手架已按当前 SDK 提供的主要 Agent 基类内置模板：

- `TwinsSimulationAgent`
- `OntologySimulationAgent`
- `CentralSchedulingAgent`
- `ModelCalculationAgent`
- `OutflowPlanAgent`

说明：

- `auto` 会根据 `BaseClass` 自动选择模板
- Tick 驱动类会生成可处理主链路的模板
- 事件驱动类会生成对应事件回调模板
- 如果传入不匹配的模板和基类组合，脚手架会中止并报错，避免生成不可运行项目

## 5. 生成后的项目结构

脚手架生成后，目录结构如下：

```text
<ProjectName>/
  agent_app/
    __init__.py
    user_logic.py
    business_engine.py
    agent_impl.py
    runtime.py
    support.py
    service.py
  conf/
    env.properties
    agent.properties
  scripts/
    bootstrap.ps1
    run.ps1
  tests/
    test_scaffold_import.py
  launcher.py
  pyproject.toml
  README.md
```

各目录职责如下：

- `agent_app/user_logic.py`
  默认业务入口，放求解器调用、规则引擎、事件处理和指标映射
- `agent_app/business_engine.py`
  适配层，负责把业务逻辑挂到模板化运行时接口上
- `agent_app/agent_impl.py`
  放基于 SDK 基类实现的 Agent 子类模板
- `agent_app/runtime.py`
  放运行时启动装配、日志初始化和客户端创建
- `agent_app/support.py`
  放生命周期辅助逻辑和指标消息转换
- `conf/env.properties`
  放运行环境配置
- `conf/agent.properties`
  放 Agent 身份配置和模板参数
- `scripts/bootstrap.ps1`
  创建 `.venv` 并通过 `.pth` 链接项目源码和 SDK 源码
- `scripts/run.ps1`
  用虚拟环境解释器启动 `launcher.py`
- `tests/test_scaffold_import.py`
  用于导入链路和配置加载烟测

## 6. 安装与启动方式

### 6.1 推荐方式：执行 bootstrap 脚本

如果外部项目与 SDK 源码在同一台机器上，推荐直接在生成项目目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

说明：

- `bootstrap.ps1` 会创建 `.venv`
- 脚本通过 `.pth` 将生成项目根目录和 SDK 源码根目录加入 Python 路径
- 这种方式不依赖 `pip install -e`，更适合当前 SDK 源码直连集成场景

### 6.2 依赖要求

如果宿主环境未提供以下依赖，需要安装到 `.venv`：

- `paho-mqtt>=1.6.1`
- `pydantic>=2.0.0`
- `pyyaml>=6.0`

Python 版本要求：

- `Python >= 3.11`

### 6.3 启动与验证命令

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
.\.venv\Scripts\python.exe -m unittest tests.test_scaffold_import
```

## 7. 最小接入流程

推荐按以下顺序完成外部集成：

1. 执行 `scripts/bootstrap.ps1`
2. 修改 `conf/env.properties`，确认 MQTT、节点、主题配置正确
3. 修改 `conf/agent.properties`，确认 Agent 身份和模板参数正确
4. 在 `agent_app/user_logic.py` 中实现业务逻辑
5. 运行 `scripts/run.ps1`
6. 执行 `tests/test_scaffold_import.py` 做本地烟测

### 7.1 user_logic.py 的职责

不同模板下，`user_logic.py` 会暴露不同的主入口方法：

- `twins` 模板
  重点实现 `simulate_twins_step()`
- `ontology` 模板
  重点实现 `run_ontology_reasoning()`
- `central` 模板
  重点实现 `build_dispatch_plan()`，并按需扩展事件处理方法

同时保留以下通用方法：

- `initialize()`
- `collect_boundary_conditions()`
- `handle_event()`
- `shutdown()`

### 7.2 何时修改其他文件

只有在以下场景才建议修改其他骨架文件：

- 需要扩展生命周期钩子时，修改 `agent_app/agent_impl.py`
- 需要调整运行时装配或日志初始化时，修改 `agent_app/runtime.py`
- 需要新增指标转换或统一辅助逻辑时，修改 `agent_app/support.py`
- 需要替换适配层抽象时，修改 `agent_app/business_engine.py`

## 8. 最小接入代码说明

脚手架已经内置最小启动链路：

- `launcher.py`
  调用 `agent_app.service.main()`
- `agent_app/service.py`
  调用运行时入口 `run_agent_service()`
- `agent_app/runtime.py`
  装配 `HydroAgentFactory + MultiAgentCallback + SimCoordinationClient`

因此外部项目通常不需要从零编写启动入口，也不需要自己手工拼装 MQTT 客户端。

## 9. 配置文件模板

### 9.1 env.properties

```properties
mqtt_broker_url=tcp://127.0.0.1
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/default_cluster
hydros_cluster_id=default_cluster
hydros_node_id=external_node_001
mqtt_username=
mqtt_password=
metrics_topic=/hydros/metrics/{hydros_cluster_id}
```

说明：

- `central` 风格模板会额外生成 `control_command_topic`

### 9.2 agent.properties

`agent.properties` 会根据模板生成不同默认参数。

Twins 示例：

```properties
agent_code=DEMO_TWINS_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=DemoTwinsAgent
time_step=60
convergence_tolerance=1e-6
max_iterations=100
boundary_condition_metrics=inflow,upstream_water_level
solver_mode=hydraulic
```

说明：

- `ontology` 模板会生成 `reasoning_mode`、`rule_file`、`inference_depth` 等参数
- `central` 模板会按 `BaseClass` 生成调度、模型计算或下泄规划相关参数

## 10. 与中央智能体的集成链路

外部 Agent 接入后，运行链路可归纳为：

1. 外部项目启动 `launcher.py`
2. `runtime.py` 加载 `env.properties`
3. `HydroAgentFactory` 基于 `agent.properties` 注册 Agent 工厂
4. `MultiAgentCallback` 负责将请求路由到对应 Agent
5. `SimCoordinationClient` 与中央协调总线建立 MQTT 通道
6. 中央端下发 `SimTaskInitRequest`、`TickCmdRequest`、`SimTaskTerminateRequest` 或业务事件命令
7. 生成的 Agent 模板把请求委托给 `business_engine.py`
8. `business_engine.py` 再委托给 `user_logic.py` 执行业务逻辑

这条链路说明：

- 外部项目不需要自己实现 MQTT 协议细节
- 外部项目主要只需要提供业务逻辑和业务参数
- 统一协议入口和宿主运行时仍由 SDK 维护

## 11. 二次开发建议

生成项目后，建议遵循以下原则：

- 优先只改 `conf/` 和 `agent_app/user_logic.py`
- 不要把所有业务逻辑写进 `launcher.py`
- 不要在 `agent_impl.py` 中直接堆叠大量配置解析逻辑
- 不要把外部业务状态直接写回 SDK 框架层代码
- DMPC 或复杂业务参数优先进入远程 YAML，而不是继续堆进 `agent.properties`

## 12. 验证建议

外部项目接入后，至少要做三层检查：

### 12.1 脚手架完整性检查

- `conf/env.properties` 存在
- `conf/agent.properties` 存在
- `agent_app/user_logic.py` 存在
- `agent_app/runtime.py`、`agent_app/support.py` 存在
- `launcher.py` 存在

### 12.2 启动检查

- 项目可以成功导入 `hydros_agent_sdk`
- `scripts/bootstrap.ps1` 可以成功执行
- `SimCoordinationClient` 可正常启动
- 能看到连接 MQTT 与订阅主题日志

### 12.3 协议联调检查

- 能正确处理初始化命令
- 能正确处理 Tick 命令或事件命令
- 能正确处理终止命令
- 返回报文中的 `command_status` 与 `source_agent_instance` 合法

## 13. 结论

对外集成的正确方式，不是复制 SDK 内部实现，而是让外部项目以最小成本复用 SDK 的运行时骨架。

当前推荐的最稳妥路径是：

- 用脚手架脚本一键生成项目骨架
- 执行 `scripts/bootstrap.ps1` 完成本地源码直连
- 用 `conf/env.properties` 和 `conf/agent.properties` 完成配置
- 用 `agent_app/user_logic.py` 承载主要业务逻辑
- 仅在确有必要时再修改 `agent_impl.py`、`runtime.py` 或 `business_engine.py`

这样既能快速落地，也不会破坏 SDK 后续演进空间。
