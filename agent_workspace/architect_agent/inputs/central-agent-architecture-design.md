# 中央智能体架构设计说明书

## 1. 文档目的

本文面向 `hydros` 中央智能体 `hydros-agent-central`，对其当前代码实现进行结构化说明，明确其在 `hydros` 总体体系中的职责定位、核心模块、领域对象、运行链路、理论对齐关系与验证策略。本文以当前 Java 代码实现为准，同时参考 DMPC、场景规范、协同协议等专题文档，对“现状能力”和“目标演进方向”做显式区分。

适用范围：

- 中央智能体代码理解与架构评审
- 中央调度链路梳理
- 向 `DMPC` 架构演进的设计基线制定
- 场景化验证与验收策略设计

核心参考实现与文档：

- `HydroCentralApplication.java`
- `SimTaskAgentInitializer.java`
- `SimCoordinationCallbackImpl.java`
- `ContextManager.java`
- `HydroModelContext.java`
- `CentralSchedulingAgent.java`
- `MpcTaskState.java`
- `MpcControllerManager.java`
- `MpcClient.java`
- `02-DMPC在hydros中的架构设计草案.md`
- `04-DMPC在hydros中的对象模型与接口规范草案.md`
- `05-DMPC场景验证矩阵与验收标准.md`
- `03-场景如何运行.md`

## 2. 系统定位

`hydros-agent-central` 是 `hydros` 多智能体水网系统中的中央调度节点。它不直接承担水力本体仿真，也不直接作为所有设备的执行器，而是承担以下中枢职责：

- 承接协同协议层的初始化、Tick、时序更新等命令
- 装配场景上下文和水网拓扑认知
- 监听时序事件并维护中央调度状态
- 调用外部 `MPC` 服务形成滚动优化结果
- 将优化结果转换为控制命令并下发到边缘 Agent 或设备对象
- 保存优化结果，形成调度过程可追溯证据

从架构本质上看，当前中央智能体更准确的定位是：

> 基于场景与协同协议驱动的中央集中式调度协调器

而不是严格意义上的：

> 面向多控制区目标分解与边界协调的完整 DMPC 中央协调器

## 3. 架构目标

中央智能体在当前阶段的设计目标可以概括为五点：

- 支持场景驱动的中央调度任务初始化
- 支持与 `hydros` 协同协议一致的 Tick/Ack 运行模式
- 支持基于时序事件的滚动优化触发
- 支持将优化结果翻译为实际控制动作
- 支持在多任务、多场景环境中以 `SimulationContext` 为边界隔离运行状态

若面向未来 `DMPC` 演进，则中央智能体的目标还应扩展为：

- 对全局目标进行区域化分解
- 管理控制区之间的耦合边界与同步策略
- 协调局部控制器之间的目标冲突与约束冲突
- 在通信异常、求解失败、设备故障时提供可审计的退化控制路径

## 4. 总体架构

中央智能体当前实现可以抽象为五层架构。

### 4.1 启动与基础设施层

由 Spring Boot 应用、配置系统、日志系统和 MQTT/Web 基础依赖组成，负责应用启动和运行环境装配。

关键入口：

- `HydroCentralApplication`
- `application.yml`

特征：

- 使用 Spring Boot 自动装配
- 通过扫描配置装配中央 Agent
- 启用 MQTT、日志、可观测性
- 外部依赖包括 `hydros-agent-protocol`、HTTP 数据服务、MPC 服务、MQTT Broker

### 4.2 协同协议接入层

该层是中央节点对 `hydros` 协同协议的适配入口。它负责接收来自协调器的命令，并把协议事件路由给本地 Agent。

关键实现：

- `SimCoordinationCallbackImpl`

主要处理的协议动作：

- `onSimTaskInit`
- `onTick`
- `onTimeSeriesDataUpdate`
- `onTimeSeriesCalculation`
- `onOutflowTimeSeries`
- `onAgentInstanceSiblingCreated`
- `onAgentInstanceSiblingStatusUpdated`

### 4.3 上下文与拓扑认知层

该层负责将场景配置转化为可运行的中央认知模型，包括对象拓扑、上下游关系、对象归属关系等。

关键实现：

- `SimTaskAgentInitializer`
- `ContextManager`
- `HydroModelContext`

核心作用：

- 按 `bizSceneInstanceId` 建立任务隔离上下文
- 从对象建模 URL 构建水网拓扑
- 将 `TopHydroObject` 与 `HydroAgentInstance` 建立映射
- 支持对象归属查询与上下游邻接查询

### 4.4 中央调度控制层

该层由中央调度 Agent 主导，负责把 Tick 和时序事件转化为中央优化动作。

关键实现：

- `CentralSchedulingAgent`
- `HydroCentralAgentExt`

主要职责：

- 初始化业务状态
- 接收入流、用水、故障等时序事件
- 在首次事件到来时构造 `MpcTaskState`
- 在 Tick 到来时按滚动步长触发重新优化
- 维护中央 Agent 的业务状态

### 4.5 求解与执行适配层

该层负责把中央调度状态变成外部求解请求，并将结果转成可执行命令。

关键实现：

- `MpcTaskState`
- `MpcControllerManager`
- `MpcClient`
- `AgentEdgeDataMqttCallback`

主要职责：

- 维护中央滚动优化状态
- 整理边界时序、传感器数据、目标和固定控制约束
- 调用外部 MPC HTTP 服务
- 保存 MPC 结果到 `hydros-data`
- 将结果转换为闸门开度命令或扰动流量命令
- 通过事件总线发布控制命令

## 5. 模块职责说明

### 5.1 `HydroCentralApplication`

职责：

- 应用启动入口
- Spring 组件扫描
- 开启异步、调度、AOP 支持

### 5.2 `SimTaskAgentInitializer`

职责：

- 响应仿真任务初始化
- 将 `BizScenarioConfiguration` 与 `SimulationContext` 注入中央上下文

### 5.3 `ContextManager`

职责：

- 维护中央运行态上下文注册表
- 依据 `bizSceneInstanceId` 获取上下文
- 依据 `objectId` 获取归属 Agent

### 5.4 `HydroModelContext`

职责：

- 持有水网拓扑 `WaterwayTopology`
- 建立 `objectToAgentInstanceMap`
- 提供对象、上下游、归属查询

### 5.5 `SimCoordinationCallbackImpl`

职责：

- 协议层命令入口
- 对本地 Agent 的 Tick、时序更新、出流请求进行分发
- 同步兄弟 Agent 实例与对象管理关系

### 5.6 `CentralSchedulingAgent`

职责：

- 中央调度 Agent 主体
- 响应 Tick 与时序事件
- 初始化和驱动滚动优化

### 5.7 `MpcTaskState`

职责：

- 保存滚动优化任务状态
- 缓存已接收的时序事件
- 保存配置 URL、滚动步长、当前步、当前轮次

### 5.8 `MpcControllerManager`

职责：

- 注册和获取 `MpcTaskState`
- 触发滚动优化
- 保存优化结果
- 把优化结果转成执行命令

### 5.9 `MpcClient`

职责：

- 组装外部 MPC 请求
- 从事件缓冲中提取边界、目标、故障约束
- 调用外部 MPC HTTP API

### 5.10 `AgentEdgeDataMqttCallback`

职责：

- 接收边缘传感器数据
- 将感知值缓存到本地供 MPC 调用时使用

## 6. 运行时主链路

### 6.1 场景初始化链路

运行时从场景到中央上下文的典型路径如下：

1. 协调器发出 `SimTaskInitRequest`
2. 中央节点通过 `SimCoordinationCallbackImpl` 收到初始化命令
3. `SimTaskAgentInitializer` 执行初始化
4. `ContextManager` 创建任务上下文
5. `HydroModelContext` 从对象建模 URL 读取拓扑
6. 边缘 Agent 初始化完成后，兄弟实例及其 `managedTopObjects` 被回传
7. 中央上下文建立对象与 Agent 的归属关系映射

### 6.2 时序驱动与滚动优化链路

典型路径如下：

1. 协调器或事件系统发出 `TimeSeriesDataUpdateRequest`
2. `SimCoordinationCallbackImpl` 将事件转发给 `CentralSchedulingAgent`
3. `CentralSchedulingAgent` 在首次事件触发时构造 `MpcTaskState`
4. `MpcTaskState` 记录当前步、滚动步长、时序事件、配置 URL
5. `MpcControllerManager` 触发滚动优化
6. `MpcClient` 组装请求并调用外部 MPC 服务
7. MPC 返回多个规划方案，中央筛选最优方案
8. 优化结果保存到 `hydros-data`
9. 第一时域动作被转成控制命令并发布

### 6.3 Tick 驱动重算链路

典型路径如下：

1. 协调器发出 `TickCmdRequest`
2. `SimCoordinationCallbackImpl` 遍历本地 Agent
3. `CentralSchedulingAgent.onTickReceived(step)` 更新当前步
4. 若已存在 `MpcTaskState`，且满足滚动触发条件
5. 再次调用 `MpcControllerManager.doRollingOptimal`
6. 发布 `TickCmdResponse` 作为当前步 ACK

## 7. 领域模型设计

建议将中央智能体的核心领域对象分为五类：

- 身份与任务域：`SimulationContext`、`BizScenarioConfiguration`
- 水网认知域：`HydroModelContext`、`WaterwayTopology`
- 智能体协同域：`HydroAgentInstance`
- 调度状态域：`CentralSchedulingAgent`、`MpcTaskState`
- 求解与执行域：`MpcOptimizeRequest`、`MpcOptimizeResponse`、控制命令对象

## 8. 与 DMPC 理论的对齐分析

已对齐部分：

- 可嵌入 `Tick/Ack` 协同链路
- 可接入场景、事件、边界与反馈
- 可作为中央协调入口接收全局信息
- 可作为控制命令发起者向边缘下发动作

未对齐部分：

- 未建立 `control_zone` 控制区模型
- 未建立 `coupling_definition` 耦合边界模型
- 未显式区分中央协调输入与中央协调输出
- 未建立局部求解输入输出对象
- 未建立执行反馈闭环对象

## 9. 设计约束与工程风险

关键风险包括：

- `ContextManager` 使用静态 `HashMap`，并发治理偏弱
- `MpcTaskState` 的事件缓冲缺少窗口裁剪策略
- `MpcClient` 对传感器缓存为空采用软重试，数据同步约束偏弱
- 当前中央直接把优化结果翻译成动作，仍然是集中式控制口径
- 测试覆盖明显不足

## 10. 验证策略设计

建议按三层推进：

### 10.1 实现正确性验证

- 场景初始化成功
- 上下文创建成功
- 水网拓扑加载成功
- 对象归属映射成功
- 时序事件接收成功
- `MpcTaskState` 创建与更新成功
- Tick 触发滚动重算成功
- 求解结果保存成功
- 控制命令下发成功

### 10.2 架构一致性验证

- `bizSceneInstanceId` 是否贯穿主链路
- 对象归属与执行路由是否一致
- 协议层 ACK 是否完整
- 事件与 Tick 是否保持状态一致性
- 故障、用水、边界时序是否都能进入统一调度入口

### 10.3 DMPC 演进准备度验证

- 是否能抽出最小控制区
- 是否能为两个控制区定义边界量
- 是否能区分全局重规划与局部重算
- 是否能为求解失败定义退化策略

## 11. 演进建议

短期建议：

- 明确 `SimulationContext` 与 `HydroModelContext` 生命周期
- 为 `MpcTaskState` 增加事件窗口管理
- 增加初始化、事件处理、Tick 重算、命令下发测试

中期建议：

- 引入 `coordination_input`
- 引入 `coordination_output`
- 引入 `local_solve_input`
- 引入 `local_solve_output`
- 引入 `execution_feedback`

长期建议：

- 中央输出区域目标而不是所有设备动作
- 管理共享约束而不是直接吞并局部求解
- 协调边界变量而不是只汇总全局时序
- 在局部控制器失效时提供保底策略

## 12. 结论

`hydros-agent-central` 当前是 `hydros` 体系中一个结构清晰、链路闭合的中央调度节点。它已经具备：

- 场景装配能力
- 协同协议接入能力
- 水网对象认知能力
- 集中式滚动优化编排能力
- 优化结果下发与存证能力

但从 `DMPC` 理论目标看，它仍处于“中央集中式 MPC 向 DMPC 中央协调层”的过渡阶段。最关键的差距不是算法精度，而是语义层和对象层尚未完全建立，尤其是控制区、边界变量、共享约束、局部求解对象和执行反馈对象的体系化建模仍需补齐。
