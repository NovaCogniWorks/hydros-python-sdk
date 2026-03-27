# 架构输出与工程输入映射表

## 1. 文档目的

本文用于建立 `architect_agent/outputs` 与 `engineering_agent/inputs` 之间的显式映射关系，明确：

- 哪些文档是架构权威来源
- 哪些文档是面向工程侧的转译输入
- 同一主题应优先阅读哪一份
- 当内容出现重复时应以谁为准

本文是职责边界和文档导航的桥接件，不替代任何专题设计文档、工程任务单或交付说明。

## 2. 使用原则

- 架构定义类内容以 `architect_agent/outputs/` 为权威来源
- 工程实施类内容以 `engineering_agent/inputs/` 为执行入口
- 若两者出现表述重复，工程输入文档只承担转译职责，不得覆盖架构结论
- 交付整理、脚手架、demo 与发布结构不在本文定义，统一以下游 `execution_agent` 文档为准

## 3. 总体映射关系

| 架构输出文档 | 工程输入文档 | 映射关系 | 权威来源 |
| --- | --- | --- | --- |
| `python-sdk-architecture-design.md` | `python-sdk-architecture-implementation-handoff.md` | 架构定位、分层边界、职责约束转译为工程总交接说明 | 架构输出 |
| `python-sdk-domain-model.md` | `python-sdk-architecture-implementation-handoff.md` | 核心对象边界和扩展约束转译为工程实现前提 | 架构输出 |
| `python-sdk-dmpc-evolution-plan.md` | `python-sdk-phase1-task-breakdown.md` | 演进路线转译为第一阶段实施顺序和任务主线 | 架构输出 |
| `python-sdk-verification-and-acceptance.md` | `python-senior-engineer-task-intake.md` | 验证策略转译为工程最小验证要求与回流规则 | 架构输出 |
| `python-sdk-refactor-task-breakdown.md` | `python-sdk-phase1-task-breakdown.md` | 架构级任务拆解转译为工程阶段任务单 | 架构输出 |

## 4. 分主题映射说明

### 4.1 系统定位与分层

架构权威文档：

- `architect_agent/outputs/python-sdk-architecture-design.md`

工程承接文档：

- `engineering_agent/inputs/python-sdk-architecture-implementation-handoff.md`

说明：

- 前者负责定义 Python SDK 在 `hydros` 体系中的定位、六层架构、与中央智能体的边界关系
- 后者只把这些结论转译成工程侧必须遵守的定位边界和分层边界
- 如果工程侧文档与架构设计说明出现冲突，应以架构设计说明为准

### 4.2 领域模型与对象边界

架构权威文档：

- `architect_agent/outputs/python-sdk-domain-model.md`

工程承接文档：

- `engineering_agent/inputs/python-sdk-architecture-implementation-handoff.md`

说明：

- 前者负责定义 `SimulationContext`、`BaseHydroAgent`、`AgentStateManager` 等核心对象边界
- 后者只把对象边界转成工程禁区，例如不能把 DMPC 高层语义直接塞进基础对象
- 对象定义和聚合根识别的解释权属于架构文档，不属于工程输入文档

### 4.3 DMPC 演进路线

架构权威文档：

- `architect_agent/outputs/python-sdk-dmpc-evolution-plan.md`

工程承接文档：

- `engineering_agent/inputs/python-sdk-phase1-task-breakdown.md`

说明：

- 前者负责定义 DMPC 对象层、抽象层、运行时层和中央协同对接层的演进路线
- 后者只负责抽取当前第一阶段需要先落地的那一部分任务
- 如果后续阶段扩展超出第一阶段任务单，仍应回到架构演进方案获取上游口径

### 4.4 验证策略与放行口径

架构权威文档：

- `architect_agent/outputs/python-sdk-verification-and-acceptance.md`

工程承接文档：

- `engineering_agent/inputs/python-senior-engineer-task-intake.md`

说明：

- 前者负责定义验证分层、关键场景、放行指标、证据链类别和角色分工
- 后者只负责要求工程侧在每次实现后补齐最小验证，并说明异常时如何回流
- 具体验证执行、日志和回归记录不在架构文档中落地，由工程侧与执行侧承接

### 4.5 任务拆解与阶段推进

架构权威文档：

- `architect_agent/outputs/python-sdk-refactor-task-breakdown.md`

工程承接文档：

- `engineering_agent/inputs/python-sdk-phase1-task-breakdown.md`
- `engineering_agent/inputs/python-senior-engineer-task-intake.md`

说明：

- 前者负责定义四条主线、阶段里程碑、模块方向和风险控制要求
- `phase1-task-breakdown` 负责抽出第一阶段的具体任务顺序和最低验收口径
- `task-intake` 负责告诉工程师按什么顺序读、做完后往哪里写、什么情况下暂停

## 5. 阅读顺序建议

如果角色是 `engineering_agent`，建议按以下顺序阅读：

1. `engineering_agent/AGENTS.md`
2. `engineering_agent/inputs/python-sdk-architecture-implementation-handoff.md`
3. `engineering_agent/inputs/python-sdk-phase1-task-breakdown.md`
4. `engineering_agent/inputs/python-senior-engineer-task-intake.md`
5. `architect_agent/outputs/python-sdk-architecture-design.md`
6. `architect_agent/outputs/python-sdk-domain-model.md`
7. `architect_agent/outputs/python-sdk-dmpc-evolution-plan.md`
8. `architect_agent/outputs/python-sdk-verification-and-acceptance.md`
9. `architect_agent/outputs/python-sdk-refactor-task-breakdown.md`

如果角色是 `execution_agent`，建议先看：

1. `execution_agent/README.md`
2. `execution_agent/outputs/README.md`
3. 需要引用的 `architect_agent/outputs/` 相关专题文档
4. 需要引用的 `engineering_agent/outputs/` 或实现摘要

## 6. 冲突处理规则

当文档之间出现冲突时，按以下顺序判定：

1. 架构边界、对象定义、演进路线、验证策略：以 `architect_agent/outputs/` 为准
2. 工程实施顺序、最小验证要求、输出去向：以 `engineering_agent/inputs/` 和 `engineering_agent/AGENTS.md` 为准
3. 交付目录、脚手架、demo、发布结构：以 `execution_agent` 相关文档为准
4. 归档副本与原始路径冲突：以原始路径文档为准，`document_archive` 不具备覆盖权

## 7. 建议落点

建议后续维护时遵守以下规则：

- 新的架构主题先写入 `architect_agent/outputs/`
- 需要交给工程侧执行时，再在 `engineering_agent/inputs/` 中生成转译输入
- 不要跳过架构输出直接在工程输入中定义新边界
- 不要让同一个主题在多个目录长期平行演化

## 8. 结论

这份映射表的作用，是把“架构定义”和“工程承接”明确拆开：

- `architect_agent/outputs/` 负责定义
- `engineering_agent/inputs/` 负责转译和执行入口
- `execution_agent` 负责交付化落地

只要持续按这个映射维护，后续文档体系就不会再次回到职责混写状态。
