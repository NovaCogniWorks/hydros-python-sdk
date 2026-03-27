# Hydros Python SDK 对外集成文档

## 1. 文档目的

本文面向 `hydros_agent_sdk` 的外部集成方，提供一份可直接落地的接入说明。目标不是解释 SDK 内部实现细节，而是帮助外部团队完成以下事情：

- 在独立项目中安装并引用 `hydros-agent-sdk`
- 基于 SDK 创建自定义 Agent 工程
- 按 Hydros 协调协议接入中央智能体或协调总线
- 通过一条脚本命令生成可运行的项目骨架

本文属于对外交付文档。关于架构边界、对象模型和演进路线，应以上游 `architect_agent/outputs/` 与 `engineering_agent` 实现结果为准。

## 2. 适用场景

该文档适用于以下外部团队：

- 需要快速开发一个新的水网仿真 Agent
- 需要将现有求解器、规则引擎、优化器封装为 Hydros Agent
- 需要在独立仓库中维护业务逻辑，而不是修改 SDK 源码
- 需要与中央协调端通过 MQTT 指令协议协同运行

不建议的方式：

- 直接在 `hydros_agent_sdk/` 包内部编写业务代码
- 将业务求解逻辑直接塞进 SDK 框架层
- 在未区分 `env.properties` 与 `agent.properties` 职责的情况下混合配置

## 3. 对外集成原则

### 3.1 推荐边界

外部项目应采用“SDK 作为运行时框架，业务项目只承载业务逻辑”的分层方式：

- SDK 负责：协议适配、MQTT 通信、Agent 生命周期、统一工厂创建、多 Agent 宿主管理
- 外部项目负责：业务模型、规则引擎、求解器、具体 Agent 子类、部署配置

### 3.2 推荐集成形态

推荐外部项目采用如下结构：

- `agent_app/`
  存放 Agent 实现、求解器、规则引擎
- `conf/`
  存放 `env.properties` 与 `agent.properties`
- `launcher.py`
  存放单进程启动入口
- `requirements.txt` 或 `pyproject.toml`
  管理外部项目依赖

### 3.3 配置职责口径

建议严格按以下口径拆分配置：

- `env.properties`
  只负责 MQTT、集群、节点等运行环境参数
- `agent.properties`
  只负责 Agent 实例的最小身份配置
- 远程 YAML
  负责正式业务建模参数、控制参数、运行场景参数

## 4. 一键生成项目

### 4.1 交付物

本目录同时提供脚手架脚本：

- [generate-hydros-agent-project.ps1](agent_workspace/execution_agent/outputs/scripts/generate-hydros-agent-project.ps1)

该脚本会生成一个最小可运行的外部 Agent 项目骨架，包含：

- `pyproject.toml`
- `README.md`
- `conf/env.properties`
- `conf/agent.properties`
- `agent_app/agent_impl.py`
- `agent_app/business_engine.py`
- `launcher.py`

### 4.2 执行命令

在 PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\generate-hydros-agent-project.ps1 `
  -ProjectName demo_hydros_agent `
  -OutputDir .\\generated_projects `
  -AgentClass DemoTwinsAgent `
  -AgentCode DEMO_TWINS_AGENT `
  -AgentType TWINS_SIMULATION_AGENT `
  -BaseClass TwinsSimulationAgent
```

执行完成后会生成目录：

```text
.\\generated_projects\\demo_hydros_agent
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

### 4.4 当前脚手架支持的基类模板

脚手架已按当前 SDK 提供的主要 Agent 基类内置模板：

- `TwinsSimulationAgent`
- `OntologySimulationAgent`
- `CentralSchedulingAgent`
- `ModelCalculationAgent`
- `OutflowPlanAgent`

说明：

- Tick 驱动类会生成可处理 `on_tick` 主链路的模板
- 事件驱动类会生成相应的事件回调模板
- 如果传入不在支持列表内的基类，脚手架会中止并报错，避免生成不可运行项目

## 5. 生成后的项目结构

脚手架生成后，目录结构如下：

```text
<ProjectName>/
  agent_app/
    __init__.py
    agent_impl.py
    business_engine.py
  conf/
    env.properties
    agent.properties
  launcher.py
  pyproject.toml
  README.md
```

各目录职责如下：

- `agent_app/business_engine.py`
  放业务求解器、规则引擎或模型计算逻辑
- `agent_app/agent_impl.py`
  放基于 SDK 基类实现的 Agent 子类
- `conf/env.properties`
  放运行环境配置
- `conf/agent.properties`
  放 Agent 身份配置
- `launcher.py`
  放最小启动主程序

## 6. 安装方式

### 6.1 从本地源码仓库安装

如果外部项目与当前 SDK 仓库在同一台机器上，建议先在项目目录执行：

```powershell
pip install -e .
```

### 6.2 从发布包安装

如果后续发布到私有制品库，建议改为：

```powershell
pip install hydros-agent-sdk
```

SDK 当前核心依赖如下：

- `paho-mqtt>=1.6.1`
- `pydantic>=2.0.0`
- `pyyaml>=6.0`

Python 版本要求：

- `Python >= 3.11`

## 7. 最小接入代码

### 7.1 推荐启动入口

```python
from hydros_agent_sdk import (
    SimCoordinationClient,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
)

from agent_app.agent_impl import DemoTwinsAgent


def main():
    env_config = load_env_config('./conf/env.properties')

    factory = HydroAgentFactory(
        agent_class=DemoTwinsAgent,
        config_file='./conf/agent.properties',
        env_config=env_config,
    )

    callback = MultiAgentCallback(node_id=env_config['hydros_node_id'])
    callback.register_agent_factory('DEMO_TWINS_AGENT', factory)

    client = SimCoordinationClient(
        broker_url=env_config['mqtt_broker_url'],
        broker_port=int(env_config['mqtt_broker_port']),
        topic=env_config['mqtt_topic'],
        sim_coordination_callback=callback,
        mqtt_username=env_config.get('mqtt_username'),
        mqtt_password=env_config.get('mqtt_password'),
    )

    callback.set_client(client)
    client.start()

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()


if __name__ == '__main__':
    main()
```

### 7.2 Agent 模板说明

不同基类的最小实现点不同：

- `TwinsSimulationAgent`
  需要重点实现 `_initialize_twins_model()`、`_execute_twins_simulation()`
- `OntologySimulationAgent`
  需要重点实现 `_initialize_ontology_model()`、`_execute_ontology_simulation()`
- `CentralSchedulingAgent`
  需要重点实现 `on_optimization()`
- `ModelCalculationAgent`
  需要重点实现 `on_model_calculation()`
- `OutflowPlanAgent`
  需要重点实现 `on_outflow_time_series()`

脚手架会自动生成对应模板，不需要手工从零搭建。

## 8. 配置文件模板

### 8.1 env.properties

```properties
mqtt_broker_url=tcp://127.0.0.1
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/default_cluster
hydros_cluster_id=default_cluster
hydros_node_id=external_node_001
mqtt_username=
mqtt_password=
```

### 8.2 agent.properties

```properties
agent_code=DEMO_TWINS_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Demo Twins Agent
```

## 9. 与中央智能体的集成链路

外部 Agent 接入后，运行链路可归纳为：

1. 外部项目启动 `launcher.py`
2. `load_env_config()` 加载节点与 MQTT 环境配置
3. `HydroAgentFactory` 基于 `agent.properties` 注册 Agent 工厂
4. `MultiAgentCallback` 负责将请求路由到对应 Agent
5. `SimCoordinationClient` 与中央协调总线建立 MQTT 通道
6. 中央端下发 `SimTaskInitRequest`、`TickCmdRequest`、`SimTaskTerminateRequest` 等命令
7. 外部 Agent 在对应生命周期方法中执行业务逻辑并响应

这条链路说明：

- 外部项目不需要自己实现 MQTT 协议细节
- 外部项目只需要提供 Agent 业务行为和模型逻辑
- 统一协议入口仍由 SDK 维护

## 10. 一键生成后的二次开发建议

生成项目后，建议按以下顺序继续开发：

1. 先修改 `conf/env.properties`，确保能连通测试 MQTT
2. 再修改 `conf/agent.properties`，固定业务身份
3. 然后在 `agent_app/business_engine.py` 中实现真实业务逻辑
4. 最后在 `agent_app/agent_impl.py` 中将业务逻辑挂接到生命周期方法

建议避免以下误区：

- 不要把所有业务逻辑写进 `launcher.py`
- 不要在 `agent_impl.py` 内直接拼接大量配置解析逻辑
- 不要把外部业务状态直接写回 SDK 框架层代码

## 11. 验证建议

外部项目接入后，至少要做三层检查：

### 11.1 静态检查

- `agent.properties` 字段齐全
- `env.properties` 字段齐全
- Agent 类确实继承自正确的 SDK 基类

### 11.2 启动检查

- 项目可以成功导入 `hydros_agent_sdk`
- `SimCoordinationClient` 可正常启动
- 能看到连接 MQTT 与订阅主题日志

### 11.3 协议联调检查

- 能正确处理初始化命令
- 能正确处理 Tick 命令或事件命令
- 能正确处理终止命令
- 返回报文中的 `command_status` 与 `source_agent_instance` 合法

## 12. 典型扩展方向

如果后续要进一步增强外部项目，可以沿以下方向扩展：

- 增加多 Agent 单进程托管能力
- 接入远程 YAML 业务配置
- 将求解器、规则引擎、预测模型拆为独立模块
- 为后续 DMPC 局部控制器预留输入输出对象层

## 13. 结论

对外集成的正确方式，不是复制 SDK 内部实现，而是让外部项目以最小成本复用 SDK 的运行时骨架。

当前推荐的最稳妥路径是：

- 用脚手架脚本一键生成项目骨架
- 用 `HydroAgentFactory + MultiAgentCallback + SimCoordinationClient` 完成接入
- 用独立的 `agent_app` 承载业务逻辑
- 用 `conf/` 管理环境配置与 Agent 身份配置

这样既能快速落地，也不会破坏 SDK 后续演进空间。


