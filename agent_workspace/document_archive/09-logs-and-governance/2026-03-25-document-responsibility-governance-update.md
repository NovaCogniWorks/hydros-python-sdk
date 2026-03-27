# 2026-03-25 文档职责收口与交付链路治理记录

## 1. 记录目的

本文记录 2026-03-25 对 `agent_workspace` 文档体系进行的职责收口、权威来源澄清、工程输入映射补齐和交付材料边界整理工作，作为后续维护、审阅与交付追踪的依据。

## 2. 本次治理背景

本轮治理的直接目标是解决以下问题：

- 架构、工程、执行三类文档中存在少量职责重复
- 部分工程输入文档与架构输出文档存在口径重复
- 执行侧对外交付文档中存在旧路径引用和来源提示不足
- 顶层索引尚未明确“谁定义、谁转译、谁交付”的权威来源关系

本轮治理以“按职责分层收口”为主，不涉及新的 Python 代码实现任务。

## 3. 本次治理范围

本次处理覆盖以下目录：

- `agent_workspace/architect_agent/`
- `agent_workspace/engineering_agent/`
- `agent_workspace/execution_agent/`
- `agent_workspace/logs/reviews/`
- `agent_workspace/INDEX.md`
- `agent_workspace/README.md`

## 4. 主要治理动作

### 4.1 角色说明文档收口

更新了以下角色说明与目录说明文件：

- `architect_agent/AGENTS.md`
- `architect_agent/README.md`
- `engineering_agent/AGENTS.md`
- `engineering_agent/README.md`
- `execution_agent/README.md`
- `execution_agent/outputs/README.md`
- `agent_workspace/README.md`
- `agent_workspace/INDEX.md`
- `document_archive/ARCHIVE_INDEX.md`

治理重点：

- 明确 `architect_agent` 只负责架构分析、建模、演进设计、验证策略和任务拆解
- 明确 `engineering_agent` 只负责 Python 工程实现、测试、样例和工程素材补齐
- 明确 `execution_agent` 只负责文档、脚手架、demo、联调和交付整理
- 明确 `document_archive` 仅为镜像归档区，不作为主编辑源
- 在顶层补充权威来源说明，避免同一主题在多个目录同时演化

### 4.2 工程输入文档重构

重写并收口了以下工程输入文档：

- `engineering_agent/inputs/python-sdk-architecture-implementation-handoff.md`
- `engineering_agent/inputs/python-sdk-phase1-task-breakdown.md`
- `engineering_agent/inputs/python-senior-engineer-task-intake.md`

治理结果：

- 将三份文档拆分为“总交接说明 + 阶段任务单 + 实施入口”三层
- 去掉三份文档之间的重复架构口径复述
- 明确工程输入文档只承接架构输出，不覆盖架构结论

### 4.3 架构正式输出文档收口

复核并收口了 `architect_agent/outputs/` 下文档边界，重点更新：

- `python-sdk-verification-and-acceptance.md`
- `python-sdk-refactor-task-breakdown.md`

治理结果：

- 将验证文档收口为“验证与验收策略”，不再替代工程测试实现和执行联调留痕
- 将任务拆解文档收口为“架构演进任务拆解”，不再与工程阶段任务单争抢职责
- 保持 `python-sdk-architecture-design.md`、`python-sdk-domain-model.md`、`python-sdk-dmpc-evolution-plan.md` 继续作为架构权威输出

### 4.4 建立架构输出与工程输入映射表

新增：

- `engineering_agent/inputs/architecture-to-engineering-mapping.md`

治理结果：

- 建立 `architect_agent/outputs` 与 `engineering_agent/inputs` 的显式对应关系
- 明确同一主题的权威来源与工程转译入口
- 补充按角色的阅读顺序建议和冲突处理规则
- 将该映射文档接入 `engineering_agent/README.md` 与 `INDEX.md`

### 4.5 执行侧交付文档收口

更新了以下执行侧文档：

- `execution_agent/outputs/docs/python-sdk-refactor-plan.md`
- `execution_agent/outputs/docs/python-sdk-external-integration-guide.md`
- `execution_agent/outputs/packages/external-delivery-package/README.md`
- `execution_agent/outputs/packages/external-delivery-package/01-external-integration-readme.md`
- `execution_agent/outputs/packages/external-delivery-package/02-configuration-templates.md`
- `execution_agent/outputs/packages/external-delivery-package/03-startup-checklist.md`
- `execution_agent/outputs/packages/external-delivery-package/04-joint-debug-command-examples.md`
- `execution_agent/outputs/packages/external-delivery-package/05-delivery-acceptance-checklist.md`

治理重点：

- 修正拆分后 `docs / scripts / packages` 目录下的真实路径引用
- 明确这些文档属于执行侧交付材料，不替代架构文档或工程实现说明
- 补充“架构边界和实现行为以上游为准”的来源提示
- 统一对外交付包的语气，避免执行侧文档被误读为新的设计源文档

## 5. 当前治理后状态

经过本轮治理，当前 `agent_workspace` 的文档职责链路已收敛为：

- `architect_agent/outputs/`：定义系统定位、架构分层、领域模型、DMPC 演进、验证策略和架构级任务主线
- `engineering_agent/inputs/`：将架构结论转译为工程实施入口、阶段任务单和实施约束
- `execution_agent/outputs/`：将既有架构与工程结果整理为对外交付文档、脚手架、demo、联调和验收材料
- `document_archive/`：承担镜像归档和分类检索，不具备覆盖原始路径文档的权力

整体状态已从“主题分散、边界交叠”收敛为“定义、转译、交付三层清晰”的文档体系。

## 6. 当前残余注意事项

虽然主链路已经收口，但后续维护仍需注意：

1. 新的架构主题必须先写入 `architect_agent/outputs/`，不要直接在 `engineering_agent/inputs/` 中定义新边界。
2. 新的工程说明如果只是对架构结论的转译，应优先追加到既有输入文档，而不是新增平行源文档。
3. 新的交付文档、脚手架和 demo 应持续落入 `execution_agent/outputs/`，并补来源提示。
4. 如后续同步归档副本，需确保 `document_archive/` 不落后于原始路径文档版本。

## 7. 后续维护建议

建议下一步继续执行以下事项：

1. 将本轮更新后的关键文档同步复制归档到 `document_archive/`
2. 如后续继续新增架构主题，先补 `architecture-to-engineering-mapping.md` 中的映射关系
3. 如工程侧开始正式实施，要求其结果摘要回写 `engineering_agent/outputs/`
4. 如执行侧继续扩充交付包，保持所有新文档都带有来源说明和角色边界说明

## 8. 相关文档

- `agent_workspace/README.md`
- `agent_workspace/INDEX.md`
- `architect_agent/AGENTS.md`
- `engineering_agent/AGENTS.md`
- `execution_agent/README.md`
- `engineering_agent/inputs/architecture-to-engineering-mapping.md`
- `architect_agent/outputs/python-sdk-verification-and-acceptance.md`
- `architect_agent/outputs/python-sdk-refactor-task-breakdown.md`

## 9. 结论

本轮治理的核心成果不是新增文档数量，而是明确了文档的权力边界：

- 谁负责定义
- 谁负责承接
- 谁负责交付

只要后续持续按这一规则维护，`agent_workspace` 就可以保持可索引、可审阅、可交付、可持续演进的状态。
