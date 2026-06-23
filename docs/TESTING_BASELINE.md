# Python SDK 测试基线

本文档记录 `hydros-python-sdk` 后续深度优化前后的固定测试基线。

测试基线的目标不是一次跑完所有历史测试，而是把 SDK 主链路和中央调度事件面固定成可重复的绿色检查；可选业务/仿真依赖测试单独作为扩展基线处理。

## 基线入口

统一入口：

```bash
python scripts/run_test_baseline.py
```

默认模式是 `sdk`，也就是当前稳定的日常 SDK 绿线。

可用模式：

```bash
python scripts/run_test_baseline.py central-events
python scripts/run_test_baseline.py central
python scripts/run_test_baseline.py central-router
python scripts/run_test_baseline.py sdk
python scripts/run_test_baseline.py compile
python scripts/run_test_baseline.py full
python scripts/run_test_baseline.py list
```

## 模式说明

### `central-events`

只运行中央调度外部事件注入基线：

```bash
python scripts/run_test_baseline.py central-events
```

覆盖范围：

- `hydro_event_command` 注入 `TIME_SERIES_DATA_UPDATED`。
- 外部事件经 `SimCoordinationClient`、`CoordinationCommandRouter`、`MultiAgentCallback` 到达 `MpcCentralSchedulingAgent`。
- 成功事件激活 MPC rolling loop，并返回 `hydro_event_ack_response`。
- 缺少 rolling 配置时返回 `FAILED` ack，且不创建 `task_state`。
- 直接 `time_series_data_update_request` 能经 multi-agent 分发到中央调度。
- `OUTFLOW_TIME_SERIES_DATA_UPDATED` 当前默认语义是成功 ack，但不激活 MPC。

### `central`

运行中央调度事件注入基线，加上已有中央调度直接调用保护：

```bash
python scripts/run_test_baseline.py central
```

适用于修改以下模块后快速确认中央调度行为：

- `hydros_agent_sdk/agents/central_scheduling_agent.py`
- `hydros_agent_sdk/agents/mpc_central_scheduling_agent.py`
- `hydros_agent_sdk/mpc/rolling_runtime.py`
- `hydros_agent_sdk/scheduling_task_state*.py`

### `central-router`

在 `central` 基础上追加 router 和 multi-agent 相关测试：

```bash
python scripts/run_test_baseline.py central-router
```

适用于修改以下模块：

- `hydros_agent_sdk/coordination_client.py`
- `hydros_agent_sdk/runtime/coordination_router.py`
- `hydros_agent_sdk/multi_agent.py`
- `hydros_agent_sdk/protocol/commands.py`
- `hydros_agent_sdk/protocol/events.py`

该模式会额外收集 `tests.test_coordination_client_dispatch` 和
`tests.test_multi_agent_callback` 中无参数的模块级 `test_*` 函数，
用于覆盖当前 `unittest discover` 默认不会收集到的 router/multi-agent
兼容测试。

### `sdk`

日常 SDK 绿线：

```bash
python scripts/run_test_baseline.py sdk
```

该模式运行当前稳定的 unittest SDK 绿线：`tests/test_*.py` 中除可选依赖
测试之外、可被 `unittest` 稳定收集的测试。当前排除：

- `tests.test_hydrosim_demo`
- `tests.test_power_outflowplan_power_agent`
- `tests.test_pump_dynamic_demand_plan`
- `tests.test_pump_scheduling_agent`

这些测试依赖 `pandas` 或 `matplotlib` 等可选业务/仿真依赖，不作为默认 SDK 优化绿线。

部分历史测试文件使用 pytest 风格的模块级函数。默认 `sdk` 模式不强制把
所有模块级函数纳入绿线，避免把尚未整理为稳定 unittest 基线的历史测试一次性
混入日常优化检查；需要 router/multi-agent 函数测试时使用 `central-router`。

### `compile`

语法和导入基础检查：

```bash
python scripts/run_test_baseline.py compile
```

等价于检查：

```bash
python -m compileall -q hydros_agent_sdk tests
```

### `full`

全量 unittest discovery：

```bash
python scripts/run_test_baseline.py full
```

当前本地环境中，`full` 预期会因为缺少可选依赖失败：

- `matplotlib`
- `pandas`

只有在安装完整业务/仿真依赖后，才把 `full` 作为必须绿色的基线。

## 推荐执行顺序

修改中央调度事件、MPC rolling、外部事件注入时：

```bash
python scripts/run_test_baseline.py central
python scripts/run_test_baseline.py compile
```

修改 router、multi-agent、protocol event/command 时：

```bash
python scripts/run_test_baseline.py central-router
python scripts/run_test_baseline.py compile
```

完成一轮 SDK 优化后：

```bash
python scripts/run_test_baseline.py sdk
python scripts/run_test_baseline.py compile
```

如果安装了可选业务/仿真依赖，再运行：

```bash
python scripts/run_test_baseline.py full
```

## 当前基线状态

截至建立本基线时：

- `central-events`：绿色。
- `central`：绿色。
- `central-router`：绿色。
- `sdk`：绿色，排除 4 个可选依赖测试。
- `compile`：绿色。
- `full`：非绿色，原因是本地缺少 `pandas` 和 `matplotlib`。

## 维护规则

- 新增中央调度事件语义时，优先补 `tests/test_central_scheduling_event_injection.py`。
- 修改事件协议模型时，同时运行 `central-router`，必要时补 Java payload shape 兼容测试。
- 把可选依赖测试迁入 `sdk` 前，必须先确保它们能在最小 SDK 环境中稳定运行，或在测试内部显式 skip。
- 不要把本地 `env.properties` 纳入测试基线；测试应通过 fake client、fake state manager 和内存对象构造运行环境。
