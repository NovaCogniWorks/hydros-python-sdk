# Python SDK 架构实现交接总说明

## 1. 文档目的

本文是面向 `engineering_agent` 的总交接说明，用于把 `architect_agent` 已确认的架构结论转交给 Python 高级工程师执行。

本文只回答四个问题：

- Python SDK 的已确认定位是什么
- 工程实现必须遵守哪些边界
- 第一阶段实施的总方向是什么
- 具体任务单和实施入口去哪里看

## 2. 适用范围

本文适用于 `hydros_agent_sdk` 的 Python 工程实现、结构化重构、样例补齐和交付素材补齐。

不适用于：

- 重新定义中央智能体与 Python SDK 的体系边界
- 重新论证 DMPC 顶层理论口径
- 重新制定对外交付编排规范

以上内容分别以：

- `architect_agent/outputs/` 为架构权威来源
- `execution_agent/README.md` 与 `execution_agent/outputs/README.md` 为交付组织权威来源

## 3. 已确认架构前提

工程侧必须把以下内容视为已确认前提，而不是重新讨论项：

- `hydros_agent_sdk` 是 Python Agent 运行时 SDK，不是完整中央调度平台
- Java 中央智能体负责全局协调、协议主链路、目标分解与上下文组织
- Python SDK 负责协议接入、Agent 生命周期、多 Agent 托管和开放接入底座
- DMPC 语义应通过扩展对象层和上层抽象承载，不能直接污染基础层

## 4. 工程实现必须遵守的总边界

### 4.1 定位边界

工程实现必须保持 `hydros_agent_sdk` 的以下定位：

- Python Agent 运行时宿主
- 协同协议 Python 侧实现
- 多 Agent 单进程托管框架
- 配置、日志、错误处理和状态隔离基础设施

### 4.2 分层边界

实现时必须遵守以下分层：

- 协议模型层
- Agent 行为抽象层
- 协同运行时层
- 状态与隔离层
- 配置与基础设施层
- DMPC 扩展层

### 4.3 禁止事项

- 不能把 Python SDK 做成中央智能体替代实现
- 不能直接把 DMPC 全局协调语义压进 `BaseHydroAgent`
- 不能在没有对象层设计前直接硬写复杂 DMPC 业务逻辑
- 不能破坏现有外部使用方式却不补兼容层
- 不能替代 `execution_agent` 定义最终交付编排

## 5. 第一阶段总方向

第一阶段只做“内部架构整理和扩展位清理”，不追求一次性补齐 DMPC 全量能力。

建议总方向：

1. 先稳运行时主骨架
2. 冻结通用 Agent 基类边界
3. 为协议对象拆分和 DMPC 扩展留出挂载位
4. 为后续脚手架、demo 和外部集成保持兼容

## 6. 文档分工

本组输入文档按以下方式使用：

- 本文：总交接说明，定义已确认前提、总边界和阅读顺序
- `python-sdk-phase1-task-breakdown.md`：第一阶段任务序列、验收口径和禁区清单
- `python-senior-engineer-task-intake.md`：实施入口、阅读顺序、输出去向和异常回流规则

## 7. 必读上游文档

进入实现前，必须优先阅读：

- `architect_agent/outputs/python-sdk-architecture-design.md`
- `architect_agent/outputs/python-sdk-domain-model.md`
- `architect_agent/outputs/python-sdk-dmpc-evolution-plan.md`
- `architect_agent/outputs/python-sdk-verification-and-acceptance.md`
- `architect_agent/outputs/python-sdk-refactor-task-breakdown.md`

## 8. 结论

工程实施应按“先稳运行时骨架，再补扩展对象层，再推进 DMPC 抽象”的顺序推进。

本文的目的，是让高级工程师直接进入实现，而不是再次进行体系级边界讨论。
