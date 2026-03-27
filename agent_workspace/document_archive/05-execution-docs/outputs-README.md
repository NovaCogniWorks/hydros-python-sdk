# Execution Outputs

本目录为执行智能体的正式输出目录，已按交付类型整理为以下结构：

- `docs/`
  正式说明文档、改造方案、集成指南
- `scripts/`
  可直接执行的脚手架或辅助脚本
- `packages/`
  面向业务方的完整交付包、demo 工程、样例配置

## 当前产物清单

### docs

- `docs/python-sdk-refactor-plan.md`
- `docs/python-sdk-external-integration-guide.md`

### scripts

- `scripts/generate-hydros-agent-project.ps1`

### packages

- `packages/external-delivery-package/`

## 说明

- `packages/external-delivery-package/` 内包含对外交付包、样例命令、两个 demo 工程与一键启动脚本
- 本目录中的文档、脚本和包，属于执行化、交付化产物；其中涉及的架构边界与实现口径分别以上游 `architect_agent/outputs` 和 `engineering_agent` 实现结果为准
- 若后续新增执行结果，优先按类型放入对应子目录，不再直接散落在根目录
