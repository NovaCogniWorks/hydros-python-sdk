# Python SDK 改造任务拆解清单

## 1. 文档目的

本文将 Python SDK 的后续演进工作拆解为可执行任务清单，覆盖模块、类、协议对象、配置模型、验证与阶段里程碑。目标是把前面四份专题文档中的架构结论，转成可排期、可实施、可验收的工程任务。

适用范围：

- `hydros_agent_sdk` 的架构演进
- Python SDK 面向 DMPC 的对象层与协议层补齐
- 局部控制器、支持性 Agent 和多 Agent 宿主增强
- 与中央协调体系对接的工程实施规划

## 2. 总体实施策略

建议按四条主线并行推进，但以“对象和协议优先，运行时和业务后置”为原则。

四条主线：

- 主线 A：协议与领域对象补齐
- 主线 B：运行时和多 Agent 宿主增强
- 主线 C：局部 DMPC Agent 抽象与样例落地
- 主线 D：验证体系、样例工程与文档收敛

推荐顺序：

1. 先补对象模型和协议模型
2. 再增强状态管理与多 Agent 宿主
3. 再引入局部 DMPC Agent 抽象层
4. 再做中央对接与场景验证

## 3. 阶段拆解

### 阶段 1：协议与对象层补齐

目标：

- 不破坏现有 SDK 主链路
- 先让 Python SDK 具备表达 DMPC 语义的能力

交付物：

- DMPC 对象模型模块
- DMPC 命令模块
- 配套的最小配置模型
- 序列化与反序列化测试

### 阶段 2：运行时增强

目标：

- 在现有 `BaseHydroAgent` 和 `MultiAgentCallback` 基础上补足控制区运行能力

交付物：

- 控制区上下文容器
- 边界量缓存机制
- 多 Agent 路由增强
- 局部控制运行状态管理

### 阶段 3：局部控制器抽象和样例

目标：

- 建立 Python 侧局部 DMPC Agent 抽象层
- 完成单控制区试点样例

交付物：

- `LocalDmpcAgent`
- 单区控制样例
- 局部求解输入输出与反馈样例

### 阶段 4：中央对接与场景验收

目标：

- 将 Python SDK 与中央协调输出正式打通
- 建立单区、双区和多 Agent 试点验收路径

交付物：

- 中央目标下发协议适配
- 执行反馈回传协议适配
- 场景化验收清单与样例

## 4. 主线 A：协议与领域对象补齐

### A1. 新建 DMPC 对象模型模块

建议新增文件：

- `hydros_agent_sdk/protocol/dmpc_models.py`

建议新增类：

- `DmpcControlZone`
- `DmpcCoupling`
- `DmpcBoundaryVariable`
- `DmpcCoordinationInput`
- `DmpcCoordinationOutput`
- `DmpcLocalSolveInput`
- `DmpcLocalSolveOutput`
- `DmpcExecutionFeedback`

任务说明：

- 使用 Pydantic 建模
- 保持字段命名与现有命令模型风格一致
- 对关键字段提供最小校验
- 避免把业务算法参数过度硬编码进基础对象

完成标准：

- 所有对象可序列化和反序列化
- 有最小单元测试覆盖
- 不影响现有 `protocol/models.py`

### A2. 新建 DMPC 命令模块

建议新增文件：

- `hydros_agent_sdk/protocol/dmpc_commands.py`

建议新增命令：

- `CoordinationTargetDispatchRequest`
- `CoordinationTargetDispatchResponse`
- `LocalSolveReportRequest`
- `LocalSolveReportResponse`
- `BoundaryExchangeRequest`
- `BoundaryExchangeResponse`
- `ExecutionFeedbackRequest`
- `ExecutionFeedbackResponse`

任务说明：

- 保持与 `SimCommand` 体系兼容
- 每个命令带 `command_type`、`context`、业务载荷
- 后续可接入 `SimCommandEnvelope`

完成标准：

- 可通过 `command_type` 多态分发
- 与现有命令不会冲突

### A3. 扩展 `SimCommandEnvelope`

涉及文件：

- `hydros_agent_sdk/protocol/commands.py`

任务说明：

- 将 DMPC 命令对象纳入 Union
- 确保现有命令兼容性不受影响
- 为后续按模块拆分命令提供兼容入口

完成标准：

- 新旧命令均可正确解析
- 解析失败场景有明确异常

### A4. 补齐 DMPC 事件对象

建议新增文件：

- `hydros_agent_sdk/protocol/dmpc_events.py`

建议新增对象：

- `BoundaryUpdateEvent`
- `ZoneTargetUpdatedEvent`
- `ExecutionDeviationEvent`
- `FallbackActivatedEvent`

任务说明：

- 事件与命令分离
- 用于局部控制器内部处理和回调扩展

## 5. 主线 B：运行时和宿主增强

### B1. 新增控制区上下文容器

建议新增文件：

- `hydros_agent_sdk/dmpc/zone_context.py`

建议新增类：

- `DmpcZoneContext`
- `ZoneRuntimeState`

任务说明：

- 保存 `zone_id`、受管对象、边界缓存、目标快照、反馈快照
- 不替代 `SimulationContext`，而是挂在其下

完成标准：

- 一个 `SimulationContext` 下可挂多个 `DmpcZoneContext`

### B2. 增强 `AgentStateManager`

涉及文件：

- `hydros_agent_sdk/state_manager.py`

改造项：

- 增加 `context -> zone contexts` 映射
- 增加局部求解状态缓存
- 增加边界量缓存
- 增加 fallback 状态记录

任务说明：

- 保持现有任务状态管理不破坏
- 新能力尽量以新增字段和新方法实现

完成标准：

- 现有测试通过
- 新增状态查询接口可用

### B3. 增强 `MultiAgentCallback`

涉及文件：

- `hydros_agent_sdk/multi_agent.py`

改造项：

- 增加 `context_id -> zone_id -> agent` 路由能力
- 支持 DMPC 目标定向派发
- 支持边界量在上下文内路由
- 支持局部控制器和支持性 Agent 混合托管

完成标准：

- 多 Agent 创建逻辑保持兼容
- 新增定向路由测试通过

### B4. 扩展 `MessageFilter`

涉及文件：

- `hydros_agent_sdk/message_filter.py`

改造项：

- 为 DMPC 新命令提供过滤规则
- 保证区级路由命令不会被误过滤
- 明确本地/远端局部求解报告的过滤逻辑

完成标准：

- 新旧命令过滤逻辑均有测试覆盖

### B5. 扩展 `SimCoordinationClient`

涉及文件：

- `hydros_agent_sdk/coordination_client.py`

改造项：

- 注册 DMPC 新命令处理器
- 增加 DMPC 命令发送便捷方法
- 支持更清晰的日志上下文标识，例如 zone 级 component

完成标准：

- 不影响现有初始化、Tick、时序更新链路
- 新命令可被正确收发

## 6. 主线 C：局部 DMPC Agent 抽象与样例

### C1. 新增局部 DMPC Agent 抽象基类

建议新增文件：

- `hydros_agent_sdk/agents/local_dmpc_agent.py`

建议新增类：

- `LocalDmpcAgent`

建议抽象方法：

- `on_coordination_target_received()`
- `build_local_solve_input()`
- `solve_local_control()`
- `build_execution_feedback()`
- `on_boundary_update()`

设计原则：

- 继承 `BaseHydroAgent` 或 `TickableAgent`
- 不在基类中绑定具体优化器实现
- 只定义局部控制器的生命周期和输入输出接口

完成标准：

- 有最小可运行样例
- 能独立完成初始化、接收目标、输出局部求解结果

### C2. 新增边界感知 Agent 抽象

建议新增文件：

- `hydros_agent_sdk/agents/boundary_aware_agent.py`

建议新增类：

- `BoundaryAwareAgent`

任务说明：

- 用于需要处理上下游边界量的局部控制器或仿真 Agent
- 将边界缓存、同步策略和更新钩子抽出来

### C3. 增强或整理现有示例 Agent

涉及文件：

- `agents/central_scheduling_agent.py`
- `agents/ontology_simulation_agent.py`
- `agents/model_calculation_agent.py`
- `agents/twins_simulation_agent.py`
- `agents/outflow_plan_agent.py`

改造建议：

- 明确哪些是抽象宿主，哪些是可直接复用示例
- 为 `CentralSchedulingAgent` 明确“抽象中央宿主，不等价于完整中央实现”的文档说明
- 为仿真 Agent 增加与控制区、边界更新相关的扩展示例

### C4. 新增单控制区样例

建议新增目录：

- `examples/dmpc_single_zone/`

建议内容：

- `env.properties`
- `agent.properties`
- 示例 YAML 配置
- 单区局部控制器实现
- 启动脚本与 README

完成标准：

- 能演示从初始化到局部求解输出的最小闭环

## 7. 主线 D：配置、验证、文档与样例工程

### D1. 扩展 YAML 配置模型

涉及文件：

- `hydros_agent_sdk/agent_config.py`

改造项：

- 增加 DMPC 配置字段的扩展容器
- 或显式新增 `dmpc_*` 字段模型

建议新增字段：

- `dmpc_control_zone`
- `dmpc_couplings`
- `dmpc_goal_templates`
- `dmpc_sync_policy`
- `dmpc_fallback_policy`

完成标准：

- 远程 YAML 可解析这些字段
- 不影响旧配置解析

### D2. 明确配置优先级

涉及文件：

- `hydros_agent_sdk/config_loader.py`
- 文档和示例工程

任务说明：

- 明确 `env.properties`、`agent.properties`、远程 YAML 的职责边界
- 文档中明确优先级与推荐用法

建议口径：

- `env.properties`：节点和连接环境
- `agent.properties`：实例化级最小信息
- 远程 YAML：正式业务和 DMPC 配置

### D3. 补齐测试目录和测试清单

建议新增目录：

- `tests/protocol/`
- `tests/runtime/`
- `tests/agents/`
- `tests/dmpc/`

建议测试范围：

- 协议对象序列化
- DMPC 命令反序列化
- 状态管理增强项
- 多 Agent 路由
- 单区局部控制器样例
- 失败与 fallback 场景

### D4. 补齐 SDK 文档目录

建议新增或更新文档：

- Python SDK 架构设计说明书
- Python SDK 领域模型说明书
- Python SDK 验证与验收方案
- Python SDK DMPC 演进改造方案
- Python SDK 改造任务拆解清单
- 新增一份“Python SDK 快速接入与 DMPC 开发指南”

### D5. 新增对接中央的联调样例

建议新增目录：

- `examples/dmpc_with_central/`

内容建议：

- 一个接收中央目标的局部控制器示例
- 一个执行反馈回传示例
- 一个边界量更新示例

## 8. 模块级任务清单

### 协议模块

涉及路径：

- `hydros_agent_sdk/protocol/`

任务：

- 新建 `dmpc_models.py`
- 新建 `dmpc_commands.py`
- 视需要新建 `dmpc_events.py`
- 更新 `commands.py` 的 Envelope 分发
- 增加协议对象单元测试

### 运行时模块

涉及路径：

- `coordination_client.py`
- `coordination_callback.py`
- `state_manager.py`
- `message_filter.py`
- `multi_agent.py`

任务：

- 接入新命令
- 新增控制区运行时状态
- 增强多 Agent 路由
- 补齐日志上下文和过滤规则

### Agent 模块

涉及路径：

- `hydros_agent_sdk/agents/`

任务：

- 新增 `local_dmpc_agent.py`
- 新增 `boundary_aware_agent.py`
- 整理现有 Agent 抽象层职责
- 增加单区样例 Agent

### 配置模块

涉及路径：

- `agent_config.py`
- `config_loader.py`

任务：

- 扩展 YAML 模型
- 补齐配置优先级说明
- 增加 DMPC 配置示例

### 示例与测试模块

涉及路径：

- `examples/`
- `tests/`

任务：

- 单区 DMPC 样例
- 中央联调样例
- 自动化测试覆盖

## 9. 里程碑建议

### M1：对象和协议层完成

完成标准：

- DMPC 对象和命令都已建模
- 新旧协议兼容
- 测试通过

### M2：运行时增强完成

完成标准：

- 状态管理和多 Agent 宿主可承载控制区场景
- 新命令收发可用

### M3：单区局部控制器样例完成

完成标准：

- 单区局部控制器可跑通最小闭环
- 有配置、样例和测试

### M4：中央联调样例完成

完成标准：

- 中央目标下发到 Python 局部控制器链路跑通
- 执行反馈回传跑通

### M5：文档和验收收敛

完成标准：

- 文档完备
- 验收方案可执行
- 可以进入更复杂场景试点

## 10. 风险控制要求

实施时必须注意：

- 不要把 DMPC 全局协调逻辑塞进 SDK 基础层
- 不要让 `BaseHydroAgent` 变成控制专用巨类
- 不要在没有对象模型的情况下先写复杂业务逻辑
- 不要跳过单区样例直接上多区协同
- 所有新协议对象都要先补测试再进入联调

## 11. 结论

这份拆解清单的核心思想是：

- 先把 Python SDK 从“可运行的开放接入框架”升级为“可表达 DMPC 的开放接入框架”
- 再逐步让它承载局部控制器和支持性 Agent
- 最后通过中央对接样例把它纳入 `hydros` 的 DMPC 闭环体系

如果严格按此清单推进，Python SDK 的演进会保持边界清晰、改造可回退、测试可落地、文档可追踪。
