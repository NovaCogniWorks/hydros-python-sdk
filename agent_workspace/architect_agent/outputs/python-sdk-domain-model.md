# Python SDK 领域模型说明书

## 1. 文档目的

本文定义 `hydros_agent_sdk` 在 Python 侧暴露的核心领域对象、对象边界和对象关系，用于统一 Python SDK 的业务抽象口径，并为后续中央协调、仿真 Agent 与 DMPC 局部控制器接入提供稳定的语义基线。

## 2. 建模原则

Python SDK 的领域建模遵循以下原则：

- 协议对象与运行时行为对象分层
- 模板配置与运行实例分层
- 任务身份、Agent 身份、对象时序、命令响应四类对象分离
- 尽量与 Java 协同协议模型对齐
- 保持对未来 DMPC 对象的扩展兼容，不提前把高层控制语义硬编码进基础层

## 3. 领域分层

### 3.1 身份与上下文层

核心对象：

- `Tenant`
- `BizScenario`
- `Waterway`
- `SimulationContext`

职责：

- 标识租户、业务场景和水网
- 提供任务实例身份 `biz_scene_instance_id`
- 作为多任务隔离的主键

说明：

- `SimulationContext` 是整个 Python SDK 运行时最核心的隔离键
- 绝大多数命令和 Agent 实例都挂靠在它之下

### 3.2 Agent 定义与实例层

核心对象：

- `HydroAgent`
- `HydroAgentInstance`
- `BaseHydroAgent`

职责：

- `HydroAgent` 表示场景中的 Agent 定义信息
- `HydroAgentInstance` 表示运行中的 Agent 实例
- `BaseHydroAgent` 在实例对象之上叠加生命周期行为和运行时依赖

说明：

- Python SDK 采用“实例对象继承后加行为”的设计，而不是把行为和数据拆成两个完全独立对象
- 这简化了业务 Agent 编写，但也意味着 `BaseHydroAgent` 是协议对象和行为对象的复合体

### 3.3 协议命令层

核心对象：

- `SimTaskInitRequest / Response`
- `TickCmdRequest / Response`
- `SimTaskTerminateRequest / Response`
- `TimeSeriesDataUpdateRequest / Response`
- `TimeSeriesCalculationRequest / Response`
- `OutflowTimeSeriesRequest / Response`
- `AgentInstanceStatusReport`

职责：

- 表达协调器、中央节点、边缘节点和 Python Agent 间的协同命令
- 统一请求/响应/广播/报告的协议语义

说明：

- 这一层是 Python SDK 与 Java 协调体系对齐的最核心部分
- `command_type` 是多态分发的主判别键

### 3.4 时序与事件层

核心对象：

- `HydroEvent`
- `TimeSeriesDataChangedEvent`
- `OutflowTimeSeriesEvent`
- `OutflowTimeSeriesDataChangedEvent`
- `ObjectTimeSeries`
- `TimeSeriesValue`

职责：

- 表达输入边界、出流需求、时序更新和业务事件
- 支撑仿真 Agent、调度 Agent 和计算 Agent 的输入输出

说明：

- 这层在 Python SDK 中主要承担协议承载作用
- 业务含义由具体 Agent 实现解释

### 3.5 配置层

核心对象：

- `AgentConfiguration`
- `AgentProperties`
- `Author`
- `MqttBroker`
- `OutputConfig`

职责：

- 表达单个 Agent 的 YAML 配置
- 记录业务属性、对象建模 URL、输出方式等

说明：

- Python SDK 同时保留本地 `.properties` 和远端 YAML 两套配置入口
- `agent.properties` 更像进程启动或工厂创建配置
- 远端 YAML 更像场景初始化时的正式业务配置

### 3.6 运行时状态层

核心对象：

- `AgentStateManager`
- `TaskState`
- `TaskStatus`

职责：

- 管理任务生命周期状态
- 记录当前活跃上下文
- 管理 agent 注册表
- 区分本地 Agent 与远端 Agent

说明：

- 这是 Python SDK 的“运行态领域仓库”
- 它与 Java 中央侧的 `ContextManager` 不同，它不存放水网认知模型，而是存放 Agent 运行时状态

## 4. 聚合根识别

从 Python SDK 的实现看，建议识别三个聚合根。

### 4.1 `SimulationContext`

用途：

- 任务实例根对象
- 多任务隔离主键
- 命令和 Agent 的统一挂载点

### 4.2 `BaseHydroAgent`

用途：

- Agent 运行时行为根对象
- 持有协议身份、配置属性和客户端引用
- 负责生命周期行为

### 4.3 `AgentStateManager`

用途：

- Python SDK 运行时状态根对象
- 承载上下文、任务状态和 Agent 注册表

## 5. 关键对象关系

Python SDK 的关键对象关系可以简化为：

```text
SimulationContext
  -> HydroAgent
  -> HydroAgentInstance
  -> BaseHydroAgent
  -> SimCommand Request/Response
  -> AgentStateManager
```

配置侧关系为：

```text
agent.properties / env.properties
  -> HydroAgentFactory
  -> BaseHydroAgent

agent_configuration.yaml
  -> AgentConfiguration
  -> BaseHydroAgent.properties
```

协同侧关系为：

```text
MQTT payload
  -> SimCommandEnvelope
  -> SimCommand subclass
  -> SimCoordinationClient
  -> SimCoordinationCallback / BaseHydroAgent
```

## 6. 运行时对象语义说明

### 6.1 `SimulationContext`

语义：

- 表示一个正在运行的仿真任务实例
- 区分于场景模板和静态业务场景编号
- 为所有命令、响应和 Agent 实例提供共同上下文

### 6.2 `HydroAgentInstance`

语义：

- 表示具体节点上、具体任务中的一个 Agent 实例
- 其身份由 `agent_id + biz_scene_instance_id + hydros_node_id` 共同确定

### 6.3 `BaseHydroAgent`

语义：

- 表示一个“可运行的 Agent 主体”
- 不是纯数据模型，而是携带行为、状态管理器和客户端引用的运行时实体

### 6.4 `TaskState`

语义：

- 表示任务生命周期状态快照
- 不描述业务控制状态，只描述任务状态和关联 Agent 列表

### 6.5 `ObjectTimeSeries`

语义：

- 表示某个对象、某项指标在一段时间或步长上的序列数据
- 既可作为输入边界，也可作为计算结果载体

## 7. 与中央智能体领域模型的关系

Python SDK 的领域模型与中央智能体领域模型是互补关系，而不是上下位替代关系。

中央智能体领域模型强调：

- 全局上下文
- 水网拓扑认知
- 对象归属与控制映射
- 中央调度状态

Python SDK 领域模型强调：

- 任务上下文身份
- Agent 实例与生命周期
- 协同命令对象
- 配置对象
- 运行时状态对象

换句话说：

- 中央模型更偏“业务控制与认知”
- Python SDK 模型更偏“协议接入与运行时宿主”

## 8. 当前领域模型缺口

虽然 Python SDK 的基础模型已经完整，但仍有明显缺口：

- 缺少控制区对象 `control_zone`
- 缺少 DMPC 耦合对象 `coupling`
- 缺少区级目标对象 `coordination_output`
- 缺少局部求解输入输出对象
- 缺少标准化执行反馈对象
- 缺少全局水网认知上下文对象

这意味着当前 Python SDK 更适合作为 Agent 宿主和协议载体，而不是直接承载完整 DMPC 领域语义。

## 9. 建议补充的领域对象

后续若要支撑 DMPC 局部控制器或 Python 侧中央协调试验，建议新增：

- `DmpcControlZone`
- `DmpcCoupling`
- `DmpcCoordinationInput`
- `DmpcCoordinationOutput`
- `DmpcLocalSolveInput`
- `DmpcLocalSolveOutput`
- `DmpcExecutionFeedback`
- `HydroModelContextPy` 或类似的 Python 侧全局认知上下文

## 10. 结论

`hydros_agent_sdk` 当前的领域模型可以概括为：

> 以 `SimulationContext` 为任务身份根，以 `BaseHydroAgent` 为行为根，以 `AgentStateManager` 为运行时状态根，通过统一命令对象和时序对象承载 `hydros` 协同协议，从而支撑 Python Agent 的初始化、步进、更新、终止与多 Agent 协同运行。

这套模型足以支撑当前开放 SDK 目标，但若要承接 DMPC 语义，需要在其上增加控制区和协调对象层，而不是继续把新语义压进现有命令模型。
