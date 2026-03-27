# Agent Workspace Index

## 1. 工作区总览

`agent_workspace` 用于承载 `hydros-python-sdk` 相关的架构分析、工程实现、执行交付、共享上下文与文档归档。

当前顶层目录：

- `architect_agent/`
- `engineering_agent/`
- `execution_agent/`
- `shared_context/`
- `logs/`
- `document_archive/`

## 2. 三类智能体职责链路

当前工作区按“架构 -> 工程 -> 执行交付”的链路组织：

1. `architect_agent`
   负责上游架构分析、领域建模、理论对齐、DMPC 演进设计和验证策略制定
2. `engineering_agent`
   负责将架构方案落实为 Python 工程实现、模块重构、测试和脚手架增强
3. `execution_agent`
   负责将工程结果整理成最终文档、脚本、demo、样例和对外交付包

这三类角色的关系是：

- `architect_agent` 提供设计输入
- `engineering_agent` 负责代码与工程落地
- `execution_agent` 负责运行、整理、归档和交付输出

权威来源约束：

- 体系级边界、理论口径和验证策略以 `architect_agent` 为准
- 工程实现方法、模块改造和验证记录以 `engineering_agent` 为准
- 交付文档、脚本、demo 和发布结构以 `execution_agent` 为准
- `document_archive` 仅承担镜像归档与检索，不承担主编辑职责

## 3. 目录说明

### 3.1 architect_agent

角色说明文件：

- [AGENTS.md](agent_workspace/architect_agent/AGENTS.md)
- [README.md](agent_workspace/architect_agent/README.md)

职责：

- 中央 Java 智能体与 Python SDK 的职责对照
- 架构设计说明书输出
- 领域模型识别与边界定义
- DMPC 演进方案和验证策略制定

关键目录：

- `architect_agent/inputs/`
- `architect_agent/outputs/`
- `architect_agent/tasks/validation_artifacts/`

当前主要产物：

- [python-sdk-architecture-design.md](agent_workspace/architect_agent/outputs/python-sdk-architecture-design.md)
- [python-sdk-domain-model.md](agent_workspace/architect_agent/outputs/python-sdk-domain-model.md)
- [python-sdk-verification-and-acceptance.md](agent_workspace/architect_agent/outputs/python-sdk-verification-and-acceptance.md)
- [python-sdk-dmpc-evolution-plan.md](agent_workspace/architect_agent/outputs/python-sdk-dmpc-evolution-plan.md)
- [python-sdk-refactor-task-breakdown.md](agent_workspace/architect_agent/outputs/python-sdk-refactor-task-breakdown.md)

### 3.2 engineering_agent

角色说明文件：

- [AGENTS.md](agent_workspace/engineering_agent/AGENTS.md)
- [README.md](agent_workspace/engineering_agent/README.md)

职责：

- `hydros_agent_sdk` Python 工程实现
- 协议模型、运行时和 Agent 抽象层改造
- 配置体系与多 Agent 宿主增强
- 测试、样例、脚手架和工程交付支撑

关键目录：

- `engineering_agent/tasks/`
- `engineering_agent/inputs/`
- `engineering_agent/outputs/`
- `engineering_agent/notes/`

说明：

- 该目录当前以角色定义和实现输入为主，后续主要承接 Python 代码级实现任务
- 架构输出与工程输入的对应关系可参考 [architecture-to-engineering-mapping.md](agent_workspace/engineering_agent/inputs/architecture-to-engineering-mapping.md)

### 3.3 execution_agent

角色说明文件：

- [README.md](agent_workspace/execution_agent/README.md)
- [outputs/README.md](agent_workspace/execution_agent/outputs/README.md)

职责：

- 执行结果整理与归档
- 脚手架脚本生成和校验
- demo 工程落盘、修正与补充说明
- 对外交付文档、样例命令、配置模板和发布结构整理

关键目录：

- `execution_agent/outputs/docs/`
- `execution_agent/outputs/scripts/`
- `execution_agent/outputs/packages/`

当前主要产物：

文档：

- [python-sdk-refactor-plan.md](agent_workspace/execution_agent/outputs/docs/python-sdk-refactor-plan.md)
- [python-sdk-external-integration-guide.md](agent_workspace/execution_agent/outputs/docs/python-sdk-external-integration-guide.md)

脚本：

- [generate-hydros-agent-project.ps1](agent_workspace/execution_agent/outputs/scripts/generate-hydros-agent-project.ps1)

交付包：

- [external-delivery-package](agent_workspace/execution_agent/outputs/packages/external-delivery-package)

交付包内部关键内容：

- [交付包总览 README](agent_workspace/execution_agent/outputs/packages/external-delivery-package/README.md)
- [外部集成 README](agent_workspace/execution_agent/outputs/packages/external-delivery-package/01-external-integration-readme.md)
- [配置模板](agent_workspace/execution_agent/outputs/packages/external-delivery-package/02-configuration-templates.md)
- [启动检查清单](agent_workspace/execution_agent/outputs/packages/external-delivery-package/03-startup-checklist.md)
- [联调命令样例](agent_workspace/execution_agent/outputs/packages/external-delivery-package/04-joint-debug-command-examples.md)
- [交付验收清单](agent_workspace/execution_agent/outputs/packages/external-delivery-package/05-delivery-acceptance-checklist.md)
- [demo-hydros-agent-project](agent_workspace/execution_agent/outputs/packages/external-delivery-package/demo-hydros-agent-project)
- [demo-central-scheduling-agent-project](agent_workspace/execution_agent/outputs/packages/external-delivery-package/demo-central-scheduling-agent-project)

### 3.4 shared_context

职责：

- 共享规范
- 协作文档
- 模板与参考材料沉淀

关键文件：

- [README.md](agent_workspace/shared_context/README.md)
- [review_template.md](agent_workspace/shared_context/templates/review_template.md)
- [task_template.md](agent_workspace/shared_context/templates/task_template.md)

### 3.5 logs

职责：

- 日志说明
- 运行记录
- 问题追踪
- 评审与治理说明

关键文件：

- [README.md](agent_workspace/logs/README.md)

### 3.6 document_archive

职责：

- 全量文档镜像归档
- 统一文档检索
- 分类化文档存档与审阅支持

关键文件：

- [ARCHIVE_INDEX.md](agent_workspace/document_archive/ARCHIVE_INDEX.md)

## 4. 当前推荐查找路径

如果要找正式内容，建议按以下顺序查找：

1. 工作区总览与索引：`README.md`、`INDEX.md`
2. 架构设计与分析：`architect_agent/outputs/`
3. Python 工程实现说明：`engineering_agent/AGENTS.md`、`engineering_agent/README.md`
4. 对外交付文档：`execution_agent/outputs/docs/`
5. 脚手架与执行脚本：`execution_agent/outputs/scripts/`
6. 业务方交付包与 demo：`execution_agent/outputs/packages/external-delivery-package/`
7. 全量文档归档：`document_archive/`

## 5. 当前工作区状态

当前工作区已经完成以下整理：

- 三类智能体目录的 README/AGENTS 已基本对齐
- `architect_agent` 根目录已清理临时验证工程
- 临时验证工程已归档到 `architect_agent/tasks/validation_artifacts/`
- `execution_agent/outputs` 已拆分为 `docs / scripts / packages`
- 对外交付包、两个 demo 和启动脚本已落盘
- `document_archive/` 已建立统一文档归档副本


