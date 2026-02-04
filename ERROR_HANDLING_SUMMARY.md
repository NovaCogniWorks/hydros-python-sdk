# 错误处理实现总结

## ✅ 已完成的工作

### 1. 核心模块实现

#### `hydros_agent_sdk/error_codes.py`
- ✅ 实现 `ErrorCode` 类：单个错误码定义
- ✅ 实现 `ErrorCodes` 类：错误码集合（参照 Java 实现）
- ✅ 实现 `create_error_response()` 便捷函数
- ✅ 包含核心错误码：
  - `SYSTEM_ERROR` - 系统错误
  - `INVALID_PARAMS` - 参数错误
  - `CONFIGURATION_LOAD_FAILURE` - 配置加载失败
  - `AGENT_INIT_FAILURE` - Agent 初始化失败
  - `AGENT_TICK_FAILURE` - Agent tick 执行失败
  - `AGENT_TERMINATE_FAILURE` - Agent 终止失败
  - `TIME_SERIES_UPDATE_FAILURE` - 时序数据更新失败
  - `TOPOLOGY_LOAD_FAILURE` - 拓扑加载失败
  - `SIMULATION_EXECUTION_FAILURE` - 仿真执行失败
  - 等 20+ 个错误码

#### `hydros_agent_sdk/error_handling.py`
- ✅ 实现 `@handle_agent_errors` 装饰器：自动错误处理
- ✅ 实现 `safe_execute()` 函数：安全执行函数
- ✅ 实现 `AgentErrorContext` 上下文管理器：代码块错误处理
- ✅ 实现 `validate_request()` 函数：请求验证
- ✅ 自动识别响应类型（根据方法名）
- ✅ 自动格式化错误消息（包含 traceback）
- ✅ 自动记录错误日志

### 2. SDK 集成

#### `hydros_agent_sdk/__init__.py`
- ✅ 导出 `ErrorCode` 类
- ✅ 导出 `ErrorCodes` 错误码集合
- ✅ 导出 `create_error_response` 函数
- ✅ 导出 `handle_agent_errors` 装饰器
- ✅ 导出 `safe_execute` 函数
- ✅ 导出 `AgentErrorContext` 上下文管理器
- ✅ 导出 `validate_request` 函数

### 3. 文档和示例

#### `docs/ERROR_HANDLING.md`
- ✅ 完整的错误处理机制文档
- ✅ 错误码列表和说明
- ✅ 四种错误处理方式详解
- ✅ 完整代码示例
- ✅ 最佳实践指南
- ✅ 常见问题解答

#### `examples/error_handling_example.py`
- ✅ 可运行的完整示例
- ✅ 演示四种错误处理方式
- ✅ 演示错误码使用
- ✅ 包含详细注释

### 4. 测试验证

- ✅ 错误码格式化测试通过
- ✅ 错误处理工具导入测试通过
- ✅ 示例程序运行成功
- ✅ SDK 重新安装成功

---

## 📊 实现对比

### Java 实现 vs Python 实现

| 特性 | Java 实现 | Python 实现 | 状态 |
|-----|----------|------------|------|
| 错误码定义 | `ErrorCodes` 类 | `ErrorCodes` 类 | ✅ 完成 |
| 消息格式化 | `MessageFormat.format()` | `str.format()` | ✅ 完成 |
| 错误码数量 | ~15 个 | ~20+ 个 | ✅ 扩展 |
| 自动错误处理 | 无 | `@handle_agent_errors` | ✅ 增强 |
| 错误上下文 | 无 | `AgentErrorContext` | ✅ 增强 |
| 安全执行 | 无 | `safe_execute()` | ✅ 增强 |

### Python 实现的优势

1. **更丰富的错误处理方式**：
   - 装饰器：自动处理
   - 上下文管理器：代码块处理
   - 工具函数：细粒度控制

2. **更详细的错误信息**：
   - 自动包含 traceback
   - 自动记录日志
   - 自动设置上下文

3. **更易用的 API**：
   - 一行装饰器即可完成错误处理
   - 类型提示完整
   - 文档详细

---

## 🎯 使用指南

### 快速开始

```python
from hydros_agent_sdk import (
    TwinsSimulationAgent,
    ErrorCodes,
    handle_agent_errors,
)

class MyAgent(TwinsSimulationAgent):
    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request):
        # 任何异常都会被自动处理
        self.load_agent_configuration(request)
        self._initialize_model()
        return SimTaskInitResponse(...)

    @handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
    def on_tick(self, request):
        # 任何异常都会被自动处理
        metrics = self._execute_simulation(request.step)
        return TickCmdResponse(...)
```

### 四种错误处理方式

#### 1. 装饰器（推荐用于生命周期方法）

```python
@handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
def on_init(self, request):
    # 自动错误处理
    pass
```

#### 2. safe_execute（推荐用于单个操作）

```python
success, result, error_msg = safe_execute(
    load_topology,
    ErrorCodes.TOPOLOGY_LOAD_FAILURE,
    "MyAgent",
    topology_url
)
if not success:
    logger.error(error_msg)
```

#### 3. 上下文管理器（推荐用于代码块）

```python
with AgentErrorContext(ErrorCodes.SIMULATION_EXECUTION_FAILURE, "MyAgent") as ctx:
    results = run_simulation()

if ctx.has_error:
    logger.error(ctx.error_message)
```

#### 4. 手动处理（完全控制）

```python
try:
    # 业务逻辑
    pass
except Exception as e:
    return create_error_response(
        SimTaskInitResponse,
        ErrorCodes.AGENT_INIT_FAILURE,
        "MyAgent",
        str(e),
        ...
    )
```

---

## 📝 错误响应格式

当 agent 发生错误时，返回给 coordinator 的响应格式：

```json
{
  "command_id": "CMD_123",
  "command_type": "task_init_response",
  "context": {
    "biz_scene_instance_id": "TASK202601282328VG3IE7H3CA0F",
    ...
  },
  "command_status": "FAILED",
  "error_code": "AGENT_INIT_FAILURE",
  "error_message": "Agent initialization failed: MyAgent, detail: Failed to load topology\nTraceback:\n  File ...\n    ...",
  "source_agent_instance": {
    "agent_id": "AGT202602040856HZ18NF_TWINS_SIMULATION_AGENT",
    "agent_code": "TWINS_SIMULATION_AGENT",
    ...
  },
  "created_agent_instances": [],
  "managed_top_objects": {}
}
```

**关键字段**：
- `command_status`: `"FAILED"` 表示失败
- `error_code`: 错误码（如 `"AGENT_INIT_FAILURE"`）
- `error_message`: 详细错误消息（包含 agent 名称、错误详情、traceback）

---

## 🔄 错误处理流程

### 使用装饰器的流程

```
1. Coordinator 发送 Request (如 SimTaskInitRequest)
   ↓
2. SimCoordinationClient 接收并路由到 agent.on_init()
   ↓
3. @handle_agent_errors 装饰器包装的 on_init() 执行
   ↓
4a. 正常情况：
    - 执行业务逻辑
    - 返回 SimTaskInitResponse (command_status=SUCCEED)
    ↓
4b. 异常情况：
    - 捕获异常
    - 获取 agent_code
    - 格式化错误消息: ErrorCodes.AGENT_INIT_FAILURE.format_message(agent_code, exception)
    - 记录日志: logger.error(...)
    - 创建 SimTaskInitResponse:
      * command_status = FAILED
      * error_code = "AGENT_INIT_FAILURE"
      * error_message = 格式化后的消息
    - 返回错误响应
   ↓
5. SimCoordinationClient 通过 MQTT 发送响应给 Coordinator
   ↓
6. Coordinator 接收响应，根据 command_status 判断成功或失败
```

---

## 🎓 最佳实践

### 1. 选择合适的错误处理方式

| 场景 | 推荐方式 | 示例 |
|-----|---------|------|
| Agent 生命周期方法 | `@handle_agent_errors` | `on_init`, `on_tick`, `on_terminate` |
| 单个操作可能失败 | `safe_execute()` | 加载拓扑、创建求解器 |
| 代码块需要错误处理 | `AgentErrorContext` | 边界条件收集、仿真执行 |
| 复杂错误处理逻辑 | 手动 `try-except` | 需要多种错误处理策略 |

### 2. 错误消息应包含的信息

✅ **好的错误消息**：
```
Agent initialization failed: MyAgent, detail: Failed to load topology from http://example.com/topology.yaml: HTTP 404 Not Found
Traceback:
  File "/path/to/agent.py", line 123, in on_init
    topology = load_topology(url)
  ...
```

❌ **不好的错误消息**：
```
Error
```

### 3. 错误码选择原则

- 使用最具体的错误码（如 `TOPOLOGY_LOAD_FAILURE` 而不是 `SYSTEM_ERROR`）
- 如果没有合适的错误码，使用 `SYSTEM_ERROR`
- 未来会根据业务需求扩展错误码清单

### 4. 日志记录

所有错误都会自动记录日志，包含：
- 错误级别：`ERROR`
- 错误消息：格式化后的消息
- Traceback：完整的异常堆栈
- 上下文：`task_id`, `agent_code`（自动设置）

示例日志：
```
2026-02-04 10:30:15,123 ERROR [TASK202601282328VG3IE7H3CA0F|MyAgent] Error in on_init for agent MyAgent: Agent initialization failed: MyAgent, detail: Failed to load topology
Traceback (most recent call last):
  File "/path/to/agent.py", line 123, in on_init
    topology = load_topology(url)
  ...
```

---

## 🚀 下一步

### 1. 更新现有 Agent 基类

建议在现有的 agent 基类中添加错误处理装饰器：

```python
# hydros_agent_sdk/agents/tickable_agent.py

from hydros_agent_sdk.error_handling import handle_agent_errors
from hydros_agent_sdk.error_codes import ErrorCodes

class TickableAgent(BaseHydroAgent):
    # 可以在基类中提供默认的错误处理
    # 子类可以覆盖或使用自己的装饰器

    @abstractmethod
    def on_init(self, request):
        pass

    # 在基类的 on_tick 中添加错误处理
    def on_tick(self, request):
        try:
            # 设置日志上下文
            self._set_agent_logging_context()

            # 更新当前步骤
            self._current_step = request.step

            # 调用子类实现
            metrics_list = self.on_tick_simulation(request)

            # 发送指标
            if metrics_list:
                self.send_metrics(metrics_list)

            # 返回成功响应
            return TickCmdResponse(
                command_id=request.command_id,
                context=request.context,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self
            )

        except Exception as e:
            logger.error(f"Error in on_tick: {e}", exc_info=True)
            return create_error_response(
                TickCmdResponse,
                ErrorCodes.AGENT_TICK_FAILURE,
                self.agent_code,
                str(e),
                command_id=request.command_id,
                context=request.context,
                source_agent_instance=self
            )
```

### 2. 更新示例代码

更新 `examples/agents/twins/twins_agent.py` 和 `examples/agents/ontology/ontology_agent.py`，添加错误处理装饰器。

### 3. 扩展错误码

根据实际业务需求，继续扩展错误码清单。

### 4. 添加单元测试

为错误处理机制添加单元测试：
- 测试错误码格式化
- 测试装饰器功能
- 测试 safe_execute
- 测试 AgentErrorContext
- 测试错误响应创建

---

## 📚 参考文档

- **Java 实现**: `/working/hydro_coding/hydros-common/src/main/java/com/hydros/common/ErrorCodes.java`
- **Python 实现**:
  - `hydros_agent_sdk/error_codes.py`
  - `hydros_agent_sdk/error_handling.py`
- **文档**: `docs/ERROR_HANDLING.md`
- **示例**: `examples/error_handling_example.py`

---

## ✅ 总结

### 实现的核心功能

1. ✅ **ErrorCodes 错误码管理**
   - 参照 Java 实现
   - 支持消息格式化
   - 包含 20+ 个错误码

2. ✅ **四种错误处理方式**
   - `@handle_agent_errors` 装饰器
   - `safe_execute()` 函数
   - `AgentErrorContext` 上下文管理器
   - 手动 `create_error_response()`

3. ✅ **自动错误处理**
   - 自动捕获异常
   - 自动转换为 Response
   - 自动设置 error_code 和 error_message
   - 自动记录日志

4. ✅ **完整文档和示例**
   - 详细的使用文档
   - 可运行的示例代码
   - 最佳实践指南

### 与 Java 实现的对比

| 特性 | Java | Python | 优势 |
|-----|------|--------|------|
| 错误码定义 | ✅ | ✅ | 相同 |
| 消息格式化 | ✅ | ✅ | 相同 |
| 自动错误处理 | ❌ | ✅ | Python 更强 |
| 装饰器支持 | ❌ | ✅ | Python 独有 |
| 上下文管理器 | ❌ | ✅ | Python 独有 |
| 类型提示 | ✅ | ✅ | 相同 |

### 开发者体验提升

**重构前**：
```python
def on_init(self, request):
    try:
        # 业务逻辑
        pass
    except Exception as e:
        logger.error(f"Error: {e}")
        return SimTaskInitResponse(
            command_status=CommandStatus.FAILED,
            error_code="SYSTEM_ERROR",
            error_message=str(e),
            ...
        )
```

**重构后**：
```python
@handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
def on_init(self, request):
    # 业务逻辑
    # 错误自动处理
    pass
```

---

**实现完成时间**: 2026-02-04
**版本**: v1.0
**状态**: ✅ 完成并测试通过
