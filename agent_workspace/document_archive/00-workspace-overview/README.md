# 智能体工作目录

本工作目录用于承载围绕架构设计、工程实现、执行验证等任务的机器智能体协同工作。

## 目录结构

- `architect_agent`：负责业务架构、系统拆解、理论到代码的映射
- `engineering_agent`：负责实现开发、工程集成与代码交付
- `execution_agent`：负责脚本执行、仿真运行与结果校验
- `shared_context`：负责共享规范、场景、参考资料与模板沉淀
- `logs`：负责运行日志、问题追踪与评审记录
- `document_archive`：负责全量文档归档副本与分类检索

## 基本协作流程

1. 优先阅读共享规范与场景定义。
2. 将角色任务放入对应智能体目录下的 `tasks` 子目录。
3. 将过程输入与最终输出分别沉淀到对应角色目录。
4. 将执行轨迹、问题分析与评审结果记录到 `logs` 目录。

## 权威来源说明

- 架构边界、理论口径、领域模型、DMPC 演进与验证策略：以 `architect_agent/AGENTS.md` 及 `architect_agent/outputs/` 为准
- Python 工程实现边界与实现规范：以 `engineering_agent/AGENTS.md` 和 `engineering_agent/inputs/` 为准
- 对外交付目录、脚本、demo 与交付包组织：以 `execution_agent/README.md` 和 `execution_agent/outputs/README.md` 为准
- `document_archive/` 为镜像归档区，不作为主编辑源

## 当前正式产物位置

- 工作区总索引：`INDEX.md`
- 全量文档归档：`document_archive/`
- 架构设计产物：`architect_agent/outputs/`
- 对外交付文档：`execution_agent/outputs/docs/`
- 可执行脚手架：`execution_agent/outputs/scripts/`
- 业务方交付包与 demo：`execution_agent/outputs/packages/external-delivery-package/`
