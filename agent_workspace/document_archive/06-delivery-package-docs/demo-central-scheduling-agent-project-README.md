# Demo Central Scheduling Agent Project

## 1. 项目说明

这是一个基于 `hydros-agent-sdk` 生成的中央调度样板项目，用于给业务方提供 `CentralSchedulingAgent` 的最小可运行接入模板。

当前样板类型：

- Agent 基类：`CentralSchedulingAgent`
- Agent 类名：`DemoCentralAgent`
- Agent 编码：`DEMO_CENTRAL_AGENT`
- Agent 类型：`CENTRAL_SCHEDULING_AGENT`

## 2. 目录结构

```text
demo-central-scheduling-agent-project/
  agent_app/
    __init__.py
    agent_impl.py
    business_engine.py
  conf/
    env.properties
    agent.properties
  launcher.py
  pyproject.toml
  README.md
```

## 3. 安装

先安装 SDK：

```powershell
pip install -e .
```

如果希望把当前 demo 项目也作为本地工程安装：

```powershell
cd agent_workspace\execution_agent\outputs\packages\external-delivery-package\demo-central-scheduling-agent-project
pip install -e .
```

## 4. 配置

修改以下两个文件：

- `conf/env.properties`
- `conf/agent.properties`

其中：

- `env.properties` 负责 MQTT、集群、节点配置
- `agent.properties` 负责中央调度 Agent 身份配置

## 5. 启动

在项目目录下执行：

```powershell
python launcher.py
```

## 6. 联调建议

建议按以下顺序联调：

1. 先发 `task_init_request`
2. 再发 `tick_cmd_request`
3. 观察 `on_optimization(step)` 是否被调用
4. 最后发 `task_terminate_request`

可直接参考上级目录样例：

- `..\samples\task_init_request.json`
- `..\samples\tick_cmd_request.json`
- `..\samples\task_terminate_request.json`

## 7. 代码职责

- `agent_app/business_engine.py`
  放中央调度计算、优化或控制逻辑
- `agent_app/agent_impl.py`
  放 `on_init()`、`on_optimization()`、`on_terminate()` 实现
- `launcher.py`
  放统一启动逻辑

## 8. 下一步改造建议

业务方拿到这个 demo 后，建议最先改三处：

1. 改 `agent.properties` 中的 `agent_code` 和 `agent_type`
2. 改 `env.properties` 中的 MQTT 连接信息
3. 把 `business_engine.py` 替换成真实 MPC 或中央调度逻辑



