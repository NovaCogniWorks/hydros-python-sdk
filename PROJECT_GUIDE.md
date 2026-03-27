# Hydros Agent SDK 项目理解指南

## 📋 项目概述

**Hydros Agent SDK** 是一个用于构建水力仿真代理的 Python SDK，提供了 MQTT 协调、协议实现和状态管理功能，与 Java 的 Hydros 协调器协议完全兼容。

### 核心用途
- 构建分布式水力仿真代理
- 通过 MQTT 进行代理间协调
- 支持多任务并发仿真
- 提供数字孪生、本体仿真、模型计算等高级功能

---

## 🏗️ 架构设计

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     Hydros Agent SDK                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   MQTT Client   │    │   协议层     │    │   状态管理   │      │
│  │  (mqtt.py)      │    │ (protocol/)   │    │(state_manager)│      │
│  └────────┬────────┘    └──────┬───────┘    └──────┬───────┘      │
│           │                     │                     │             │
│           ▼                     ▼                     ▼             │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │              SimCoordinationClient (协调客户端)              │ │
│  │  - MQTT 连接管理                                             │ │
│  │  - 消息解析与序列化                                         │ │
│  │  - 消息过滤 (active context, local/remote)                  │ │
│  │  - 自动消息路由到回调                                       │ │
│  │  - 出站消息队列 + 重试逻辑                                  │ │
│  └───────────────────────┬────────────────────────────────────┘ │
│                          │                                          │
│                          ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │         SimCoordinationCallback (回调接口)                 │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │  on_sim_task_init()     初始化任务                      │   │ │
│  │  │  on_tick()               执行仿真步                      │   │ │
│  │  │  on_task_terminate()    终止任务                      │   │ │
│  │  │  on_time_series_data_update()  边界条件更新              │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                          │                                          │
│                          ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                  BaseHydroAgent (代理基类)                  │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │  生命周期:                                            │   │ │
│  │  │    - on_init()      初始化                            │   │ │
│  │  │    - on_tick()      执行仿真                          │   │ │
│  │  │    - on_terminate() 终止                            │   │ │
│  │  │                                                      │   │ │
│  │  │  功能:                                                │   │ │
│  │  │    - load_agent_configuration()  加载配置                │   │ │
│  │  │    - get_time_series_value()      获取时序数据          │   │ │
│  │  │    - send_response()               发送响应              │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  └───────────────────────────────┬────────────────────────────┘ │
│                                    │                                 │
│                                    ▼                                 │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                     专用代理类型                             │ │
│  │  ┌──────────────┐ ┌───────────────┐ ┌────────────────┐    │ │
│  │  │ TickableAgent│ │   TwinsAgent   │ │  OntologyAgent  │    │ │
│  │  │   (步进驱动)  │ │  (数字孪生)   │ │   (本体仿真)    │    │ │
│  │  └──────────────┘ └───────────────┘ └────────────────┘    │ │
│  │                                                               │ │
│  │  ┌──────────────┐ ┌────────────────────────┐ ┌──────────────┐ │ │
│  │  │ModelCalcAgent│ │ CentralSchedulingAgent │ │   更多...    │ │ │
│  │  │ (模型计算)   │ │   (中央调度)        │ │              │ │ │
│  │  └──────────────┘ └────────────────────────┘ └──────────────┘ │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
└───────────────────────────────────────────────────────────────────┘
```

---

## 📁 目录结构说明

```
hydros_agent_sdk/
├── __init__.py                 # 公共 API 导出
├── base_agent.py               # BaseHydroAgent 抽象基类
├── coordination_client.py      # 协调客户端 (核心)
├── coordination_callback.py    # 协调回调接口
├── state_manager.py             # 状态管理器
├── message_filter.py            # 消息过滤器
├── mqtt.py                      # MQTT 底层客户端
│
├── protocol/                    # 协议定义
│   ├── base.py                  # HydroBaseModel
│   ├── models.py                # 核心数据模型
│   ├── commands.py              # 命令/响应定义
│   └── events.py                # 事件定义
│
├── agents/                      # 专用代理实现
│   ├── tickable_agent.py        # 步进驱动代理基类
│   ├── twins_simulation_agent.py # 数字孪生代理
│   ├── ontology_simulation_agent.py # 本体仿真代理
│   ├── model_calculation_agent.py    # 模型计算代理
│   └── central_scheduling_agent.py  # 中央调度代理
│
├── utils/                       # 工具类
│   ├── hydro_object_utils.py   # 水网拓扑工具
│   ├── mqtt_metrics.py          # MQTT 指标工具
│   └── yaml_loader.py           # YAML 配置加载器
│
├── error_handling.py            # 错误处理机制
├── error_codes.py               # 错误码定义
├── logging_config.py            # 日志配置
│
├── config_loader.py             # 配置文件加载
├── agent_properties.py          # 代理属性
├── agent_config.py              # 代理配置加载
├── factory.py                   # 代理工厂
└── multi_agent.py               # 多代理支持
```

---

## 🔄 核心工作流程

### 1. 消息处理流程

```
MQTT Broker
    │
    │ JSON 消息
    ▼
┌─────────────────────────────────┐
│  SimCoordinationClient          │
│  ┌───────────────────────────┐  │
│  │ _on_message()              │  │
│  │  ├─> 解析 JSON            │  │
│  │  ├─> 创建 SimCommandEnvelope  │  │
│  │  ├─> 消息过滤              │  │
│  │  │   ├─ should_process?   │  │
│  │  │   └─ 检查 active context │  │
│  │  └─> 路由到 handler        │  │
│  └───────────────────────────┘  │
│                                 │
│  ┌───────────────────────────┐  │
│  │ _handle_incoming_message() │  │
│  │  ├─> 设置日志上下文        │  │
│  │  └─> 调用 handler          │  │
│  └───────────────────────────┘  │
│                                 │
│                                 ▼
│  ┌───────────────────────────┐  │
│  │ SimCoordinationCallback   │  │
│  │  (用户实现)                 │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

### 2. 任务生命周期

```
┌───────────────────────────────────────────────────────────────┐
│                         任务生命周期                              │
├───────────────────────────────────────────────────────────────┤
│                                                                   │
│  INITIALIZING                                                    │
│      │                                                            │
│      │  ┌─────────────────────────────────────────────────────┐  │
│      │  │ SimTaskInitRequest 收到                               │  │
│      │  │ - 加载代理配置                                       │  │
│      │  │ - 创建代理实例                                       │  │
│      │  │ - 初始化拓扑                                         │  │
│      │  │  - 调用 on_init()                                    │  │
│      │  └─────────────────────────────────────────────────────┘  │
│      │                                                            │
│      ▼                                                            │
│                                                                   │
│  ACTIVE                                                            │
│      │                                                            │
│      │  ┌─────────────────────────────────────────────────────┐  │
│      │  │ TickCmdRequest 收到 (每个仿真步)                       │  │
│      │  │ - 更新边界条件                                       │  │
│      │  │ - 执行仿真计算                                       │  │
│      │  │ - 生成指标                                           │  │
│      │  │  - 调用 on_tick()                                     │  │
│      │  └─────────────────────────────────────────────────────┘  │
│      │                                                            │
│      ▼                                                            │
│                                                                   │
│  TERMINATING                                                     │
│      │                                                            │
│      │  ┌─────────────────────────────────────────────────────┐  │
│      │  │ SimTaskTerminateRequest 收到                          │  │
│      │  │ - 调用 on_terminate()                                │  │
│      │  │ - 清理资源                                           │  │
│      │  │  - 发送终止响应                                       │  │
│      │  └─────────────────────────────────────────────────────┘  │
│      │                                                            │
│      ▼                                                            │
│                                                                   │
│  TERMINATED                                                      │
│      └─ 清理状态记录                                              │
│                                                                   │
└───────────────────────────────────────────────────────────────┘
```

### 3. 多任务并发机制

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentStateManager                          │
├─────────────────────────────────────────────────────────────┤
│                                                                   │
│  任务隔离:                                                         │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Task A: biz_scene_instance_id = "TASK123"            │    │
│  │   - context_id → TaskState                         │    │
│  │   - agents: [agent001, agent002]                    │    │
│  │   - active_contexts.add("TASK123")                  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Task B: biz_scene_instance_id = "TASK456"            │    │
│  │   - context_id → TaskState                         │    │
│  │   - agents: [agent001, agent003]                    │    │
│  │   - active_contexts.add("TASK456")                  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                                   │
│  代理实例管理:                                                      │
│  _agent_instances: {agent_id → HydroAgentInstance}              │
│  _local_agent_instances: {agent_id, ...}                      │
│                                                                   │
│  线程安全:                                                         │
│  - 所有公共方法使用 threading.RLock()                          │
│  - 支持多线程并发访问                                           │
│                                                                   │
└───────────────────────────────────────────────────────────────┘
```

---

## 🔑 关键概念

### 1. SimulationContext (仿真上下文)
- **作用**: 标识一个独立的仿真任务
- **关键字段**: `biz_scene_instance_id` (业务场景实例ID)
- **用途**:
  - 区分不同的仿真任务
  - 实现多任务并发隔离
  - 每个任务有独立的代理实例

### 2. HydroAgent vs HydroAgentInstance
- **HydroAgent**: 代理的定义 (静态配置)
  - `agent_code`: 代理代码
  - `agent_type`: 代理类型
  - `agent_name`: 代理名称

- **HydroAgentInstance**: 代理的运行实例 (动态状态)
  - `agent_id`: 实例ID
  - `hydros_node_id`: 运行节点
  - `agent_biz_status`: 业务状态

### 3. Local vs Remote Agents
- **Local Agent**: 运行在当前节点的代理
  - 发送响应和报告
  - 处理该节点的计算任务

- **Remote Agent**: 运行在其他节点的代理
  - 接收响应和报告
  - 作为分布式仿真的对等节点

### 4. Message Filtering (消息过滤)
两个过滤维度:

**a) Active Context Filter**
```python
# 接受条件:
1. SimTaskInitRequest - 总是接受
2. 命令的 context 在 active_contexts 中
```

**b) Receive Filter**
```python
# 接收条件:
1. SimCoordinationRequest - 总是接收
2. AgentInstanceStatusReport - 来自 remote agent
3. SimTaskInitResponse - 来自 remote agent
```

---

## 🛠️ 开发指南

### 创建自定义代理

```python
from hydros_agent_sdk import TwinsSimulationAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest, SimTaskInitResponse,
    TickCmdRequest, SimTaskTerminateResponse, SimTaskTerminateResponse,
)
from hydros_agent_sdk.utils.mqtt_metrics import create_mock_metrics

class MyCustomAgent(TwinsSimulationAgent):
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """1. 加载配置"""
        self.load_agent_configuration(request)

        """2. 加载拓扑"""
        from hydros_agent_sdk.utils import HydroObjectUtilsV2
        self._topology = HydroObjectUtilsV2.build_waterway_topology(
            self.properties.get_property('hydros_objects_modeling_url')
        )

        """3. 初始化模型"""
        self._initialize_twins_model()

        """4. 注册状态"""
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        """5. 返回响应"""
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status="SUCCESS",
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={}
        )

    def on_tick_simulation(self, request: TickCmdRequest) -> List[MqttMetrics]:
        """执行仿真步"""
        step = request.step

        # 1. 获取边界条件
        boundary_conditions = self._collect_boundary_conditions(step)

        # 2. 执行仿真计算
        results = self._execute_twins_simulation(step)

        # 3. 转换为指标
        metrics_list = self._convert_results_to_metrics(results)

        return metrics_list

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """清理资源"""
        # 清理状态
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        # 返回响应
        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status="SUCCESS",
            source_agent_instance=self,
        )
```

### 错误处理最佳实践

```python
from hydros_agent_sdk import ErrorCodes, handle_agent_errors, AgentErrorContext

class MyAgent(TwinsSimulationAgent):

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """自动错误处理"""
        # 任何异常都会被捕获并转换为错误响应
        self.load_agent_configuration(request)

        # 使用 AgentErrorContext 处理特定代码块
        with AgentErrorContext(ErrorCodes.TOPOLOGY_LOAD_FAILURE, "MyAgent") as ctx:
            self._topology = HydroObjectUtilsUtilsV2.build_waterway_topology(url)

        if ctx.has_error:
            logger.error(f"Topology loading failed: {ctx.error_message}")
            # 创建错误响应
            return self._create_error_response(request, ctx.error_message)

        return self._create_success_response(request)
```

---

## 📊 性能特性

### 已实施的优化

| 优化项 | 描述 | 性能提升 |
|--------|------|----------|
| 类型检查缓存 | 使用 `__class__ 替代 isinstance()` | ~40% |
| 上下文缓存 | 缓存活跃/非活跃上下文 | ~60% |
| 移除 assert | 生产环境禁用类型检查 | ~15% |
| 日志上下文缓存 | 缓存 cluster_id 和 node_id | ~30% |
| 指数退避+抖动 | 避免惊群效应 | 更稳定 |
| 错误分类 | 不可恢复错误立即失败 | 更高效 |

### 监控指标

```python
# 获取指标
metrics = client.get_metrics()

print(f"接收消息总数: {metrics['messages_received']}")
print(f"发送消息总数: {metrics['messages_sent_TickCmdRequest']}")
print(f"重试次数: {metrics['messages_sent_retry']}")
print(f"过滤消息数: {metrics['messages_filtered']}")
print(f"解析错误: {metrics['messages_parse_error']}")
```

---

## 🚀 快速开始

### 1. 基本设置

```python
from hydros_agent_sdk import SimCoordinationClient, HydroAgentFactory
from hydros_agent_sdk.protocol.commands import SimTaskInitRequest
from hydros_agent_sdk.protocol.models import SimulationContext

# 1. 创建协调客户端
client = SimCoordinationClient(
    broker_url="192.168.1.24",
    broker_port=1883,
    topic="/hydros/commands/coordination/my_cluster",
    sim_coordination_callback=my_callback,
    qos=1
)

# 2. 启动客户端
client.start()

# 3. 保持运行
import time
while True:
    time.sleep(1)
```

### 2. 运行多代理

```bash
# 设置
cd examples

# 启动多个代理
cd twins
python twins_agent.py

cd ../ontology
python ontology_agent.py

cd ../central_scheduling
python central_scheduling_agent.py
```

---

## 🔍 调试技巧

### 查看日志

日志格式 (结构化):
```
CLUSTER|NODE|TIME|LEVEL|BIZ_SCENE_ID|AGENT_ID|SOURCE|MESSAGE
```

示例:
```
default_cluster|node1|2026-03-02 14:30:45|INFO |TASK123|AGENT_001|twins_agent.py:123|Initializing...
```

### 查看指标

```python
# 在代码中
metrics = client.get_metrics()
for key, value in metrics.items():
    print(f"{key}: {value}")
```

### 常见问题排查

**问题**: 消息被过滤
```python
# 检查活跃上下文
context_id = "TASK123"
is_active = state_manager.has_active_context(context)

# 检查过滤原因
command = # 你的命令对象
from hydros_agent_sdk.message_filter import MessageFilter
filter_result = MessageFilter(state_manager).should_process_message(command)
```

---

## 📚 相关文档

- **错误处理指南**: [docs/ERROR_HANDLING_SUMMARY.md](hydros_agent_sdk/docs/ERROR_HANDLING_SUMMARY.md)
- **完整错误处理**: [docs/ERROR_HANDLING.md](hydros_agent_sdk/docs/ERROR_HANDLING.md)
- **代理示例**: [examples/agents/](hydros_agent_sdk/examples/agents/)
- **协议定义**: [hydros_agent_sdk/protocol/](hydros_agent_sdk/protocol/)
- **Java 协议参考**: 对应 Java 包 `com.hydros.protocol`

---

## 🎯 总结

**核心概念**:
1. **MQTT 协调**: 所有代理通过 MQTT 交换消息
2. **多任务并发**: 每个任务有独立的上下文和代理实例
3. **消息过滤**: 只处理相关消息，避免处理无关数据
4. **线程安全**: State Manager 使用锁保证并发安全

**开发要点**:
1. 继承 `BaseHydroAgent` 或其子类
2. 实现三个核心方法: `get_component()`, `on_init()`, `on_tick()`
3. 使用 `@handle_agent_errors` 装饰器自动处理错误
4. 通过 `self.state_manager` 管理任务状态
5. 使用 `self.properties.get_property()` 获取配置

**优化特性**:
1. 类型检查缓存提升性能
2. 上下文缓存减少查询
3. 监控指标便于运维
4. 指数退避+抖动提高可靠性
