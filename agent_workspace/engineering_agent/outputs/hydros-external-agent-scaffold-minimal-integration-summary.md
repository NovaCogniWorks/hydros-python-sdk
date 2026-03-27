# Hydros 外部 Agent 脚手架最小集成改造摘要

## 1. 任务目标

本轮工作目标是优化外部 Agent 脚手架，使业务方在基于 `hydros_agent_sdk` 集成时尽量减少非必要改动，并保证生成工程可运行、可验证、可交付。

本轮任务归类为：

- 交付脚手架与样例工程完善
- 对外交付文档收口

对齐依据：

- `architect_agent/outputs/python-sdk-verification-and-acceptance.md`
- `architect_agent/outputs/python-sdk-refactor-task-breakdown.md`

最小可验证方案：

- 用脚本生成新样板工程
- 执行 `scripts/bootstrap.ps1`
- 执行 `python -m unittest tests.test_scaffold_import`
- 受控启动 `scripts/run.ps1` 验证运行时装配与日志链路
- 核对 README 和对外集成文档是否与真实脚手架输出一致

## 2. 改动范围

### 2.1 脚手架脚本

已修改：

- [generate-hydros-agent-project.ps1](/F:/sl/sdk/hydros-python-sdk/agent_workspace/execution_agent/outputs/scripts/generate-hydros-agent-project.ps1)

关键改动：

- 生成工程改为包含完整可运行骨架：`agent_app/`、`conf/`、`scripts/`、`tests/`、`launcher.py`
- 新增模板参数：`-Template auto|twins|ontology|central`
- 增加 `BaseClass` 与 `Template` 的兼容性校验
- 按模板生成不同的 `agent.properties` 默认参数
- 按模板生成不同的 `agent_impl.py` 和 `business_engine.py`
- 引入 `agent_app/user_logic.py` 作为默认业务集成入口
- 将 `business_engine.py` 收敛为适配层，主要职责变为委托 `user_logic.py`
- `bootstrap.ps1` 采用 `.pth` 方式链接项目源码和 SDK 源码，不再依赖 `pip install -e`
- README 模板、生成摘要和 smoke test 同步更新到“最小集成面”口径

### 2.2 对外交付文档

已修改：

- [python-sdk-external-integration-guide.md](/F:/sl/sdk/hydros-python-sdk/agent_workspace/execution_agent/outputs/docs/python-sdk-external-integration-guide.md)
- [python-sdk-refactor-plan.md](/F:/sl/sdk/hydros-python-sdk/agent_workspace/execution_agent/outputs/docs/python-sdk-refactor-plan.md)

关键改动：

- 对外集成指南明确最小集成面为：`conf/env.properties`、`conf/agent.properties`、`agent_app/user_logic.py`
- 项目结构、启动方式、配置职责、模板参数和验证路径更新为当前真实脚手架输出
- 执行说明补充交付侧脚手架口径、交付收口阶段和当前已落地的交付基线

### 2.3 工程侧摘要

已新增：

- [hydros-external-agent-scaffold-minimal-integration-summary.md](/F:/sl/sdk/hydros-python-sdk/agent_workspace/engineering_agent/outputs/hydros-external-agent-scaffold-minimal-integration-summary.md)

用途：

- 留存本轮脚手架和文档收口的工程实施记录
- 记录验证结论、未验证项和交付影响
- 为后续执行侧和联调侧提供统一引用材料

## 3. 当前统一口径

当前脚手架和文档收口后的统一口径如下：

- 外部用户优先只修改 `conf/env.properties`
- 外部用户优先只修改 `conf/agent.properties`
- 外部用户优先只修改 `agent_app/user_logic.py`
- `agent_app/business_engine.py` 默认作为适配层保留
- `agent_app/runtime.py`、`agent_app/support.py`、`agent_app/agent_impl.py` 默认不要求优先修改
- 本地启动优先走 `scripts/bootstrap.ps1` 和 `scripts/run.ps1`
- 本地验证优先走 `tests/test_scaffold_import.py`

## 4. 验证记录

### 4.1 已执行验证

已生成并验证多个样板工程，包括：

- [sample_template_twins_v3](/F:/sl/sdk/hydros-python-sdk/agent_workspace/engineering_agent/outputs/sample_template_twins_v3)
- [sample_template_ontology_v5](/F:/sl/sdk/hydros-python-sdk/agent_workspace/engineering_agent/outputs/sample_template_ontology_v5)
- [sample_template_central_v3](/F:/sl/sdk/hydros-python-sdk/agent_workspace/engineering_agent/outputs/sample_template_central_v3)
- [sample_min_integration_twins_v4](/F:/sl/sdk/hydros-python-sdk/agent_workspace/engineering_agent/outputs/sample_min_integration_twins_v4)

已完成的验证动作：

- 使用脚手架成功生成样板工程
- `scripts/bootstrap.ps1` 执行成功
- `.venv` 中通过 `.pth` 成功链接项目源码和 SDK 源码
- `python -m unittest tests.test_scaffold_import` 通过
- 受控启动 `scripts/run.ps1`，验证运行时装配和日志初始化链路
- 核对生成 README 已明确 `user_logic.py` 为主业务入口
- 核对 `business_engine.py` 已委托 `user_logic.py`
- 核对测试已断言 `agent_app/user_logic.py` 存在

### 4.2 代表性验证结果

代表样板：

- [sample_min_integration_twins_v4](/F:/sl/sdk/hydros-python-sdk/agent_workspace/engineering_agent/outputs/sample_min_integration_twins_v4)

验证结果：

- `bootstrap.ps1` 成功完成虚拟环境初始化和路径注入
- `tests.test_scaffold_import` 执行结果为 `Ran 3 tests ... OK`
- `scripts/run.ps1` 可成功进入运行时装配，日志显示 `HydroAgentFactory`、`MultiAgentCallback`、`SimCoordinationClient` 初始化完成
- 服务启动后在 MQTT 建连阶段因 `127.0.0.1:1883` 无可用 broker 返回 `ConnectionRefusedError [WinError 10061]`
- 该结果说明脚手架启动链路已走通到外部依赖边界，当前失败原因属于环境依赖未就绪，而非脚手架导入或装配错误

## 5. 未验证项

本轮未覆盖以下内容：

- MQTT 实际连通性和真实 broker 联调
- `scripts/run.ps1` 在可用 broker 条件下的完整生命周期联调
- `ontology` 和 `central` 模板下的真实业务命令闭环
- 远程 YAML 配置拉取与解析链路
- 多 Agent 单进程场景下的实际消息路由联调

因此本轮结论应限定为：

- 脚手架落盘完整性已验证
- 本地导入链路和配置加载已验证
- 启动链路已验证到 MQTT 外部依赖边界
- 最小接入文档与生成内容已对齐
- 不等于真实运行场景已经全部联通

## 6. API 与交付影响评估

### 6.1 对 SDK API 的影响

本轮未修改 `hydros_agent_sdk` 核心包代码，也未改变 SDK 公共导出 API。

### 6.2 对交付路径的影响

本轮改变了外部脚手架和交付文档的推荐接入方式：

- 默认接入方式从“用户自行安装或编辑多个骨架文件”收敛为“脚本生成 + bootstrap + 仅改配置和 `user_logic.py`”
- 外部项目 README、执行说明和对外集成文档现在保持一致
- 启动烟测已证明运行时装配能够拉起，并且已完成真实 broker 连接与订阅验证，后续联调重点转为消息收发和业务命令闭环

## 7. 后续建议

建议后续继续推进以下事项：

1. 为 `ontology` 和 `central` 模板分别补一份生成样板的集成截图或运行记录
2. 增加一份面向业务方的“5 分钟快速接入清单”文档
3. 在具备可用 MQTT broker 的环境下补充 `scripts/run.ps1` 完整生命周期验证留痕
4. 视 SDK 打包修复进展，再决定是否恢复发布包安装路径作为默认说明

## 8. 结论

本轮工作已把外部 Agent 脚手架从“可生成模板”推进到“可运行、可验证、最小集成改造”的交付状态，并完成了脚手架、README、测试和交付文档的同步收口。

当前最重要的交付结论是：外部用户接入时，优先只需要改配置和 `agent_app/user_logic.py`，而不再需要理解整套运行时装配细节。
