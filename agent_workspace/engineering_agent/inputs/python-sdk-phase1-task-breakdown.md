# Python SDK 第一阶段任务单

## 1. 文档目的

本清单用于指导 `engineering_agent` 执行 Python SDK 第一阶段改造。

本文只负责三类内容：

- 第一阶段任务顺序
- 每项任务的实施范围
- 每项任务的最低验收口径

架构边界、理论依据和总体定位不在本文重复展开，统一以上游交接说明和 `architect_agent/outputs/` 为准。

## 2. 第一阶段目标

第一阶段目标是：

- 先完成运行时主骨架治理
- 保持外部 API 基本稳定
- 为后续 DMPC 对象层和上层抽象腾出位置

## 3. 实施顺序

建议严格按以下顺序推进：

1. 拆分 `SimCoordinationClient`
2. 冻结 `BaseHydroAgent`
3. 拆分协议对象与命令模块
4. 增强 `MultiAgentCallback`
5. 统一配置体系

## 4. 任务清单

### T1. 拆分 `SimCoordinationClient`

涉及模块：

- `hydros_agent_sdk/coordination_client.py`

建议拆分方向：

- 连接管理组件
- 命令路由组件
- 日志上下文绑定组件
- 出站发送与重试组件

最低验收：

- `SimCoordinationClient` 对外构造和调用方式不变
- 连接、路由、日志、发送职责不再全部堆在单类中
- 基础导入和最小语法验证通过

### T2. 冻结 `BaseHydroAgent`

涉及模块：

- `hydros_agent_sdk/base_agent.py`
- `hydros_agent_sdk/agents/`

建议动作：

- 明确 `BaseHydroAgent` 为通用基类
- 不再往里继续叠加控制区、边界量、局部求解等语义
- 准备新增更上层抽象，例如：
  - `BoundaryAwareAgent`
  - `LocalDmpcAgent`

最低验收：

- 文档口径和代码注释明确其边界
- 工程实现中不再把新业务状态塞入基类

### T3. 拆分协议对象和命令模块

涉及模块：

- `hydros_agent_sdk/protocol/models.py`
- `hydros_agent_sdk/protocol/commands.py`

建议动作：

- 为未来对象拆分准备独立模块
- 第一阶段可以先建立新文件并保留统一导出层
- 不要求一次性迁完所有对象

建议预留文件：

- `protocol/core_models.py`
- `protocol/core_commands.py`
- `protocol/dmpc_models.py`
- `protocol/dmpc_commands.py`

最低验收：

- 不破坏现有导入路径
- 新增模块结构清晰

### T4. 增强 `MultiAgentCallback`

涉及模块：

- `hydros_agent_sdk/multi_agent.py`

建议动作：

- 保持当前“多实例宿主”定位
- 逐步加入上下文内路由增强能力
- 为后续 `context -> zone -> agent` 映射预留位置

最低验收：

- 当前多 Agent 初始化和广播逻辑保持可用
- 新增强能力不改变现有主链路

### T5. 统一配置体系

涉及模块：

- `hydros_agent_sdk/config_loader.py`
- `hydros_agent_sdk/agent_config.py`
- `hydros_agent_sdk/factory.py`

建议动作：

- 文档与代码同时明确三类配置职责：
  - `env.properties`
  - `agent.properties`
  - 远程 YAML
- 不增加新的散乱入口

最低验收：

- 配置职责边界清晰
- 新 demo 和脚手架中的配置说明与代码行为一致

## 5. 第一阶段交付物

第一阶段结束后，工程侧至少应交付：

- 运行时代码重构结果
- 更新后的最小说明文档
- 至少一个通过验证的脚手架或 demo 样板素材
- 一份实现摘要

## 6. 禁区清单

第一阶段不要做以下事情：

- 不要提前大规模引入 DMPC 全量对象
- 不要把控制区语义直接塞进 `BaseHydroAgent`
- 不要把 `MultiAgentCallback` 直接改成业务编排器
- 不要在未统一配置职责前继续增加配置入口
- 不要破坏现有对外交付目录结构

## 7. 最低验证清单

每完成一个任务，至少补以下检查：

- 语法或导入验证通过
- 关键路径未断
- 现有 demo/脚手架未被破坏
- 输出说明已同步更新

## 8. 协作约定

- 架构边界问题回流 `architect_agent`
- 代码实现问题留在 `engineering_agent`
- 脚手架、demo 和交付落盘交给 `execution_agent`

## 9. 结论

第一阶段不是为了“一次性做完所有 DMPC 能力”，而是为了把 Python SDK 主骨架从可用状态提升到可持续演进状态。
