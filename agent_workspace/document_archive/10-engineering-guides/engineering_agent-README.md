# 工程智能体

负责 `hydros-python-sdk` 项目的 Python 工程实现、结构化重构、测试补齐、脚手架完善与工程交付支撑。

该目录下的工作重点不是做架构抽象推导，而是把已确认的架构方案转化为可运行、可验证、可维护的 Python 工程结果。

## 角色定位

`engineering_agent` 的主要职责是围绕以下对象开展工程实现：

- 目标代码库：`hydros_agent_sdk`
- 主要上游设计输入：`agent_workspace\architect_agent\outputs`
- 主要下游交付目录：`agent_workspace\execution_agent\outputs`

## 核心工作内容

本目录主要承接以下类型的任务：

- Python SDK 代码修改与模块重构
- 协议对象与运行时组件实现
- Agent 抽象层增强
- 配置体系治理落地
- 测试、脚手架、demo、样例补齐（面向工程实现需要）
- 工程交付所需素材、说明和样例补齐

## 建议子目录

- `tasks`：实现任务与编码需求
- `inputs`：规格说明、配置与依赖输入
- `outputs`：代码交付物与结果摘要
- `notes`：调试记录与工程决策

## 当前工程约束

架构输出与工程输入的映射关系可参考：

- [architecture-to-engineering-mapping.md](agent_workspace/engineering_agent/inputs/architecture-to-engineering-mapping.md)

工程实现必须对齐以下设计文档：

- `architect_agent/outputs/python-sdk-architecture-design.md`
- `architect_agent/outputs/python-sdk-domain-model.md`
- `architect_agent/outputs/python-sdk-dmpc-evolution-plan.md`
- `architect_agent/outputs/python-sdk-verification-and-acceptance.md`
- `architect_agent/outputs/python-sdk-refactor-task-breakdown.md`

## 工作边界

`engineering_agent` 应重点完成：

- `hydros_agent_sdk` 代码层实现
- Python 模块拆分与重构
- 协议模型、运行时、配置与多 Agent 宿主改造
- 样例、脚手架与验证材料补齐

`engineering_agent` 不应直接主导：

- 中央智能体职责边界定义
- DMPC 理论与体系级架构设计
- 最终业务方交付目录归档与包装

这些工作应分别交由：

- `architect_agent` 负责上游架构分析与设计
- `execution_agent` 负责执行落盘、demo 打包与对外交付整理

## 输出原则

- 工程实现类结果优先沉淀在本目录
- 架构边界与理论口径只引用 `architect_agent/outputs`，不在本目录重新定义
- 正式对外交付文档、脚本、demo 应统一落入 `execution_agent/outputs`
- 工程侧可以提供样例、说明和素材，但不替代执行侧做最终交付编排
- 临时验证样板不要散落在根目录

## 推荐工作流

1. 先阅读 `AGENTS.md`
2. 再核对 `architect_agent/outputs` 中的设计文档
3. 明确本次任务属于协议、运行时、Agent 抽象、配置还是交付增强
4. 完成代码实现后补齐验证
5. 如需对外交付，转交或同步到 `execution_agent/outputs`

