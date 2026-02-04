# 错误处理机制文档

## 概述

Hydros Agent SDK 提供了完整的错误处理机制，用于在 agent 处理各种 Request 时捕获异常并转换为对应的 Response 返回给 coordinator。

## 核心组件

### 1. ErrorCodes - 错误码定义

参照 Java 实现 `com.hydros.common.ErrorCodes`，提供统一的错误码管理。

**位置**: `hydros_agent_sdk/error_codes.py`

**核心类**:
- `ErrorCode`: 单个错误码类，包含 code 和 message_template
- `ErrorCodes`: 错误码定义集合（静态类）

**主要错误码**:

| 错误码 | 说明 | 消息模板 |
|-------|------|---------|
| `SYSTEM_ERROR` | 系统错误 | `Unknown system failure happens, cause: {0}-{1}` |
| `INVALID_PARAMS` | 参数错误 | `Invalid parameters: {0}` |
| `CONFIGURATION_LOAD_FAILURE` | 配置加载失败 | `Configuration load failure: {0}, {1}` |
| `AGENT_INIT_FAILURE` | Agent 初始化失败 | `Agent initialization failed: {0}, detail: {1}` |
| `AGENT_TICK_FAILURE` | Agent tick 执行失败 | `Agent tick execution failed: {0}, detail: {1}` |
| `AGENT_TERMINATE_FAILURE` | Agent 终止失败 | `Agent termination failed: {0}, detail: {1}` |
| `TIME_SERIES_UPDATE_FAILURE` | 时序数据更新失败 | `Time series data update failed: {0}, detail: {1}` |
| `TOPOLOGY_LOAD_FAILURE` | 拓扑加载失败 | `Topology load failure: {0}, detail: {1}` |
| `SIMULATION_EXECUTION_FAILURE` | 仿真执行失败 | `Simulation execution failed: {0}, detail: {1}` |
| `MODEL_INITIALIZATION_FAILURE` | 模型初始化失败 | `Model initialization failed: {0}, detail: {1}` |
| `BOUNDARY_CONDITION_ERROR` | 边界条件错误 | `Boundary condition error: {0}, detail: {1}` |
| `METRICS_GENERATION_FAILURE` | 指标生成失败 | `Metrics generation failed: {0}, detail: {1}` |

**使用示例**:

```python
from hydros_agent_sdk import ErrorCodes

# 格式化错误消息
error_message = ErrorCodes.AGENT_INIT_FAILURE.format_message(
    "MyAgent",
    "Failed to load topology"
)
# 输出: "Agent initialization failed: MyAgent, detail: Failed to load topology"

# 获取错误码
error_code = ErrorCodes.AGENT_INIT_FAILURE.code
# 输出: "AGENT_INIT_FAILURE"
```

### 2. Error Handling - 错误处理工具

**位置**: `hydros_agent_sdk/error_handling.py`

提供多种错误处理方式：

#### 方式 1: `@handle_agent_errors` 装饰器（推荐）

**适用场景**: Agent 生命周期方法（`on_init`, `on_tick`, `on_terminate` 等）

**特点**:
- 自动捕获异常
- 自动转换为对应的 Response
- 自动设置 `command_status=FAILED`
- 自动填充 `error_code` 和 `error_message`
- 自动记录日志（包含 traceback）

**使用示例**:

```python
from hydros_agent_sdk import TwinsSimulationAgent, ErrorCodes, handle_agent_errors
from hydros_agent_sdk.protocol.commands import SimTaskInitRequest, SimTaskInitResponse

class MyAgent(TwinsSimulationAgent):
    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化 agent。

        任何异常都会被自动捕获并转换为 SimTaskInitResponse，
        其中 command_status=FAILED，error_code 和 error_message 已填充。
        """
        # 加载配置（可能抛出异常）
        self.load_agent_configuration(request)

        # 加载拓扑（可能抛出异常）
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        self._topology = HydroObjectUtilsV2.build_waterway_topology(topology_url)

        # 初始化模型（可能抛出异常）
        self._initialize_twins_model()

        # 返回成功响应
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={}
        )
```

**错误处理流程**:

```
1. 执行 on_init() 方法
2. 如果抛出异常:
   a. 捕获异常
   b. 获取 agent_code (默认从 self.agent_code)
   c. 格式化错误消息: error_code.format_message(agent_code, exception_detail)
   d. 记录日志: logger.error(...)
   e. 创建 SimTaskInitResponse:
      - command_status = CommandStatus.FAILED
      - error_code = "AGENT_INIT_FAILURE"
      - error_message = 格式化后的消息
   f. 返回错误响应
3. 如果没有异常:
   - 返回正常的响应
```

#### 方式 2: `safe_execute()` 工具函数

**适用场景**: 单个操作的错误处理，需要细粒度控制

**特点**:
- 返回 `(success, result, error_message)` 元组
- 允许在错误后继续执行
- 适合需要多次尝试或回退的场景

**使用示例**:

```python
from hydros_agent_sdk import safe_execute, ErrorCodes
from hydros_agent_sdk.utils import HydroObjectUtilsV2

def _initialize_twins_model(self):
    """初始化孪生模型"""

    # 使用 safe_execute 加载拓扑
    success, topology, error_msg = safe_execute(
        HydroObjectUtilsV2.build_waterway_topology,
        ErrorCodes.TOPOLOGY_LOAD_FAILURE,
        self.agent_code,
        topology_url
    )

    if not success:
        logger.error(f"Failed to load topology: {error_msg}")
        # 可以选择使用默认拓扑或抛出异常
        raise RuntimeError(f"Topology load failed: {error_msg}")

    self._topology = topology

    # 使用 safe_execute 创建求解器
    success, solver, error_msg = safe_execute(
        self._create_solver,
        ErrorCodes.MODEL_INITIALIZATION_FAILURE,
        self.agent_code
    )

    if not success:
        logger.error(f"Failed to create solver: {error_msg}")
        raise RuntimeError(f"Solver creation failed: {error_msg}")

    self._solver = solver
```

#### 方式 3: `AgentErrorContext` 上下文管理器

**适用场景**: 特定代码块的错误处理

**特点**:
- 使用 `with` 语句包裹代码块
- 提供 `has_error` 和 `error_message` 属性
- 适合需要在错误后继续执行的场景

**使用示例**:

```python
from hydros_agent_sdk import AgentErrorContext, ErrorCodes

def _execute_twins_simulation(self, step: int):
    """执行仿真步骤"""

    # 收集边界条件（使用错误上下文）
    with AgentErrorContext(
        ErrorCodes.BOUNDARY_CONDITION_ERROR,
        agent_name=self.agent_code
    ) as ctx:
        boundary_conditions = self._collect_boundary_conditions(step)

    if ctx.has_error:
        logger.error(f"Failed to collect boundary conditions: {ctx.error_message}")
        # 使用默认边界条件或返回空结果
        boundary_conditions = {}

    # 执行仿真（使用错误上下文）
    with AgentErrorContext(
        ErrorCodes.SIMULATION_EXECUTION_FAILURE,
        agent_name=self.agent_code
    ) as ctx:
        results = self._run_simulation(step, boundary_conditions)

    if ctx.has_error:
        logger.error(f"Failed to run simulation: {ctx.error_message}")
        return []

    # 转换结果为指标
    metrics_list = self._convert_results_to_metrics(results)
    return metrics_list
```

#### 方式 4: `create_error_response()` 手动创建

**适用场景**: 需要完全控制错误处理逻辑

**特点**:
- 手动捕获异常
- 手动创建错误响应
- 最大灵活性

**使用示例**:

```python
from hydros_agent_sdk import create_error_response, ErrorCodes
from hydros_agent_sdk.protocol.commands import SimTaskTerminateRequest, SimTaskTerminateResponse

def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
    """终止 agent"""
    try:
        # 清理资源
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        # 返回成功响应
        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self
        )

    except Exception as e:
        logger.error(f"Error during termination: {e}", exc_info=True)

        # 手动创建错误响应
        return create_error_response(
            SimTaskTerminateResponse,
            ErrorCodes.AGENT_TERMINATE_FAILURE,
            self.agent_code,
            str(e),
            command_id=request.command_id,
            context=request.context,
            source_agent_instance=self
        )
```

## 完整示例

### 示例 1: 使用装饰器的完整 Agent

```python
from hydros_agent_sdk import (
    TwinsSimulationAgent,
    ErrorCodes,
    handle_agent_errors,
)
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import CommandStatus

class MyTwinsAgent(TwinsSimulationAgent):
    """使用错误处理装饰器的孪生仿真 agent"""

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """初始化 agent（自动错误处理）"""
        # 加载配置
        self.load_agent_configuration(request)

        # 加载拓扑
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        self._topology = HydroObjectUtilsV2.build_waterway_topology(topology_url)

        # 注册到状态管理器
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        # 初始化模型
        self._initialize_twins_model()

        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={}
        )

    @handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """处理 tick（自动错误处理）"""
        # 执行仿真
        metrics_list = self._execute_twins_simulation(request.step)

        # 发送指标
        self.send_metrics(metrics_list)

        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self
        )

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """终止 agent（自动错误处理）"""
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self
        )
```

### 示例 2: 混合使用多种错误处理方式

```python
from hydros_agent_sdk import (
    TwinsSimulationAgent,
    ErrorCodes,
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
)

class AdvancedAgent(TwinsSimulationAgent):
    """混合使用多种错误处理方式的 agent"""

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """使用装饰器处理整体错误"""
        self.load_agent_configuration(request)

        # 使用 safe_execute 处理拓扑加载
        success, topology, error_msg = safe_execute(
            HydroObjectUtilsV2.build_waterway_topology,
            ErrorCodes.TOPOLOGY_LOAD_FAILURE,
            self.agent_code,
            self.properties.get_property('hydros_objects_modeling_url')
        )

        if not success:
            raise RuntimeError(f"Topology load failed: {error_msg}")

        self._topology = topology

        # 初始化模型
        self._initialize_model()

        return SimTaskInitResponse(...)

    def _initialize_model(self):
        """使用上下文管理器处理模型初始化"""
        # 创建求解器
        with AgentErrorContext(
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            self._solver = self._create_solver()

        if ctx.has_error:
            raise RuntimeError(f"Solver creation failed: {ctx.error_message}")

        # 加载参数
        with AgentErrorContext(
            ErrorCodes.CONFIGURATION_LOAD_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            self._load_solver_parameters()

        if ctx.has_error:
            logger.warning(f"Failed to load parameters, using defaults: {ctx.error_message}")
            self._use_default_parameters()
```

## 错误响应格式

当发生错误时，返回的 Response 格式如下：

```python
{
    "command_id": "CMD_123",
    "command_type": "task_init_response",
    "context": {...},
    "command_status": "FAILED",  # CommandStatus.FAILED
    "error_code": "AGENT_INIT_FAILURE",
    "error_message": "Agent initialization failed: MyAgent, detail: Failed to load topology from http://example.com/topology.yaml\nTraceback:\n...",
    "source_agent_instance": {...},
    "created_agent_instances": [],
    "managed_top_objects": {}
}
```

## 最佳实践

### 1. 选择合适的错误处理方式

| 场景 | 推荐方式 | 原因 |
|-----|---------|------|
| Agent 生命周期方法 | `@handle_agent_errors` | 自动处理，代码简洁 |
| 单个操作可能失败 | `safe_execute()` | 细粒度控制，可继续执行 |
| 代码块错误处理 | `AgentErrorContext` | 灵活，可在错误后继续 |
| 复杂错误逻辑 | 手动 `try-except` | 完全控制 |

### 2. 错误消息应包含的信息

- Agent 名称（agent_code）
- 错误详情（异常消息）
- 相关参数（URL、文件路径等）
- Traceback（开发环境）

### 3. 日志记录

所有错误都会自动记录日志，包含：
- 错误级别：`ERROR`
- 错误消息：格式化后的消息
- Traceback：完整的异常堆栈
- 上下文：task_id, agent_code（自动设置）

### 4. 错误码选择

- 使用最具体的错误码
- 如果没有合适的错误码，使用 `SYSTEM_ERROR`
- 未来会根据业务需求扩展错误码

## 扩展错误码

如果需要添加新的错误码，在 `error_codes.py` 中添加：

```python
class ErrorCodes:
    # ... 现有错误码 ...

    # 新增错误码
    MY_CUSTOM_ERROR = ErrorCode(
        "MY_CUSTOM_ERROR",
        "My custom error: {0}, detail: {1}"
    )
```

## 参考

- Java 实现: `/working/hydro_coding/hydros-common/src/main/java/com/hydros/common/ErrorCodes.java`
- Python 实现: `hydros_agent_sdk/error_codes.py`
- 错误处理工具: `hydros_agent_sdk/error_handling.py`
- 示例代码: `examples/error_handling_example.py`

## 常见问题

### Q: 装饰器会影响性能吗？

A: 影响极小。装饰器只在发生异常时才会执行额外逻辑，正常情况下几乎没有性能开销。

### Q: 可以在装饰器中自定义错误消息吗？

A: 可以。在抛出异常时使用自定义消息：

```python
raise ValueError("Custom error message with details")
```

### Q: 如何在错误响应中包含额外信息？

A: 使用 `create_error_response()` 手动创建响应，可以添加任何额外字段。

### Q: 错误码不够用怎么办？

A: 当前提供了核心错误码，未来会根据业务需求扩展。临时可以使用 `SYSTEM_ERROR` 并在消息中说明具体错误。
