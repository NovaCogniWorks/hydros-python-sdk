# 01 外部集成 README

## 1. 集成目标

外部团队接入 Hydros Python SDK 的目标，应限定为：

- 复用 SDK 现有的协议、MQTT 通信与 Agent 生命周期框架
- 在独立业务项目中实现本团队自己的 Agent 行为与业务引擎
- 与中央智能体按统一命令协议协同运行

不建议把外部业务代码直接改进 SDK 包内部。

## 2. 最小技术方案

建议采用以下最小方案：

- 一个独立 Python 项目
- 一个 Agent 实现类
- 一个业务引擎类
- 一套 `env.properties`
- 一套 `agent.properties`
- 一个启动入口 `launcher.py`

## 3. 标准启动链路

标准启动链路如下：

1. 启动 `launcher.py`
2. 读取 `env.properties`
3. 读取 `agent.properties`
4. 通过 `HydroAgentFactory` 注册 Agent 工厂
5. 通过 `MultiAgentCallback` 建立命令路由
6. 通过 `SimCoordinationClient` 连接 MQTT
7. 等待中央侧下发初始化、Tick、终止或事件命令

## 4. 外部项目边界

SDK 层负责：

- MQTT 接入
- 指令反序列化
- 生命周期路由
- Agent 实例工厂化创建
- 多 Agent 宿主回调

业务项目负责：

- Agent 子类实现
- 规则、优化、求解、预测等业务逻辑
- 参数与模型配置
- 业务结果解释与本地验证

说明：

- 架构边界与对象模型以上游架构文档为准
- 本 README 只保留对外集成所需的最小执行口径

## 5. 接入建议

- 新项目优先使用脚手架生成，不建议手工从零搭目录
- 首次联调优先使用 `TwinsSimulationAgent` 或 `OntologySimulationAgent` 这类链路更直观的模板
- 事件驱动 Agent 在联调前要先确认中央侧是否会发送对应事件类命令
