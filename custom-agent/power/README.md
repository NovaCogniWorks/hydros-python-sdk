# Custom Agent 使用手册

本目录用于启动与运行 power 自定义 agent，并共享同一套 MQTT 配置与日志。

## 目录结构

```
custom-agent/
├── power/
│   ├── start_agents.sh           # 启动脚本
│   ├── multi_agent_launcher.py   # MultiAgentLauncherApp 薄入口
│   ├── outflowplan/
│   │   ├── agent.properties
│   │   └── power_outflow_plan_agent.py
│   ├── scheduling/
│   │   ├── agent.properties
│   │   └── power_scheduling_agent.py
│   └── logs/
│       └── hydros.log
```

## 前置条件

- Python 3
- 依赖安装（项目根目录执行）：
  ```bash
  pip install -e .
  pip install -e ".[power]"
  ```
- MQTT 配置：在 `custom-agent/power/env.properties` 准备本地连接配置

## 配置说明

### env.properties（共享配置）

位于 `custom-agent/power/env.properties`，用于配置 MQTT 连接和集群信息。真实配置只属于本地或部署环境，不应提交。

示例：
```properties
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
hydros_cluster_id=example-cluster
hydros_node_id=example-node
```

### agent.properties（每个 agent）

位于 `custom-agent/power/outflowplan|scheduling/agent.properties`，用于描述 agent 元信息。

示例：
```properties
agent_code=OUTFLOW_PLAN_AGENT_POWER
agent_type=OUTFLOW_PLAN_AGENT
agent_name=Power Outflow Plan Agent
```

## 启动方式

### 启动指定 agent

```bash
bash custom-agent/power/start_agents.sh outflowplan scheduling
```

### 启动全部 agent

```bash
bash custom-agent/power/start_agents.sh --all
```

### 列出可用 agent

```bash
bash custom-agent/power/start_agents.sh --list
```

### 启动前检查

```bash
bash custom-agent/power/start_agents.sh --check
```

### 启动电站边缘控制 HTTP 服务

```bash
python custom-agent/power/control_algorithm_service.py
```

默认监听 `127.0.0.1:8066`，标准接口为：

```text
POST /engine/v1/api/control-algorithms/power_station_edge_control/solve
```

可通过 `HYDROS_CONTROL_ALGORITHM_HOST`、`HYDROS_CONTROL_ALGORITHM_PORT` 调整监听地址。edge 侧的
`hydros.edge.control-algorithm.python-http.endpoint` 应配置为该服务的基址，例如
`http://127.0.0.1:8066`。电站站级 `water_flow` 输入会分配为站内可用水轮机的 `water_flow` 候选目标，
最终范围校验与设备写入仍由 edge 负责。

### 查看日志

```bash
bash custom-agent/power/start_agents.sh --logs
```

## 调试模式

### 启用调试（等待调试器）

```bash
bash custom-agent/power/start_agents.sh --debug outflowplan
```

### 启用调试（不等待调试器）

```bash
bash custom-agent/power/start_agents.sh --debug --debug-nowait outflowplan
```

### 指定调试端口

```bash
bash custom-agent/power/start_agents.sh --debug --debug-port 5679 outflowplan
```

## 日志

- 日志文件：`custom-agent/power/logs/hydros.log`
- 过滤示例：
  ```bash
  grep 'POWER_AGENT' custom-agent/power/logs/hydros.log
  ```

## 常见问题

### 1) Windows 下提示 python3 没权限

请使用可用的 Python 命令（如 `python` 或 `py`）直接启动：
```bash
python -m hydros_agent_sdk.launcher --launcher-dir custom-agent/power --project-root . -- outflowplan scheduling
```

### 2) MQTT 连接失败

检查 `custom-agent/power/env.properties` 中的 broker 地址、端口和 cluster。
