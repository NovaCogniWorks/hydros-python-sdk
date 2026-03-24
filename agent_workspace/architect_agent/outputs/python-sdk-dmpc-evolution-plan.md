# Python SDK DMPC 演进改造方案

## 1. 文档目的

本文提出 `hydros_agent_sdk` 面向 DMPC 体系演进的改造方案。目标不是把 Python SDK 直接改造成完整中央调度系统，而是让它能够稳定承接以下两类能力：

- Python 侧局部 DMPC 控制器
- Python 侧支持性 Agent 与中央协调配合

同时保证与输入目录中中央智能体 DMPC 演进方案保持一致的职责边界：

- 中央负责全局目标分解与约束协调
- Python SDK 负责承载局部控制器、仿真 Agent 和支持 Agent 的运行时与协议接入能力

## 2. 当前基线判断

当前 Python SDK 已具备以下 DMPC 演进基础：

- 统一任务上下文 `SimulationContext`
- 协同命令和响应协议模型
- 单 Agent 与多 Agent 宿主框架
- Tick 驱动与事件驱动回调框架
- 本地/远端过滤与多任务隔离
- 代表性 `CentralSchedulingAgent`、`OntologySimulationAgent` 等抽象 Agent 类型

但仍缺少以下 DMPC 关键语义：

- 控制区对象
- 区间耦合和边界变量对象
- 中央下发区级目标对象
- 局部求解输入输出对象
- 执行反馈标准对象
- Python 侧全局认知上下文对象

因此，当前 Python SDK 的状态应被定义为：

> DMPC-ready 的 Python Agent 运行时底座，而不是已完成 DMPC 语义封装的控制框架。

## 3. 改造目标

### 3.1 架构目标

- 保留现有协同协议与运行时骨架
- 补齐局部 DMPC 所需的标准对象层
- 支持控制区级局部控制器的编写与托管
- 支持中央协调输出到局部控制器输入的标准映射
- 支持局部求解结果和执行反馈的标准回传

### 3.2 业务目标

- 让 Python SDK 能承载局部控制区 Agent
- 让 Python SDK 能承载 DMPC 支持 Agent，例如状态估计、需求预测、边界预测
- 让 Python SDK 不侵入中央职责，但能无缝接收中央协调结果

### 3.3 工程目标

- 新旧 Agent 接口尽量兼容
- 不破坏现有 Tick、初始化、终止链路
- 允许分阶段引入 DMPC 语义对象
- 支持在单区、双区和多区场景中逐步验证

## 4. 改造原则

- 先补语义对象，再补控制逻辑
- 不把中央协调逻辑硬塞进 Python SDK 基础层
- 保持 `BaseHydroAgent` 的通用性
- 在 SDK 层提供抽象与协议，不在基础层绑定具体优化器
- 允许集中式模式、混合模式、局部 DMPC 模式共存

## 5. 目标架构

建议 Python SDK 向七层结构演进。

### 5.1 基础协议层

保留现有：

- `SimulationContext`
- `HydroAgentInstance`
- 协同命令对象
- MQTT 客户端与消息过滤器

### 5.2 DMPC 语义对象层

新增：

- `DmpcControlZone`
- `DmpcCoupling`
- `DmpcBoundaryVariable`
- `DmpcCoordinationInput`
- `DmpcCoordinationOutput`
- `DmpcLocalSolveInput`
- `DmpcLocalSolveOutput`
- `DmpcExecutionFeedback`

这是最关键的新增层。

### 5.3 局部控制抽象层

新增抽象基类：

- `LocalDmpcAgent`
- `BoundaryAwareAgent`
- `ExecutionFeedbackAwareAgent`

职责：

- 接收区级目标
- 接收边界量
- 执行局部求解
- 输出动作计划与预测轨迹
- 上报执行反馈

### 5.4 局部控制运行时层

在现有 `BaseHydroAgent` 基础上新增：

- 控制区上下文装配
- 边界缓存与同步策略
- 局部求解状态跟踪
- fallback 状态管理

### 5.5 支持性 Agent 层

新增或增强：

- 边界预测 Agent
- 状态估计 Agent
- 参数识别 Agent
- 需求预测 Agent

这些 Agent 不直接执行控制，但为局部 DMPC 提供输入。

### 5.6 多 Agent 编排层

增强 `MultiAgentCallback`：

- 支持一进程内多个局部控制区 Agent
- 支持控制区间的路由与边界同步
- 支持局部控制器与支持性 Agent 混合托管

### 5.7 中央协同对接层

新增协议适配：

- 中央协调输出对象到 Python 局部控制器输入的映射层
- Python 局部求解输出到中央执行反馈对象的映射层

## 6. 建议新增的核心对象

### 6.1 控制区对象

建议新增 `DmpcControlZone`，字段至少包括：

- `zone_id`
- `zone_name`
- `zone_type`
- `managed_objects`
- `owner_agent_code`
- `upstream_zone_ids`
- `downstream_zone_ids`

### 6.2 耦合对象

建议新增 `DmpcCoupling`，字段至少包括：

- `coupling_id`
- `source_zone_id`
- `target_zone_id`
- `coupling_type`
- `signal_policy`
- `sync_interval`

### 6.3 中央协调输入输出对象

建议新增：

- `DmpcCoordinationInput`
- `DmpcCoordinationOutput`

其中输出对象至少包含：

- `global_goal`
- `zone_targets`
- `shared_constraints`
- `valid_until_step`

### 6.4 局部求解对象

建议新增：

- `DmpcLocalSolveInput`
- `DmpcLocalSolveOutput`

输入包含：

- 控制区目标
- 本地状态估计
- 边界预测
- 设备约束
- fallback 上下文

输出包含：

- 动作计划
- 预测轨迹
- solver 状态
- fallback 标记

### 6.5 执行反馈对象

建议新增 `DmpcExecutionFeedback`，至少包含：

- `zone_id`
- `step`
- `observed_state`
- `execution_status`
- `deviation_summary`
- `needs_replan`

## 7. 对现有代码的改造映射

### 7.1 `protocol/models.py`

保留现有身份模型。

新增：

- DMPC 控制区与耦合对象
- 可考虑单独放到 `protocol/dmpc_models.py`

### 7.2 `protocol/commands.py`

保留现有通用命令。

新增：

- `CoordinationTargetDispatchRequest/Response`
- `LocalSolveReportRequest/Response`
- `BoundaryExchangeRequest/Response`
- `ExecutionFeedbackRequest/Response`

建议不要把这些对象塞进现有通用命令类文件过度膨胀，可单独切分为 `protocol/dmpc_commands.py`。

### 7.3 `BaseHydroAgent`

保持其作为通用 Agent 基类，不直接加入过多 DMPC 专有字段。

建议做法：

- 保留 `BaseHydroAgent`
- 在其上新增 `LocalDmpcAgent` 抽象层

### 7.4 `MultiAgentCallback`

当前已经具备多 Agent 托管能力，是最适合承接局部控制区组合运行的模块。

建议增强：

- `context -> zone -> agent` 的映射
- 边界量在上下文内的交换机制
- 区级目标的定向广播

### 7.5 `AgentStateManager`

建议新增：

- 控制区级状态
- 边界量缓存
- 局部求解状态缓存
- fallback 状态记录

但仍应避免把全局水网认知和复杂业务对象全部塞到这里。

### 7.6 `CentralSchedulingAgent`

当前 Python 版更适合作为实验性中央调度抽象基类。

后续建议：

- 不把它发展成中央核心实现的唯一载体
- 可以作为 Python 版中央协调试验宿主
- 更重要的用途是定义与局部控制器协同的抽象接口

## 8. 场景配置改造建议

若 Python SDK 要真正承接 DMPC 局部控制器，建议在 Agent YAML 或场景配置中补充：

- `dmpc_control_zone`
- `dmpc_couplings`
- `dmpc_goal_templates`
- `dmpc_sync_policy`
- `dmpc_fallback_policy`

同时要明确配置优先级：

- `env.properties` 负责节点和连接环境
- `agent.properties` 负责实例化级信息
- 远程 YAML 负责正式业务配置
- DMPC 专项配置建议优先进入远程 YAML

## 9. 分阶段演进路线

### 阶段一：补对象，不改运行时主链路

目标：

- 增加 DMPC 模型对象与协议对象
- 保持现有 Agent 生命周期和协同客户端不变
- 让 SDK 先具备“表达 DMPC”的能力

### 阶段二：引入 `LocalDmpcAgent`

目标：

- 在 `BaseHydroAgent` 上引入局部控制抽象层
- 支持区级目标输入和局部求解输出
- 完成单控制区试点

### 阶段三：增强 `MultiAgentCallback`

目标：

- 支持一进程多控制区 Agent
- 支持边界量交换和区级路由
- 支持局部控制器与支持性 Agent 组合

### 阶段四：对接中央协调输出

目标：

- 建立中央协调输出到 Python 局部控制输入的正式映射
- 建立局部执行反馈回传链路
- 在 `NORMAL` 环境完成混合模式验证

### 阶段五：推进 `SIL/XIL`

目标：

- 用 Python SDK 局部控制器接入更真实的仿真链路
- 验证局部控制器在更复杂环境下的稳定性

## 10. 验证与放行建议

阶段放行建议如下。

### 阶段一放行条件

- DMPC 对象可序列化、可反序列化
- 不影响现有协议对象和 SDK 使用方式

### 阶段二放行条件

- 单区 `LocalDmpcAgent` 可跑通初始化、Tick、目标接收和求解输出

### 阶段三放行条件

- 多控制区单进程运行稳定
- 边界量路由正确

### 阶段四放行条件

- 中央目标下发与局部反馈回传闭环成立
- 与现有中央架构口径一致

## 11. 风险与防御策略

主要风险包括：

- 把 DMPC 语义硬塞到 `BaseHydroAgent`，导致基础层污染
- 协议对象与现有命令体系耦合过深，后期难维护
- `MultiAgentCallback` 过度承担业务编排，导致框架层和业务层混杂
- 过早实现 Python 中央协调器，和 Java 中央职责冲突

防御策略：

- 保持“基础运行时”和“DMPC 语义扩展层”分层
- 中央协调语义以协议输入输出形式进入 SDK，而不是在 SDK 基础层重建中央逻辑
- 优先支持局部控制器和支持性 Agent
- 保持与中央智能体专题文档中职责划分一致

## 12. 结论

Python SDK 面向 DMPC 的正确演进方向不是“把 SDK 变成中央系统”，而是：

> 在保持现有协议宿主和 Agent 运行时骨架稳定的前提下，补齐控制区、协调输入输出、局部求解和执行反馈等标准对象层，使 Python SDK 成为 `hydros` DMPC 局部控制器和支持性 Agent 的稳定承载底座。

这一路线与中央智能体 DMPC 演进方案形成清晰分工：

- 中央决定全局目标与约束
- Python SDK 负责承载局部控制执行与反馈闭环
