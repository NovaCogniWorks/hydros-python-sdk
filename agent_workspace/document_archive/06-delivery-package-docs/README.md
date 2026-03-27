# Hydros Python SDK 对外交付包

## 1. 交付包说明

本目录面向外部集成方，提供一套可以直接用于项目接入、环境配置、联调验证和启动排障的标准材料。

适用对象：

- 新接入 Hydros Python SDK 的业务团队
- 需要快速生成 Agent 项目并完成中央侧联调的开发团队
- 需要形成统一实施手册的交付团队

## 2. 目录内容

- `README.md`
  当前总览文档
- `01-external-integration-readme.md`
  面向业务方的集成总说明
- `02-configuration-templates.md`
  配置文件模板与字段说明
- `03-startup-checklist.md`
  启动前、启动中、启动后的检查清单
- `04-joint-debug-command-examples.md`
  与中央智能体联调的协议命令样例
- `05-delivery-acceptance-checklist.md`
  交付验收清单
- `samples\env.properties`
  环境配置样例
- `samples\agent.properties`
  Agent 身份配置样例
- `samples\task_init_request.json`
  初始化命令样例
- `samples\tick_cmd_request.json`
  Tick 命令样例
- `samples\task_terminate_request.json`
  终止命令样例
- `samples\time_series_calculation_request.json`
  事件驱动计算命令样例
- `samples\outflow_time_series_request.json`
  外发流量时序命令样例

## 3. 推荐使用方式

建议按以下顺序使用本交付包：

1. 先阅读 `01-external-integration-readme.md`
2. 再按 `02-configuration-templates.md` 准备配置文件
3. 通过脚手架生成项目骨架
4. 按 `03-startup-checklist.md` 做启动验证
5. 用 `04-joint-debug-command-examples.md` 与中央侧联调
6. 最后用 `05-delivery-acceptance-checklist.md` 做正式验收

## 4. 与已有交付物关系

本交付包是在以下两份已有成果之上的对外交付增强层：

- [python-sdk-external-integration-guide.md](agent_workspace/execution_agent/outputs/docs/python-sdk-external-integration-guide.md)
- [generate-hydros-agent-project.ps1](agent_workspace/execution_agent/outputs/scripts/generate-hydros-agent-project.ps1)

前者负责总体集成说明，后者负责一键生成项目。本目录则补足实施交付、联调和验收所需的标准化材料。

## 5. 角色边界说明

本交付包属于执行侧整理后的对外交付材料：

- 架构边界、对象模型和演进路线以上游 `architect_agent/outputs/` 为准
- 代码实现与兼容性行为以 `engineering_agent` 的实现结果为准
- 本目录负责把这些既有结论组织成可直接使用的外部材料

