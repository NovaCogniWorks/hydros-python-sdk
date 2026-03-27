# Python 高级工程师实施入口

## 1. 文档目的

本文是 `engineering_agent` 的实施入口文档。

本文只负责：

- 告诉工程师先看什么
- 告诉工程师本轮输出写到哪里
- 告诉工程师遇到什么情况应暂停并回流

## 2. 实施前阅读顺序

进入实现前，请按以下顺序阅读：

1. `engineering_agent/AGENTS.md`
2. `engineering_agent/inputs/python-sdk-architecture-implementation-handoff.md`
3. `engineering_agent/inputs/python-sdk-phase1-task-breakdown.md`
4. `architect_agent/outputs/python-sdk-architecture-design.md`
5. `architect_agent/outputs/python-sdk-domain-model.md`
6. `architect_agent/outputs/python-sdk-dmpc-evolution-plan.md`
7. `architect_agent/outputs/python-sdk-verification-and-acceptance.md`

## 3. 本轮实施主线

当前默认主线是：

- 不重复做架构定位争论
- 优先做第一阶段主骨架治理
- 每次变更都带最小验证
- 工程侧补齐实现素材，不越权接管最终交付编排

## 4. 输出去向

建议按以下路径输出：

- 代码改动：`hydros_agent_sdk/`
- 工程摘要：`engineering_agent/outputs/`
- 需交付侧整理的文档、脚本和样例素材：`execution_agent/outputs/`

## 5. 完成后至少说明的内容

每次实现完成后，至少说明：

- 改了哪些文件
- 对应哪一个任务项
- 跑了什么验证
- 哪些内容未验证
- 是否影响已有 API、样例或交付路径

## 6. 遇到以下情况应暂停

以下情况应暂停并回流架构侧：

- 发现文档口径冲突
- 发现需要新增新的基础领域对象但架构未定义
- 发现现有代码与设计边界完全不兼容
- 发现要破坏现有 API 才能继续推进

以下情况应同步执行侧：

- 需要新增或调整对外交付目录
- 需要生成新的 demo、脚手架或交付说明
- 需要校对集成指南、启动清单或发布结构

## 7. 结论

你当前的职责是高级 Python 工程实现，不是重新定义系统。

请直接以“实现 + 验证 + 交付素材补齐”为工作主线推进。
