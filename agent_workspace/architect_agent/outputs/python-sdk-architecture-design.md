# Python SDK 架构设计说明书

## 1. 文档目的

本文面向 `hydros_agent_sdk`，对当前 Python SDK 的代码实现进行架构化说明，明确其在 `hydros` 体系中的定位、核心模块、运行时职责边界、与中央智能体及协同协议的关系，以及后续向 DMPC 体系演进时应保持的稳定扩展点。

本文以当前 Python 代码实现为准，结合输入目录中的中央智能体专题文档进行口径对齐，但不把中央 Java 代码逻辑机械映射到 Python SDK。Python SDK 的重点不是“重写一个中央调度器”，而是提供一套可以接入 `hydros` 协同链路的 Agent 宿主、协议模型、配置装载和多 Agent 运行时框架。

## 2. 系统定位

`hydros_agent_sdk` 是 `hydros` 面向 Python 智能体开发的运行时 SDK。它的核心定位不是水力学算法库，也不是调度求解器，而是：

- Python Agent 的统一运行时底座
- 协同协议的 Python 侧实现
- 场景初始化、Tick、事件注入的接入层
- 多 Agent 单进程托管与生命周期管理框架
- 配置、日志、消息过滤、状态隔离等基础设施集合

从整体架构上看，它在 `hydros` 中处于“开放 SDK + 协议宿主 + Agent 运行容器”的位置，主要服务于：

- 快速开发 Python 版本的业务 Agent
- 在 `NORMAL/SIL/XIL` 等环境下承接调度或仿真任务
- 与中央节点、边缘节点及协调器完成 MQTT 协同

## 3. 架构目标

当前 Python SDK 的架构目标可归纳为：

- 提供统一的 Agent 基类与生命周期回调接口
- 提供与 Java 协同协议兼容的命令/事件对象模型
- 提供标准的 MQTT 协同客户端与消息路由机制
- 提供多任务隔离和一进程多 Agent 运行能力
- 提供统一的配置加载、日志上下文和错误处理能力
- 为未来 DMPC 局部控制器、仿真 Agent 和支持性 Agent 提供可扩展运行基座

## 4. 总体架构

当前 SDK 可抽象为六层架构。

### 4.1 公共导出层

入口文件 [`__init__.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/__init__.py) 对外暴露了 SDK 的稳定 API 面，包括：

- 协同客户端 `SimCoordinationClient`
- 回调基类 `SimCoordinationCallback`
- 行为基类 `BaseHydroAgent`
- 状态管理 `AgentStateManager`
- MQTT 客户端与消息过滤
- 配置模型与加载函数
- 工厂和多 Agent 运行支持
- 错误处理、日志和工具类
- 内置代表性 Agent 类型

这一层定义了 SDK 的“外部使用面”。

### 4.2 协议模型层

协议模型层主要由以下模块组成：

- [`protocol/models.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/protocol/models.py)
- [`protocol/commands.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/protocol/commands.py)
- [`protocol/events.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/protocol/events.py)
- [`protocol/base.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/protocol/base.py)

职责：

- 定义 `SimulationContext`、`HydroAgent`、`HydroAgentInstance` 等运行时身份对象
- 定义 `SimTaskInitRequest`、`TickCmdRequest`、`TimeSeriesDataUpdateRequest` 等命令对象
- 提供基于 `command_type` 的多态反序列化机制
- 保持与 Java 协同协议口径一致的字段结构

这一层是 Python SDK 的协议语义基础。

### 4.3 Agent 行为抽象层

行为抽象层的核心在：

- [`base_agent.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/base_agent.py)
- [`agents/tickable_agent.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/agents/tickable_agent.py)
- [`agents/*.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/agents)

其中 `BaseHydroAgent` 采用“数据模型继承 + 行为补充”的方式：

- 继承 `HydroAgentInstance` 获取运行时身份属性
- 通过抽象方法暴露 `on_init`、`on_tick`、`on_terminate`
- 提供默认的时序更新、出流请求、响应发送等行为
- 在初始化时绑定 `sim_coordination_client`、`state_manager`、`properties`

这使 SDK 形成了“协议模型与业务行为合一”的 Agent 编程体验。

### 4.4 协同运行时层

这一层是 SDK 的核心运行宿主，主要由：

- [`coordination_client.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/coordination_client.py)
- [`coordination_callback.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/coordination_callback.py)
- [`mqtt.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/mqtt.py)

构成。

`SimCoordinationClient` 负责：

- 建立 MQTT 连接
- 自动订阅协调主题
- 反序列化命令
- 基于消息过滤规则进行过滤
- 按命令类型路由到处理方法
- 维护发送队列和重试机制
- 设置日志上下文

`SimCoordinationCallback` 负责：

- 定义统一的业务回调接口
- 让开发者只聚焦 `on_sim_task_init`、`on_tick` 等核心逻辑
- 将消息处理和 MQTT 细节从业务代码中抽离

这一层对应 Java 侧 `SimCoordinationSlave + SimCoordinationCallback` 的 Python 实现。

### 4.5 运行时状态与隔离层

这一层主要包括：

- [`state_manager.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/state_manager.py)
- [`message_filter.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/message_filter.py)

`AgentStateManager` 负责：

- 维护活跃任务上下文集合
- 管理任务生命周期状态
- 管理 agent 实例注册表
- 区分本地 Agent 与远端 Agent
- 维护当前集群和节点信息

`MessageFilter` 负责：

- 仅放行与当前活跃任务相关的命令
- 对请求、响应、状态报告进行本地/远端过滤
- 复刻 Java 协同接收逻辑中的两层过滤：任务活跃性 + 来源有效性

这使 Python SDK 具备多任务隔离和协议级消息治理能力。

### 4.6 配置与基础设施层

这一层包括：

- [`agent_config.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/agent_config.py)
- [`config_loader.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/config_loader.py)
- [`factory.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/factory.py)
- [`multi_agent.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/multi_agent.py)
- [`logging_config.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/logging_config.py)
- [`error_codes.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/error_codes.py)
- [`error_handling.py`](F:/sl/sdk/hydros-python-sdk/hydros_agent_sdk/error_handling.py)

职责包括：

- 加载 `env.properties` 与 `agent.properties`
- 加载远程 YAML Agent 配置
- 通过工厂创建 Agent 实例
- 在单进程中协调多个 Agent
- 提供面向任务实例和组件的日志上下文
- 提供错误码和统一异常包装能力

## 5. 核心模块说明

### 5.1 `BaseHydroAgent`

定位：Python Agent 行为基类。

特点：

- 继承 `HydroAgentInstance`，避免数据定义重复
- 强制实现 `on_init`、`on_tick`、`on_terminate`
- 默认提供时序更新、出流处理与响应发送方法
- 允许通过 `load_agent_configuration()` 从初始化命令中加载自身配置

设计意义：

- 统一 Agent 开发生命周期
- 将“协议对象”和“运行行为”聚合到同一对象中
- 降低开发 Python Agent 的样板代码

### 5.2 `SimCoordinationClient`

定位：Python 协同客户端宿主。

职责：

- MQTT 连接管理
- 命令反序列化与路由
- 发送队列与重试
- 消息过滤
- 日志上下文注入

设计意义：

- 把网络、消息和重试逻辑从业务 Agent 中抽离
- 让 SDK 的业务扩展点保持在 callback 层和 agent 层

### 5.3 `SimCoordinationCallback`

定位：回调协议接口。

核心要求：

- 实现 `get_component()`
- 实现 `on_sim_task_init()`
- 实现 `on_tick()`

可选扩展：

- 时序计算
- 时序更新
- 终止处理
- 兄弟 Agent 状态更新
- 参数更新、故障注入、噪声仿真等

设计意义：

- 明确“SDK 框架代码”和“业务处理代码”的边界

### 5.4 `AgentStateManager`

定位：运行时统一状态管理器。

职责：

- 管理活跃上下文
- 管理任务状态机
- 管理 agent 注册与本地性判定
- 为消息过滤和回调路由提供基础数据

设计意义：

- 保证 Python SDK 在多任务、多 Agent 情况下仍具备任务隔离能力

### 5.5 `MessageFilter`

定位：消息接收前置治理器。

职责：

- 过滤掉不属于活跃任务的命令
- 过滤掉不应由本节点重复处理的本地响应和报告
- 保持与 Java 接收逻辑的一致性

设计意义：

- 防止同一 MQTT 主题上的广播消息被错误消费
- 避免本地回环响应被误处理

### 5.6 `HydroAgentFactory`

定位：Agent 实例工厂。

职责：

- 加载本地 `agent.properties`
- 加载共享环境配置
- 生成符合约定的 agent 实例 ID
- 统一构造 Agent 对象

设计意义：

- 统一实例化方式
- 降低用户直接 new Agent 时的配置装配复杂度

### 5.7 `MultiAgentCallback`

定位：单进程多 Agent 宿主。

职责：

- 一个 `SimTaskInitRequest` 中识别多个 agent 定义
- 根据工厂注册表创建多个 Agent 实例
- 在同一上下文中托管多个 Agent
- 将 Tick、终止、时序更新广播给上下文中的多个 Agent
- 将定向请求路由给目标 Agent

设计意义：

- 提供 Python 侧的一进程多智能体运行方式
- 对应 `hydros` 场景配置中“一个节点承载多个 Agent”的需求

## 6. 典型运行链路

### 6.1 启动链路

1. 加载 `env.properties`
2. 创建 `SimCoordinationCallback` 或 `MultiAgentCallback`
3. 创建 `SimCoordinationClient`
4. 建立 MQTT 连接并订阅协调主题
5. 注册命令处理器

### 6.2 任务初始化链路

1. 协调器广播 `SimTaskInitRequest`
2. `SimCoordinationClient` 接收并反序列化
3. `MessageFilter` 判断该请求是否应处理
4. 回调进入 `on_sim_task_init()`
5. `BaseHydroAgent.load_agent_configuration()` 从 `request.agent_list` 中匹配自身配置 URL
6. Agent 完成初始化并注册到 `AgentStateManager`
7. 产生 `SimTaskInitResponse` 返回

### 6.3 Tick 链路

1. 协调器发送 `TickCmdRequest`
2. 客户端完成解析与过滤
3. 回调进入 `on_tick()`
4. 单 Agent 或多 Agent 分别执行自身业务步骤
5. 构建 `TickCmdResponse`
6. 通过发送队列异步发布响应

### 6.4 时序更新链路

1. 上游发出 `TimeSeriesDataUpdateRequest`
2. 客户端解析并过滤
3. 回调或 Agent 默认方法处理时序数据更新
4. 返回 `TimeSeriesDataUpdateResponse`

### 6.5 多 Agent 单进程链路

1. `MultiAgentCallback` 读取初始化请求中的 `agent_list`
2. 按 `agent_code` 匹配已注册的 Agent 工厂
3. 为同一 `SimulationContext` 创建多个 Agent 实例
4. 将上下文内请求广播给相关 Agent 或按目标实例路由

## 7. 与中央智能体专题的对齐关系

对齐点主要有四个。

### 7.1 与中央架构设计说明书的对齐

中央智能体文档强调“场景驱动、协议驱动、事件驱动”的主链路。Python SDK 完整承接了这三点：

- 通过 `SimTaskInitRequest` 承接场景初始化
- 通过 `SimCoordinationClient` 承接协同协议
- 通过 Tick 和时序更新承接事件驱动

### 7.2 与中央领域模型的对齐

Python SDK 已对齐的关键领域对象包括：

- `SimulationContext`
- `HydroAgent`
- `HydroAgentInstance`
- `ObjectTimeSeries`
- 命令与响应对象

但它并不内建中央 `HydroModelContext` 那样的全局认知上下文。这说明 SDK 更偏“Agent 运行时”，而不是“全局中央认知内核”。

### 7.3 与中央验证方案的对齐

中央文档中的初始化、协议、时序、ACK 验证口径，几乎都可直接映射到 Python SDK 的：

- 初始化链路测试
- Tick/ACK 测试
- 消息过滤测试
- 多 Agent 路由测试
- 配置加载测试

### 7.4 与中央 DMPC 演进方案的对齐

中央 DMPC 演进方案要求未来出现：

- 控制区目标下发
- 局部求解输入输出
- 执行反馈对象
- 边界变量交换

Python SDK 当前已经具备承接这些能力的基础骨架：

- 命令协议扩展点
- callback 扩展点
- 多 Agent 路由机制
- 状态管理和日志上下文

但目前尚未内建标准化的 DMPC 控制区对象和局部求解协议对象。

## 8. 代表性 Agent 类型

SDK 当前内置的 Agent 类型说明了它的目标使用面：

- `TickableAgent`：面向按 Tick 驱动执行的通用 Agent
- `OntologySimulationAgent`：面向本体仿真的仿真 Agent
- `TwinsSimulationAgent`：面向孪生仿真或状态映射的 Agent
- `ModelCalculationAgent`：面向模型计算的 Agent
- `CentralSchedulingAgent`：面向中央调度逻辑的 Python 抽象基类
- `OutflowPlanAgent`：面向出流计划等专门业务的 Agent

其中 Python 版 `CentralSchedulingAgent` 当前更多是一个抽象宿主，而不是 Java 中央智能体的完整等价实现。它的意义在于为 Python 侧中央调度实验或局部控制器实验预留扩展点。

## 9. 当前架构优势

当前 SDK 架构有以下优势：

- 协议与运行时骨架完整，能直接进入 `hydros` 协同链路
- 单 Agent 和多 Agent 两种运行模式并存
- 协议对象采用 Pydantic，结构清晰，序列化和校验便利
- 配置加载同时支持本地 `.properties` 和远程 YAML
- 日志上下文设计较成熟，适合多任务排障
- 通过 `MessageFilter` 复刻了 Java 协调接收逻辑，减少跨语言偏差

## 10. 当前架构缺口

当前 SDK 也存在明显边界和缺口：

- 仍然更偏“运行时框架”，缺少高层业务编排抽象
- 对控制区、共享约束、边界量等 DMPC 语义没有标准对象
- `MultiAgentCallback` 的 `managed_top_objects` 仍较弱，尚不足以表达复杂对象归属模型
- 远程 YAML 配置和本地 properties 存在双入口，需要更清晰的优先级规范
- 局部控制器之间的边界协同协议尚未正式内建
- 现有内置 Agent 抽象层仍偏示范性质，复杂业务实现需要业务方继续补充

## 11. 架构结论

`hydros_agent_sdk` 当前应被定义为：

> 面向 `hydros` 多智能体场景的 Python Agent 运行时 SDK，负责协议接入、Agent 生命周期管理、多任务隔离、多 Agent 编排以及配置、日志、错误处理等基础设施，不直接承担完整中央调度语义，但为中央调度 Agent、仿真 Agent 和未来 DMPC 局部控制器提供统一扩展底座。

这一定义与输入目录中的中央智能体专题是对齐的：中央侧强调“系统协调与控制职责”，而 Python SDK 侧强调“跨语言 Agent 运行时与开放接入职责”。
