# Hydros Agent 调试指南

本指南介绍如何调试 Hydros Agent SDK 的各种方式。

## 目录

- [方案 1: 使用 debugpy 远程调试（推荐）](#方案-1-使用-debugpy-远程调试推荐)
- [方案 2: VS Code 直接调试](#方案-2-vs-code-直接调试)
- [方案 3: PyCharm 调试](#方案-3-pycharm-调试)
- [方案 4: 使用 pdb 命令行调试](#方案-4-使用-pdb-命令行调试)

---

## 方案 1: 使用 debugpy 远程调试（推荐）

这是最灵活的方案，适合调试多 agent 场景。

### 1.1 安装 debugpy

```bash
pip install debugpy
```

### 1.2 启动 Agent（调试模式）

```bash
# 启动并等待调试器连接
./start_agents.sh --debug twins ontology

# 或者使用 Python 直接启动
cd examples
python multi_agent_launcher.py --debug twins ontology
```

你会看到类似输出：

```
======================================================================
🐛 DEBUG MODE ENABLED
======================================================================
Debugpy listening on port 5678
Connect your debugger to: localhost:5678

VS Code launch.json configuration:
{
  "name": "Attach to Hydros Agent",
  "type": "debugpy",
  "request": "attach",
  "connect": {"host": "localhost", "port": 5678},
  ...
}
======================================================================
⏳ Waiting for debugger to attach...
   (Press Ctrl+C to skip and continue)
```

### 1.3 连接调试器

#### VS Code

1. 打开 VS Code
2. 按 `F5` 或点击 "Run and Debug"
3. 选择 "Attach to Hydros Agent (debugpy)"
4. 设置断点，开始调试

#### PyCharm

1. 打开 PyCharm
2. Run → Edit Configurations
3. 添加 "Python Remote Debug"
4. 设置 Host: `localhost`, Port: `5678`
5. 点击 Debug 按钮连接

### 1.4 调试选项

```bash
# 不等待调试器，直接启动（可以稍后连接）
./start_agents.sh --debug --debug-nowait twins

# 使用自定义端口
./start_agents.sh --debug --debug-port 5679 twins

# 组合使用
./start_agents.sh --debug --debug-port 5679 --debug-nowait twins ontology
```

---

## 方案 2: VS Code 直接调试

适合调试单个 agent 或开发阶段。

### 2.1 使用预配置的 launch.json

项目已包含 `.vscode/launch.json` 配置文件，提供以下调试配置：

1. **Attach to Hydros Agent (debugpy)** - 连接到远程调试会话
2. **Debug Twins Agent (Direct)** - 直接调试 twins agent
3. **Debug Ontology Agent (Direct)** - 直接调试 ontology agent
4. **Debug Multi-Agent Launcher** - 调试多 agent 启动器

### 2.2 使用步骤

1. 在 VS Code 中打开项目
2. 按 `F5` 或点击 "Run and Debug"
3. 选择要使用的调试配置
4. 设置断点
5. 开始调试

### 2.3 自定义调试配置

编辑 `.vscode/launch.json`：

```json
{
    "name": "Debug My Agent",
    "type": "debugpy",
    "request": "launch",
    "program": "${workspaceFolder}/examples/agents/twins/twins_agent.py",
    "args": [],
    "console": "integratedTerminal",
    "cwd": "${workspaceFolder}/examples/agents/twins",
    "env": {
        "PYTHONPATH": "${workspaceFolder}",
        "HYDROS_NODE_ID": "DEBUG_NODE"
    },
    "justMyCode": false
}
```

---

## 方案 3: PyCharm 调试

### 3.1 直接运行调试

1. 打开 PyCharm
2. 右键点击 `twins_agent.py` 或 `multi_agent_launcher.py`
3. 选择 "Debug 'twins_agent'"
4. 设置断点，开始调试

### 3.2 配置运行配置

1. Run → Edit Configurations
2. 添加 "Python" 配置
3. 设置：
   - Script path: `examples/multi_agent_launcher.py`
   - Parameters: `twins ontology`
   - Working directory: `examples/`
   - Environment variables: `PYTHONPATH=<project_root>`

### 3.3 远程调试

1. Run → Edit Configurations
2. 添加 "Python Remote Debug"
3. 设置 Host: `localhost`, Port: `5678`
4. 启动 agent: `./start_agents.sh --debug twins`
5. 在 PyCharm 中点击 Debug 按钮连接

---

## 方案 4: 使用 pdb 命令行调试

适合快速调试或无 IDE 环境。

### 4.1 在代码中插入断点

```python
# 在需要调试的地方插入
import pdb; pdb.set_trace()

# 或使用 Python 3.7+ 的 breakpoint()
breakpoint()
```

### 4.2 运行 Agent

```bash
cd examples
python multi_agent_launcher.py twins
```

### 4.3 pdb 常用命令

```
n (next)      - 执行下一行
s (step)      - 进入函数
c (continue)  - 继续执行
l (list)      - 显示代码
p <var>       - 打印变量
pp <var>      - 美化打印
h (help)      - 帮助
q (quit)      - 退出
```

---

## 调试技巧

### 1. 调试多 Agent 场景

使用远程调试模式，可以同时调试多个 agent：

```bash
./start_agents.sh --debug twins ontology
```

在 VS Code 中连接后，可以在不同 agent 的代码中设置断点。

### 2. 查看 MQTT 消息

在 `coordination_client.py` 中设置断点：

```python
# 在 _on_message 方法中
def _on_message(self, client, userdata, msg):
    breakpoint()  # 查看接收到的消息
    ...
```

### 3. 调试初始化流程

在 agent 的 `on_init` 方法中设置断点：

```python
def on_init(self, request: SimTaskInitRequest):
    breakpoint()  # 查看初始化请求
    ...
```

### 4. 调试仿真步骤

在 `on_tick_simulation` 方法中设置断点：

```python
def on_tick_simulation(self, request: TickCmdRequest):
    breakpoint()  # 查看每个仿真步骤
    ...
```

### 5. 条件断点

在 VS Code 中右键断点，选择 "Edit Breakpoint"，添加条件：

```python
step == 10  # 只在第 10 步暂停
object_id == 1001  # 只在特定对象时暂停
```

### 6. 日志级别调整

调试模式会自动启用 DEBUG 日志级别，查看更详细的日志：

```bash
./start_agents.sh --debug twins
```

### 7. 查看变量

在调试器中可以：
- 查看局部变量
- 查看 `self` 对象的所有属性
- 执行表达式求值
- 查看调用栈

---

## 常见问题

### Q1: debugpy 连接超时

**原因**: 防火墙阻止或端口被占用

**解决**:
```bash
# 检查端口是否被占用
lsof -i :5678

# 使用其他端口
./start_agents.sh --debug --debug-port 5679 twins
```

### Q2: 断点不生效

**原因**: 代码路径映射不正确

**解决**: 检查 `launch.json` 中的 `pathMappings`：
```json
"pathMappings": [
    {
        "localRoot": "${workspaceFolder}",
        "remoteRoot": "/working/hydro_coding/hydros-python-sdk"
    }
]
```

### Q3: 无法查看变量值

**原因**: `justMyCode` 设置为 true

**解决**: 在 `launch.json` 中设置：
```json
"justMyCode": false
```

### Q4: 调试时 Agent 超时

**原因**: 调试暂停导致 MQTT 心跳超时

**解决**:
- 使用 `--debug-nowait` 选项
- 增加 MQTT keepalive 时间
- 在非关键路径设置断点

---

## 推荐工作流

### 开发阶段

1. 使用 VS Code 直接调试单个 agent
2. 快速迭代，频繁设置断点
3. 使用 `justMyCode: false` 查看 SDK 内部

### 集成测试

1. 使用远程调试模式启动多个 agents
2. 在关键路径设置断点
3. 观察 agent 间的交互

### 生产问题排查

1. 添加详细日志
2. 使用条件断点
3. 复现问题后使用 pdb 快速定位

---

## 更多资源

- [debugpy 官方文档](https://github.com/microsoft/debugpy)
- [VS Code Python 调试](https://code.visualstudio.com/docs/python/debugging)
- [PyCharm 调试指南](https://www.jetbrains.com/help/pycharm/debugging-code.html)
- [Python pdb 文档](https://docs.python.org/3/library/pdb.html)
