# Python SDK 分层设计指南

本参考文档用于指导 `hydros` Python SDK 的分层、抽象边界和扩展策略。

## 适用场景

当用户需要以下内容时，读取本文件：
- 设计或重构 Python SDK
- 讨论基类、工厂、配置、协议模型、工具层如何分层
- 判断某段逻辑应放在 Agent 内还是 SDK 内
- 设计可扩展、可复用的 Agent 开发模型

## 推荐分层

### 1. Protocol Layer

职责：
- 定义命令模型、事件模型、响应模型
- 定义序列化/反序列化规范
- 维护版本兼容策略

不应承担：
- 业务决策
- 路由策略
- Agent 专属逻辑

### 2. Runtime Coordination Layer

职责：
- 负责消息发送、接收、订阅、回调派发
- 管理连接、重试、心跳、超时
- 维护与 Broker 或中间件的连接语义

典型对象：
- `SimCoordinationClient`
- `MultiAgentCallback`

### 3. Agent Lifecycle Layer

职责：
- 定义 Agent 生命周期
- 约束初始化、启动、接收命令、关闭等阶段
- 管理 Agent 与运行时的接入方式

典型对象：
- `BaseHydroAgent`
- `TwinsSimulationAgent`

### 4. Factory And Bootstrap Layer

职责：
- 负责配置装配
- 实例化 Agent
- 绑定环境配置、日志、依赖和运行时

典型对象：
- `HydroAgentFactory`

### 5. Utilities Layer

职责：
- 配置加载
- 日志初始化
- 指标采集
- 通用转换工具
- 与业务无关的通用辅助函数

## 落点判断原则

当一段代码需要放置时，使用以下判断：

- 如果它定义消息结构，应放在 Protocol Layer
- 如果它负责 Broker 交互和消息派发，应放在 Runtime Coordination Layer
- 如果它定义 Agent 的生命周期契约，应放在 Agent Lifecycle Layer
- 如果它负责实例装配和配置绑定，应放在 Factory And Bootstrap Layer
- 如果它只是无状态通用能力，应放在 Utilities Layer

## 何时不应放入 SDK

以下逻辑通常不应进入 SDK：
- 单一项目专用的业务规则
- 特定 Agent 独有的目录兼容逻辑
- 只服务于某个具体行业场景的字段映射
- 临时排障代码
- 无法在第二个 Agent 中自然复用的逻辑

## 好的 SDK 信号

- 新增 Agent 时，开发者只需实现少量明确的生命周期方法
- 配置加载过程可预测
- 错误信息集中且可读
- 不同 Agent 共享同一套运行时接入语义
- 协议模型清晰，版本演进可控

## 差的 SDK 信号

- 新增 Agent 必须复制粘贴大量样板代码
- 基类过深、调用链不透明
- Factory 同时负责业务决策
- 回调层夹杂业务判断
- SDK 工具层依赖具体项目目录结构
