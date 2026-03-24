# 中央智能体 DMPC 演进改造方案

## 1. 文档目的

本文基于当前 `hydros-agent-central` 的代码现实，提出一套可分阶段落地的 `DMPC` 演进改造方案。目标不是推翻现有中央集中式 `MPC` 架构，而是在保持现有场景驱动、协同协议、Tick/Ack、事件注入和本体仿真链路稳定的前提下，将中央智能体逐步演进为：

> 面向多控制区目标分解、边界协调、局部控制编排与退化治理的 DMPC 中央协调器

## 2. 当前基线判断

当前基线可概括为：

- 中央具备完整的场景初始化与上下文装配链路
- 中央具备完整的协同协议接入链路
- 中央具备统一时序事件汇聚能力
- 中央具备集中式滚动优化触发能力
- 中央直接调用外部 `MPC` 求解器，并把结果翻译成终端动作下发

这意味着当前中央的真实角色是：

- 全局输入汇聚器
- 集中式优化编排器
- 动作下发路由器

## 3. 改造目标

### 3.1 架构目标

- 保留当前场景驱动、协议驱动和 Tick/Ack 主链路
- 从集中式动作求解升级为“全局目标分解 + 局部控制编排”
- 支持控制区建模、边界耦合与共享约束
- 支持中央协调与局部控制并存
- 支持故障、失联、边界缺失时的退化控制

### 3.2 业务目标

- 让中央从“直接给设备动作”转向“给控制区目标”
- 让边缘或局部控制器获得局部求解能力
- 让中央只保留全局协调、仲裁和兜底能力
- 支持单区、双区、多区逐步扩展

### 3.3 工程目标

- 不破坏现有集中式 `MPC` 场景
- 允许新旧模式共存
- 允许按场景逐步启用 DMPC
- 支持在 `NORMAL/SIL/HIL/XIL` 分级推进

## 4. 改造原则

- 不推翻现有主链路
- 先补对象语义，再拆控制职责
- 集中式 MPC 作为保底路径保留
- 先单区试点，再多区扩展
- 中央保留仲裁权，不吞并局部求解

## 5. 目标架构设计

DMPC 演进后的中央智能体建议采用六层架构。

### 5.1 场景与上下文层

保留现有能力：

- 场景配置加载
- `SimulationContext`
- `HydroModelContext`
- 对象归属映射

新增能力：

- 控制区配置加载
- 耦合关系配置加载
- 共享约束配置加载
- 退化策略配置加载

### 5.2 协同协议层

保留现有能力：

- 初始化
- Tick/Ack
- 时序更新
- 兄弟 Agent 状态同步

新增能力：

- 控制区目标分发命令
- 局部求解结果上报命令
- 执行反馈命令
- 边界量交换命令

### 5.3 中央协调层

新增核心层，职责包括：

- 汇总全局状态
- 汇总事件、预测、反馈
- 进行全局目标分解
- 生成各控制区目标与共享约束
- 仲裁控制区冲突
- 决定是否触发全局重规划或局部重算

### 5.4 局部控制编排层

中央不直接做所有局部求解，而是：

- 组织 `local_solve_input`
- 将目标下发给控制区 Agent
- 跟踪控制区求解状态
- 汇总控制区动作与预测轨迹

### 5.5 执行反馈层

该层接收：

- 局部控制器求解结果
- 设备执行结果
- 本体仿真反馈
- 边界量反馈
- 偏差与告警

中央以此决定：

- 是否继续按当前目标推进
- 是否局部重算
- 是否全局重规划
- 是否进入退化控制

### 5.6 兜底集中式控制层

保留现有集中式 `MPC` 作为 fallback：

- 新模式失效时切回集中式 `MPC`
- 早期试点中作为对照组
- 多区场景尚未建模完整时兜底

## 6. 核心改造项

建议把改造工作拆成八个明确模块。

### 6.1 引入控制区模型

新增对象：

- `DmpcControlZone`
- `DmpcZoneType`
- `DmpcZoneMembership`

最小字段建议：

- `zone_id`
- `zone_name`
- `zone_type`
- `owner_agent_code`
- `managed_objects`
- `upstream_zones`
- `downstream_zones`
- `environment_scope`

### 6.2 引入耦合与同步模型

新增对象：

- `DmpcCouplingDefinition`
- `DmpcBoundaryVariable`
- `DmpcSignalPolicy`

最小字段建议：

- `source_zone_id`
- `target_zone_id`
- `coupling_type`
- `signal_policy`
- `sync_interval`
- `boundary_metric_type`

### 6.3 引入中央协调输入输出对象

新增对象：

- `DmpcCoordinationInput`
- `DmpcCoordinationOutput`

`CoordinationInput` 包含：

- 当前全局状态快照
- 事件引用
- 预测引用
- 各区反馈引用
- 当前步与触发原因

`CoordinationOutput` 包含：

- 全局目标摘要
- 各区目标
- 共享约束
- 有效窗口
- 协调状态

### 6.4 引入局部求解输入输出对象

新增对象：

- `DmpcLocalSolveInput`
- `DmpcLocalSolveOutput`

输入包括：

- 控制区目标
- 边界预测
- 本地状态估计
- 设备约束
- 退化上下文

输出包括：

- 动作计划
- 预测轨迹
- 求解状态
- fallback 标记
- 耗时

### 6.5 引入执行反馈对象

新增对象：

- `DmpcExecutionFeedback`

最小字段建议：

- `zone_id`
- `step`
- `observed_state`
- `execution_status`
- `deviation_summary`
- `alerts`
- `needs_replan`

### 6.6 改造中央调度状态机

当前 `MpcTaskState` 过于集中，建议拆分为两层状态。

保留：

- `CentralRollingState`
  内容：当前步、当前轮、触发历史、调度模式

新增：

- `DmpcCoordinationState`
  内容：当前控制区目标快照、边界快照、反馈快照、退化模式

### 6.7 新增模式切换机制

建议在场景或 Agent 配置中新增：

- `control_mode: CENTRALIZED_MPC | HYBRID_DMPC | FULL_DMPC`
- `fallback_mode: LAST_VALID | CENTRALIZED_TAKEOVER | SAFE_RULE`
- `dmpc_enabled: true/false`

### 6.8 引入中央仲裁器

新增模块：

- `DmpcCoordinator`
- `DmpcConflictResolver`
- `DmpcFallbackManager`

职责：

- 生成区级目标
- 仲裁边界冲突
- 决策是否全局重规划
- 决策是否进入兜底模式

## 7. 对现有代码的改造映射

### 7.1 `SimTaskAgentInitializer`

当前职责：
初始化中央上下文。

改造后职责：

- 保持现状
- 新增控制区配置、耦合配置、DMPC 策略配置的加载入口

### 7.2 `ContextManager` / `HydroModelContext`

当前职责：
对象认知与 Agent 归属。

改造后新增：

- `zoneId -> ZoneDefinition`
- `objectId -> zoneId`
- `zoneId -> ownerAgent`
- 控制区邻接关系
- 边界变量定义查询

建议新增专门的 `DmpcZoneContext`，不要把所有新职责硬塞进 `HydroModelContext`。

### 7.3 `CentralSchedulingAgent`

当前职责：
接收事件和 Tick，触发集中式 MPC。

改造后职责：

- 继续作为中央调度 Agent 主入口
- 在 `CENTRALIZED_MPC` 模式下维持现状
- 在 `HYBRID_DMPC` 和 `FULL_DMPC` 模式下改为调用 `DmpcCoordinator`

### 7.4 `MpcTaskState`

当前职责：
集中式滚动优化状态容器。

改造后建议：

- 缩回到“集中式模式专用状态”
- 新增 `DmpcCoordinationState`
- 避免让 `MpcTaskState` 同时承担集中式和分布式两种控制语义

### 7.5 `MpcControllerManager`

当前职责：
直接求解、落库、下发动作。

改造后建议拆分：

- `CentralizedMpcManager`
- `DmpcCoordinationManager`
- `CommandDispatchManager`

### 7.6 `MpcClient`

当前职责：
集中式 MPC 服务适配器。

改造后建议：

- 保留为集中式求解适配器
- 新增 `DmpcCoordinationClient` 或局部控制器通信适配器
- 不让 `MpcClient` 承担控制区级通信职责

## 8. 协议改造方案

DMPC 改造不能只改中央代码，必须同步扩展协同协议。

### 8.1 保留现有协议骨架

保留现有：

- 初始化命令
- Tick/Ack
- 时序更新
- 事件广播
- 兄弟实例状态同步

### 8.2 新增四类协议对象

建议新增：

- `CoordinationTargetDispatchRequest/Response`
- `LocalSolveReportRequest/Response`
- `BoundaryExchangeRequest/Response`
- `ExecutionFeedbackRequest/Response`

### 8.3 与现有命令体系的关系

建议：

- 协调类对象走 `coordination commands`
- 局部动作类对象走 `agent commands`
- 状态与验收对象走系统或 SSE 观测流

## 9. 场景配置改造方案

建议在场景或 Agent 配置中新增以下配置块：

- `dmpc_control_zones`
- `dmpc_couplings`
- `dmpc_goal_templates`
- `dmpc_sync_policy`
- `dmpc_fallback_policy`

最小配置建议：

```yaml
dmpc_enabled: true
control_mode: HYBRID_DMPC

dmpc_control_zones:
  - zone_id: zone_gate_01
    zone_type: GATE_STATION
    owner_agent_code: GATE_STATION_AGENT_001
    managed_objects: [1041, 1042]

dmpc_couplings:
  - coupling_id: cp_01
    source_zone_id: zone_gate_01
    target_zone_id: zone_channel_01
    coupling_type: FLOW
    signal_policy: LATCH_WITH_SYNC
    sync_interval: 10

dmpc_fallback_policy:
  central_takeover_on_local_failure: true
  boundary_timeout_strategy: LAST_VALID
  max_boundary_age_steps: 3
```

## 10. 演进阶段规划

建议分四个阶段推进，而不是一步到位。

### 阶段一：语义补齐，不改主控制链

目标：

- 引入 `control_zone`、`coupling`、`coordination_input/output` 对象
- 引入配置结构
- 引入中央仲裁接口
- 不改现有集中式求解链路

结果：

- 现有场景仍跑集中式 `MPC`
- 新对象用于观测、验证和语义校验

### 阶段二：混合模式 `HYBRID_DMPC`

目标：

- 中央仍可集中求解
- 同时可向单个局部控制区下发目标
- 局部控制区试点返回 `local_solve_output`
- 中央汇总局部结果与集中式结果对比

### 阶段三：双区与多区协同

目标：

- 引入边界量交换
- 中央进行控制区冲突仲裁
- 局部控制器之间形成最小耦合链路
- 支持局部重算与全局重规划区分

### 阶段四：`FULL_DMPC` 与在环验证

目标：

- `FULL_DMPC` 模式上线
- 集中式 `MPC` 转为兜底模式
- 推进 `NORMAL -> SIL -> HIL -> XIL`

## 11. 验证与放行策略

### 阶段一放行条件

- 控制区定义可正确装配
- 耦合定义可正确解析
- 中央可生成 `coordination_input/output`
- 不影响现有集中式场景通过

### 阶段二放行条件

- 单区局部求解可跑通
- 中央可收发局部求解输入输出
- 单区异常时可切回集中式接管
- 与集中式结果可比较、可追踪

### 阶段三放行条件

- 双区边界交换稳定
- 中央仲裁逻辑稳定
- 局部重算与全局重规划边界清晰
- 多区场景无丢 ACK、无失控动作

### 阶段四放行条件

- `FULL_DMPC` 场景在 `NORMAL` 通过
- `SIL` 通过
- 关键 `HIL/XIL` 场景通过
- 异常退化链路完整

## 12. 风险与防御策略

DMPC 改造的最大风险不在求解器，而在系统工程。

- 对象语义补得太慢，控制代码先乱改
- 把所有新职责继续堆进 `MpcTaskState` 和 `MpcControllerManager`
- 局部控制区定义不稳，导致协议返工
- 新旧模式切换不清晰
- DMPC 试点影响现有集中式主业务

防御策略：

- 必须先补对象和配置，再改调度职责
- 尽早拆分集中式与分布式两个状态机和管理器
- 先从单闸站、单渠段做最小控制区模板
- 场景级显式配置 `control_mode`
- 集中式 `MPC` 长期保留为 fallback

## 13. 推荐实施顺序

建议按以下顺序实施：

1. 先定义配置与领域对象
2. 再定义协议对象
3. 再引入中央协调器接口
4. 再做单区 `HYBRID_DMPC`
5. 再做双区边界量交换
6. 再做多区协调与退化治理
7. 最后推进 `FULL_DMPC` 和在环验证

## 14. 最终架构结论

中央智能体的 DMPC 演进，不应理解为“把当前中央 MPC 改复杂”，而应理解为一次职责重构：

- 从“集中式动作求解器”转向“全局目标协调器”
- 从“对象级控制路由”转向“控制区级控制编排”
- 从“统一时序事件缓冲”转向“协调输入/输出语义对象”
- 从“单一路径成功”转向“局部自治 + 中央兜底 + 退化可审计”

用一句话总结这次改造方向：

> 保留中央智能体作为 `hydros` 协同中枢，但把它的核心能力从“直接算动作”升级为“组织分布式控制”。
