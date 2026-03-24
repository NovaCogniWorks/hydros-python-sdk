# 中央智能体领域模型说明书

## 1. 文档目的

本文定义 `hydros-agent-central` 的核心领域对象、对象边界、对象关系与演进方向，用于统一中央智能体的业务语义、代码理解口径和后续 `DMPC` 升级基线。

核心参考：

- `ContextManager.java`
- `HydroModelContext.java`
- `CentralSchedulingAgent.java`
- `MpcTaskState.java`
- `MpcClient.java`
- `04-DMPC在hydros中的对象模型与接口规范草案.md`

## 2. 建模原则

中央智能体领域建模遵循以下原则：

- 运行态与模板态分离
- 身份对象、认知对象、控制对象、执行对象分离
- 场景编排语义与控制求解语义分离
- 当前实现对象与目标 DMPC 对象并行表述，不强行混写

## 3. 领域分层

建议将中央智能体的领域划分为六层。

### 3.1 场景与身份层

核心对象：

- `BizScenarioConfiguration`
- `SimulationContext`

职责：

- `BizScenarioConfiguration` 表示场景模板定义，描述场景配置、Agent 列表、对象模型 URL、自动事件等
- `SimulationContext` 表示本次任务运行身份，包含租户、场景、水网、实例 ID

建模结论：

- `BizScenarioConfiguration` 是“配置模板对象”
- `SimulationContext` 是“运行实例对象”
- 两者不可混用

### 3.2 水网认知层

核心对象：

- `HydroModelContext`
- `WaterwayTopology`
- `TopHydroObject`
- `SimpleHydroObjectDTO`
- `NeighborResult`

职责：

- 描述水网拓扑
- 提供对象上下游查询
- 提供对象归属关系查找能力

建模结论：

- `HydroModelContext` 是中央对水网的“运行态认知快照”
- `WaterwayTopology` 是“物理拓扑领域对象”
- 该层不负责优化，只负责“理解系统”

### 3.3 智能体协同层

核心对象：

- `HydroAgentInstance`
- 本地 Agent 集合
- 兄弟 Agent 状态报告对象

职责：

- 表示场景内实际存在的智能体实例
- 管理对象与 Agent 的归属关系
- 支持中央对边缘 Agent 的命令寻址

建模结论：

- 中央控制的不是对象本身，而是“对象背后的归属 Agent”
- `HydroAgentInstance` 是中央执行路由的核心枢纽对象

### 3.4 事件与扰动层

核心对象：

- `TimeSeriesDataChangedEvent`
- `ObjectTimeSeries`
- `TimeSeriesValue`

职责：

- 表达天气、用水、故障、边界变化等外部扰动
- 为控制求解提供边界输入

建模结论：

- 当前实现采用“统一时序事件模型”承载多种扰动
- 这是工程上简化后的输入对象，不等于最终 DMPC 语义对象

### 3.5 中央控制状态层

核心对象：

- `CentralSchedulingAgent`
- `MpcTaskState`

职责：

- 保存中央调度状态
- 管理滚动优化的当前步、当前轮、事件缓存、配置入口

建模结论：

- `CentralSchedulingAgent` 是行为主体
- `MpcTaskState` 是中央控制状态聚合根
- 当前中央调度的控制状态还偏“过程态”，尚未抽象为标准协调输入输出

### 3.6 求解与执行层

核心对象：

- `MpcOptimizeRequest`
- `MpcOptimizeResponse`
- `HydroDirectGateOpeningRequest`
- `DisturbanceNodeWaterFlowRequest`

职责：

- 将中央状态转换为求解器输入
- 将求解器结果转换为实际执行动作

建模结论：

- 当前中央直接产出终端动作，说明其仍是集中式控制口径
- 若未来演进到 DMPC，此层前面应新增“区域目标层”

## 4. 聚合根设计

建议从 DDD 视角识别三个聚合根。

### 4.1 任务运行聚合根：`SimulationContext`

聚合内容：

- 任务身份
- 租户、场景、水网
- 当前任务实例边界

用途：

- 作为所有运行态对象的分区键
- 作为上下文隔离的唯一主键

### 4.2 中央认知聚合根：`HydroModelContext`

聚合内容：

- 水网拓扑
- 对象归属映射
- 上下游关系查询能力

用途：

- 中央做对象级寻址与关系推断的基础

### 4.3 中央控制聚合根：`MpcTaskState`

聚合内容：

- 当前轮次
- 当前步
- 滚动步长
- 事件缓冲
- MPC 配置入口

用途：

- 描述一条中央滚动调度链路的运行态

## 5. 关键对象关系

当前对象关系可以描述为：

```text
BizScenarioConfiguration
  -> SimulationContext
  -> HydroModelContext
  -> HydroAgentInstance 集合
  -> CentralSchedulingAgent
  -> MpcTaskState
  -> MpcOptimizeRequest / Response
  -> Command Request
```

进一步展开为：

```text
场景模板
  -> 构造任务实例身份
  -> 加载水网拓扑认知
  -> 建立对象归属关系
  -> 接收时序扰动
  -> 更新中央控制状态
  -> 触发集中式滚动优化
  -> 下发执行命令
```

## 6. 当前实现模型与目标 DMPC 模型的映射

当前实现对象：

- `TimeSeriesDataChangedEvent`
- `MpcTaskState`
- `MpcOptimizeRequest`
- `MpcOptimizeResponse`
- 控制命令事件

目标 DMPC 对象：

- `coordination_input`
- `coordination_output`
- `local_solve_input`
- `local_solve_output`
- `execution_feedback`

建议映射关系：

- `TimeSeriesDataChangedEvent + Sensor Cache + Context`
  未来映射为 `coordination_input`
- `MpcTaskState`
  未来拆分为 `coordination_state + rolling_control_state`
- `MpcOptimizeRequest`
  未来对应 `local_solve_input` 或中央输出到局部控制器的输入
- `MpcOptimizeResponse`
  未来对应 `local_solve_output`
- 控制命令执行结果
  未来对应 `execution_feedback`

## 7. 当前领域模型缺口

关键缺口有六项：

- 缺少 `control_zone` 控制区对象
- 缺少 `coupling_definition` 耦合定义对象
- 缺少共享约束对象
- 缺少中央协调输入输出对象
- 缺少局部求解输入输出对象
- 缺少执行反馈标准对象

## 8. 建议补充的领域对象

建议后续新增以下对象，不立即替换现有对象，而是作为扩展层引入。

- `DmpcControlZone`
  说明：表示一个局部控制区
- `DmpcCoupling`
  说明：表示控制区间边界耦合关系
- `DmpcCoordinationInput`
  说明：中央本轮协调所需的全局输入
- `DmpcCoordinationOutput`
  说明：中央对控制区下发的目标与共享约束
- `DmpcLocalSolveInput`
  说明：某个局部控制器的求解输入
- `DmpcLocalSolveOutput`
  说明：局部控制器输出的动作与预测轨迹
- `DmpcExecutionFeedback`
  说明：对象侧或设备侧反馈的执行结果

## 9. 领域模型结论

中央智能体当前的领域模型可以概括为：

> 以 `SimulationContext` 为身份根，以 `HydroModelContext` 为认知根，以 `MpcTaskState` 为控制根，通过统一时序事件驱动集中式滚动优化，并通过对象归属路由执行命令。

这是一套合理的“中央集中式调度领域模型”，但尚未达到“DMPC 语义完备领域模型”的成熟度。
