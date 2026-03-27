# 架构智能体

负责 `hydros` 体系的架构设计、领域建模、理论对齐、DMPC 演进设计与验证策略制定。

该目录下的工作不以直接工程编码为主，而是为后续 Python 工程实现和执行交付提供稳定、清晰、可验证的上游输入。

## 角色定位

`architect_agent` 的主要职责是围绕以下三类基座进行分析和设计：

- Java 中央智能体代码：`..\..\agent\hydros-agent-central`
- Python SDK 代码：`hydros_agent_sdk`
- 规范与理论文档：`..\..\doc\wjh-docs\hydros系统分析与规范`

## 核心输出类型

本目录主要输出以下内容：

- 架构设计说明书
- 领域模型说明书
- 理论与代码对齐说明
- DMPC 演进改造方案
- 验证与验收策略（方案级、矩阵级，不包含执行脚本本身）
- 重构优先级与任务拆解建议

## 建议子目录

- `tasks`：架构任务、设计需求与临时验证归档
- `inputs`：上游需求、中央智能体参考文档与输入材料
- `outputs`：正式设计产物与评审输出
- `notes`：分析记录与决策说明

## 当前补充约定

- `tasks/validation_artifacts`：脚手架验证工程、临时样板、自测归档
- 正式对外交付物不要放在 `architect_agent` 根目录
- 面向业务方的最终文档、脚本和 demo 统一放入 `execution_agent/outputs`
- 对外交付结构建议可由本目录提出，但只作为交接输入，不在本目录承担最终交付整理

## 工作边界

`architect_agent` 应重点完成：

- 中央 Java 架构与 Python SDK 架构的职责对照
- 协同协议、事件对象、场景配置与运行链路分析
- Python SDK 的分层设计、领域对象识别和演进边界定义
- DMPC 场景下中央与局部 Agent 的职责拆分

`architect_agent` 不应直接主导：

- 大规模 Python 工程编码实现
- 业务方最终脚手架与 demo 交付整理
- 执行验证脚本与最终运行包落地

这些工作应分别交由：

- `engineering_agent` 负责工程实现
- `execution_agent` 负责执行落盘、脚手架、demo 和交付归档

## 推荐工作流

1. 先阅读 `AGENTS.md`
2. 再核对 `architect_agent/inputs` 和 `architect_agent/outputs`
3. 分析时同时对齐中央代码、Python SDK 代码和规范文档
4. 形成结论后，将正式产物写入 `architect_agent/outputs`
5. 如需交付脚本、样例或 demo，转交 `execution_agent`


