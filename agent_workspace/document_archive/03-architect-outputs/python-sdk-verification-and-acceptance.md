# Python SDK 验证与验收策略

## 1. 文档目的

本文定义 `hydros_agent_sdk` 的验证目标、验证分层、关键验证场景和放行口径，用于支撑 Python SDK 作为 `hydros` 开放接入层时的方案级质量评估。

本文属于 `architect_agent` 的上游验证策略文档，负责回答“应该验证什么、为什么验证、放行看什么”。

本文不直接替代：

- `engineering_agent` 的测试实现与回归记录
- `execution_agent` 的联调执行、自检日志和交付验收留痕

## 2. 验证目标

Python SDK 的验证不应只关注“能否连上 MQTT”，而应回答以下问题：

- 协同协议对象是否能正确解析和序列化
- 初始化、Tick、终止等主链路是否稳定
- 多任务隔离和消息过滤是否正确
- 单 Agent 与多 Agent 运行模式是否都能稳定工作
- 配置加载、日志上下文和错误处理是否足够支撑工程使用
- 后续 DMPC 扩展是否有稳定挂载点

## 3. 验证原则

建议遵循以下原则：

- 先验证协议正确性，再验证业务示例
- 先验证单 Agent，再验证多 Agent
- 先验证本地运行，再验证跨节点协同
- 先验证闭环存在，再验证健壮性和异常治理
- 先验证 SDK 框架行为，再验证具体 Agent 实现

## 4. 验证分层

### 4.1 L0 模型与协议验证

目标：验证协议模型和序列化行为正确。

覆盖范围：

- `SimulationContext`、`HydroAgentInstance` 等对象构造
- `SimCommandEnvelope` 多态反序列化
- `command_type` 分发正确性
- 时序对象 `ObjectTimeSeries`、`TimeSeriesValue` 解析正确性
- 别名字段兼容性

### 4.2 L1 运行时基础设施验证

目标：验证 SDK 基础设施层行为正确。

覆盖范围：

- `AgentStateManager` 的上下文管理和本地/远端判定
- `MessageFilter` 的双重过滤逻辑
- `config_loader` 的环境配置与属性加载
- `AgentConfigLoader` 的 YAML URL 加载和解析
- `logging_config` 的上下文日志格式
- 错误处理包装器

### 4.3 L2 Agent 生命周期验证

目标：验证 Python Agent 生命周期闭环。

覆盖范围：

- `BaseHydroAgent` 的初始化约束
- `load_agent_configuration()` 配置匹配逻辑
- `on_init`、`on_tick`、`on_terminate` 调用顺序
- 响应发送 `send_response()` 行为
- 默认时序更新处理

### 4.4 L3 协同客户端验证

目标：验证 `SimCoordinationClient` 的宿主行为。

覆盖范围：

- MQTT 连接和断连重连
- 消息反序列化
- 消息过滤
- 命令路由
- 队列发送和重试
- 日志上下文注入

### 4.5 L4 多 Agent 运行验证

目标：验证 `MultiAgentCallback` 的单进程多 Agent 宿主能力。

覆盖范围：

- 多工厂注册
- 按 `agent_code` 正确创建多个 Agent
- Tick 广播到多个 Agent
- 定向请求只路由到目标 Agent
- 终止时统一清理上下文 Agent

## 5. 关键验证场景

### 5.1 单 Agent 初始化场景

关注点：

- 接收到 `SimTaskInitRequest`
- 从 `agent_list` 中匹配自身 `agent_code`
- 成功加载远程 YAML 配置
- 注册到 `AgentStateManager`
- 返回 `SimTaskInitResponse`

### 5.2 Tick 步进场景

关注点：

- 接收 `TickCmdRequest`
- 进入 `on_tick` 或 `on_tick_simulation`
- 生成正确响应
- 若有指标输出则可经 MQTT 发出

### 5.3 时序更新场景

关注点：

- 接收 `TimeSeriesDataUpdateRequest`
- 调用默认或重载处理逻辑
- 生成成功响应

### 5.4 多 Agent 单进程场景

关注点：

- 一个初始化请求中包含多个 `agent_code`
- `MultiAgentCallback` 正确创建多个实例
- Tick 被广播到上下文中的多个 Agent
- 定向请求只进入目标 Agent
- 终止时全部实例正确清理

### 5.5 消息过滤场景

关注点：

- 非活跃上下文消息被过滤
- 本地源响应被过滤
- 远端状态报告被接收
- 初始化请求无条件放行

### 5.6 配置双入口场景

关注点：

- `env.properties` 正确加载节点与主题信息
- `agent.properties` 正确加载实例化所需属性
- 远程 YAML 正确加载业务属性
- 缺失配置时有明确错误

## 6. 放行指标

### 6.1 强制指标

以下指标建议作为 SDK 放行的硬约束：

- 协议对象解析正确
- 初始化链路闭环成立
- Tick 响应链路闭环成立
- 消息过滤与路由行为符合设计
- 单进程多 Agent 路由符合设计
- 配置加载路径清晰且失败可诊断
- 错误场景能产生明确异常或错误日志

### 6.2 观察指标

以下指标作为工程观察项，由工程侧和执行侧在具体验证中量化留痕：

- MQTT 连接耗时
- 命令反序列化耗时
- Tick 平均处理耗时
- 出站消息重试次数
- 多 Agent 单进程内广播耗时
- 远程 YAML 拉取耗时

## 7. 验收证据链要求

每轮 SDK 验收建议保留以下证据：

- 测试环境配置快照
- 协议对象样例
- MQTT 主题与消息样例
- 初始化、Tick、终止日志
- 多 Agent 创建和清理日志
- 过滤命中与过滤拒绝日志
- 配置加载结果日志
- 错误场景日志与异常栈

说明：

- 证据留痕由 `engineering_agent` 和 `execution_agent` 在实施与联调过程中补齐
- 本文只规定证据类别，不直接替代测试报告模板

## 8. 当前测试风险

基于当前代码结构，最值得提前防御的风险是：

- 远程 YAML 配置链路对网络与编码处理敏感
- 本地/远端 agent 判定逻辑容易在多节点联调时产生歧义
- `MultiAgentCallback` 的 `managed_top_objects` 当前较弱，不足以支撑复杂对象归属建模
- 一进程多 Agent 广播逻辑如果业务实现过重，可能拖慢 Tick 处理链路
- Python 版 `CentralSchedulingAgent` 当前偏抽象宿主，不能误认为已具备完整中央调度能力

## 9. 角色分工

在验证与验收环节，职责划分如下：

- `architect_agent`：定义验证分层、关键场景、放行口径和风险项
- `engineering_agent`：实现测试、回归验证、最小样例和实现摘要
- `execution_agent`：组织联调、自检、交付验收材料和运行留痕

## 10. 结论

Python SDK 的验收重点不在于“算法能力”，而在于：

- 是否能稳定承接 `hydros` 协同协议
- 是否能稳定托管 Python Agent 生命周期
- 是否能在多任务、多 Agent 场景下保持隔离与路由正确
- 是否具备后续 DMPC 局部控制器接入的稳定底座

只要这四点成立，Python SDK 就可作为 `hydros` 开放接入体系中的可靠运行时基座。
