# Custom Agent 使用手册

本目录用于启动与运行自定义 agent（power、pump、scheduling），并共享同一套 MQTT 配置与日志。

## 目录结构

```
custom-agent/
├── start_agents.sh           # 启动脚本
├── multi_agent_launcher.py   # Python 启动器
├── env.properties            # 共享环境配置
├── power/
│   ├── agent.properties
│   ├── env.properties
│   ├── power_agent.py
│   └── power_solver.py
├── pump/
│   ├── agent.properties
│   └── outflow_plan_agent.py
└── scheduling/
    ├── agent.properties
    └── scheduling_agent.py
```

## 前置条件

- Python 3
- 依赖安装（项目根目录执行）：
  ```bash
  pip install -e .
  pip install pyyaml
  ```
- MQTT 配置：`custom-agent/env.properties`

## 配置说明

### env.properties（共享配置）

位于 `custom-agent/env.properties`，用于配置 MQTT 连接和集群信息。

示例：
```properties
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/cluster_name
hydros_cluster_id=default_cluster
hydros_node_id=default_node
```

### agent.properties（每个 agent）

位于 `custom-agent/power|pump|scheduling/agent.properties`，用于描述 agent 元信息。

示例：
```properties
agent_code=POWER_AGENT
agent_type=POWER_AGENT
agent_name=Power Agent
```

## 启动方式

### 启动指定 agent

```bash
bash custom-agent/start_agents.sh power pump scheduling
```

### 启动全部 agent

```bash
bash custom-agent/start_agents.sh --all
```

### 列出可用 agent

```bash
bash custom-agent/start_agents.sh --list
```

### 查看日志

```bash
bash custom-agent/start_agents.sh --logs
```

## 调试模式

### 启用调试（等待调试器）

```bash
bash custom-agent/start_agents.sh --debug power
```

### 启用调试（不等待调试器）

```bash
bash custom-agent/start_agents.sh --debug --debug-nowait power
```

### 指定调试端口

```bash
bash custom-agent/start_agents.sh --debug --debug-port 5679 power
```

## 日志

- 日志文件：`custom-agent/logs/hydros.log`
- 过滤示例：
  ```bash
  grep 'POWER_AGENT' custom-agent/logs/hydros.log
  ```

## 常见问题

### 1) Windows 下提示 python3 没权限

请使用可用的 Python 命令（如 `python` 或 `py`）直接启动：
```bash
python custom-agent/multi_agent_launcher.py power pump scheduling
```

### 2) MQTT 连接失败

检查 `custom-agent/env.properties` 中的 broker 地址、端口和 topic。
