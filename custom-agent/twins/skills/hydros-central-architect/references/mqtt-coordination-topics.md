# MQTT 协调链路与 Topic 设计参考

本参考文档用于指导 `hydros` 中多智能体系统的 MQTT 协调链路设计、Topic 规划和可观测性增强。

## 适用场景

当用户需要以下内容时，读取本文件：
- 设计 Agent 之间的 MQTT 协调链路
- 评审 Topic 设计是否合理
- 分析消息追踪、重复投递、乱序到达问题
- 设计调试和运维可观测性方案

## Topic 设计目标

好的 Topic 设计应支持以下目标：
- 清晰表达消息意图
- 支持按角色或业务域路由
- 便于运维筛查日志和消息
- 支持多环境、多节点、多集群部署
- 降低误订阅和消息语义混淆风险

## 推荐 Topic 维度

在 `hydros` 中，Topic 设计通常至少考虑以下维度：
- 集群标识
- 节点标识
- 业务域
- 消息类型
- 来源 Agent
- 目标 Agent 或广播范围

示例思路：
- `/hydros/commands/coordination/{node_id}`
- `/hydros/events/agents/{agent_code}`
- `/hydros/telemetry/{cluster_id}/{agent_code}`

## 推荐消息元数据

除 Topic 之外，消息负载或消息头中建议包含：
- correlation_id
- command_id
- source_agent_code
- target_agent_code
- payload_version
- timestamp
- request_type
- retry_count

## 常见风险

### 1. Topic 语义过宽

问题：
- 多类消息混在同一 Topic
- 订阅方需要自己猜测消息类型

后果：
- 处理器复杂
- 容易误消费
- 排障成本高

### 2. Topic 语义过细

问题：
- Topic 粒度过碎
- 新增一个流程就新增大量 Topic

后果：
- 配置难维护
- 订阅关系复杂
- 扩展时容易失控

### 3. 缺少链路追踪字段

问题：
- 只能看到 Topic，无法关联具体业务请求

后果：
- 难以排查一次请求在多个 Agent 之间的传播路径

## 设计建议

- Topic 负责粗粒度路由，消息体负责细粒度语义
- 不要把所有语义都编码到 Topic 名字里
- 保证命令、事件、遥测至少在一级语义上分离
- 保证运维能根据 Topic 和 correlation_id 快速还原链路
- 对广播消息和点对点消息使用不同语义约束

## 运维检查项

- 是否能按 Agent 快速过滤消息
- 是否能按 correlation_id 还原完整执行链路
- 是否能识别重复消息和重试消息
- 是否能区分命令消息、状态消息和遥测消息
- 是否能按 cluster/node 维度隔离环境
