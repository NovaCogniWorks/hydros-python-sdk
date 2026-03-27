# Python SDK 改造执行说明

## 1. 文档目的

本文基于 `hydros_agent_sdk` 当前代码实现，提供一份面向执行侧和交付侧的改造说明，目标是把已确认的架构改造方向整理为可沟通、可交付、可跟踪的实施说明。

本文不负责重新定义架构边界。关于系统定位、领域模型、DMPC 演进路线和验证策略，应以 `architect_agent/outputs/` 下正式文档为准。

适用范围：

- `hydros_agent_sdk` 运行时骨架优化
- 协议模型与命令模块扩展治理
- Agent 抽象层收敛
- 多 Agent 宿主能力增强
- 配置体系统一与长期治理
- 对外交付脚手架与接入文档收敛

## 2. 当前执行侧关注重点

结合现有项目结构和代码实现，当前对外沟通时最需要聚焦的改造重点有六类：

- `SimCoordinationClient` 职责过重
- `BaseHydroAgent` 已接近通用基类职责边界，不宜继续扩张
- 协议对象集中在少数文件中，未来会快速膨胀
- `MultiAgentCallback` 已有价值，但尚未进化成高阶宿主核心
- 本地配置与远程配置双入口并存，职责边界尚不够清晰
- 对外脚手架需要持续保持“可运行、可验证、最小集成改造”特性

这些问题并不会立刻导致项目不可用，但如果继续叠加 DMPC、新命令、新 Agent 类型和更多场景，维护成本会明显上升。

## 3. 执行侧沟通口径

建议按“先稳骨架，再放扩展，最后收口交付”的顺序组织实施沟通：

1. 先拆运行时核心类
2. 再冻结基础 Agent 抽象层
3. 再整理协议对象层
4. 再增强多 Agent 宿主
5. 再统一配置体系
6. 最后收口脚手架、接入文档和样例工程

执行侧在对外说明时，应把这六点视为实施主线摘要，而不是独立的新架构定义。

## 4. 对外交付时应如何表述

### 4.1 关于 `SimCoordinationClient`

建议表述为：

- 当前运行时核心类职责偏重
- 后续会向“编排入口 + 专用内部组件”方向治理
- 外部 API 应尽量保持稳定

### 4.2 关于 `BaseHydroAgent`

建议表述为：

- 当前通用基类定位已明确
- 后续 DMPC 或边界感知能力应通过上层抽象承载
- 不建议继续把高层业务语义压入通用基类

### 4.3 关于协议对象层

建议表述为：

- 当前协议模型已可用
- 后续将按核心协议与 DMPC 扩展协议逐步拆分
- 对外导入路径应尽量保持兼容

### 4.4 关于多 Agent 宿主

建议表述为：

- 当前 `MultiAgentCallback` 已支持多实例托管
- 后续会增强控制区路由和混合托管能力
- 其定位仍是框架宿主，而不是业务编排器

### 4.5 关于配置体系

建议表述为：

- 后续会进一步明确 `env.properties`、`agent.properties` 和远程 YAML 的职责边界
- DMPC 专项配置将优先进入远程 YAML

### 4.6 关于对外脚手架

建议表述为：

- 对外脚手架的目标是生成“可运行、可验证、可二次开发”的独立工程
- 当前推荐的最小集成面应收敛到 `conf/env.properties`、`conf/agent.properties`、`agent_app/user_logic.py`
- `agent_app/business_engine.py`、`agent_app/runtime.py`、`agent_app/support.py` 和 `agent_app/agent_impl.py` 默认作为运行时适配层保留，不要求外部用户优先修改
- 启动与本地接入优先通过 `scripts/bootstrap.ps1` 和 `.pth` 源码直连方式完成，而不是要求外部用户先处理 SDK 打包问题
- 交付侧文档、README、脚手架生成内容和测试断言必须保持一致，避免对外口径分裂

## 5. 推荐执行顺序

### 阶段一：稳住运行时骨架

优先关注：

- 拆分 `SimCoordinationClient`
- 冻结 `BaseHydroAgent` 的职责边界

### 阶段二：整理协议扩展口

优先关注：

- 拆分协议对象与命令模块

### 阶段三：增强多 Agent 宿主

优先关注：

- 增强 `MultiAgentCallback`

### 阶段四：统一工程配置

优先关注：

- 统一配置体系和配置说明

### 阶段五：收口交付物

优先关注：

- 对齐脚手架生成内容、README、集成文档和烟测脚本
- 保证外部用户启动路径尽量短，优先修改配置和 `user_logic.py`
- 保持样例工程与真实模板输出一致，避免文档先行或模板漂移

## 6. 角色边界说明

在这份执行说明对应的工作链路中：

- `architect_agent` 负责定义改造边界、演进路线、放行口径
- `engineering_agent` 负责具体代码改造、测试和实现摘要
- `execution_agent` 负责将这些内容整理为对外交付文档、脚手架、demo 和验收材料

## 7. 当前已落地的交付收口点

截至当前版本，交付侧已形成以下收口原则：

- 脚手架支持 `twins`、`ontology`、`central` 模板及其基类映射
- 生成工程默认包含 `scripts/bootstrap.ps1`、`scripts/run.ps1` 和 `tests/test_scaffold_import.py`
- `business_engine.py` 已退化为适配层，主要业务逻辑委托给 `user_logic.py`
- 本地烟测至少覆盖导入链路、配置加载和关键文件存在性

这些收口点不等于架构终态，但应作为当前对外说明和交付材料的统一基线。

## 8. 关联文档

架构权威来源：

- `architect_agent/outputs/python-sdk-architecture-design.md`
- `architect_agent/outputs/python-sdk-domain-model.md`
- `architect_agent/outputs/python-sdk-dmpc-evolution-plan.md`
- `architect_agent/outputs/python-sdk-verification-and-acceptance.md`
- `architect_agent/outputs/python-sdk-refactor-task-breakdown.md`

工程实施入口：

- `engineering_agent/inputs/architecture-to-engineering-mapping.md`
- `engineering_agent/inputs/python-sdk-architecture-implementation-handoff.md`
- `engineering_agent/inputs/python-sdk-phase1-task-breakdown.md`
- `engineering_agent/inputs/python-senior-engineer-task-intake.md`

对外交付入口：

- `execution_agent/outputs/docs/python-sdk-external-integration-guide.md`
- `execution_agent/outputs/scripts/generate-hydros-agent-project.ps1`

## 9. 结论

这份文档的作用，是为执行侧和交付侧提供一致的改造说明口径，而不是替代架构文档或工程任务单。

最关键的执行共识仍然是：先把 SDK 的主骨架从可用提升到可持续演进，再逐步承接 DMPC 扩展和更复杂的多 Agent 场景，并把对外脚手架收敛为低集成成本、可验证、可维护的标准交付面。
