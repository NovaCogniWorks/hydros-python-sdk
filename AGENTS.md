# 仓库规范

## 项目结构与模块组织
`hydros_agent_sdk/` 是 SDK 源码目录，包含 MQTT 客户端、协议模型、命令运行时、智能体基类、工具类以及日志/配置封装。`hydros_agent_sdk/agent_commands/` 是新的命令子系统，路由、持久化、传输相关改动尽量集中在这里。`examples/` 和 `custom-agent/` 放可运行示例和启动脚本。`tests/` 放主题规则、ID 生成、运行时行为和调度相关的单元测试。

## 构建、测试与开发命令
- `pip install -e .` 以可编辑模式安装，便于本地联调。
- `python -m unittest discover -s tests` 运行全部单元测试。
- `python -m unittest tests.test_agent_commands_refactor` 运行命令运行时回归测试。
- `python -m py_compile hydros_agent_sdk/**/*.py custom-agent/**/**/*.py` 快速检查语法。
- `python examples/multi_agent_launcher.py` 或 `python custom-agent/pump/multi_agent_launcher.py` 启动示例 launcher，前提是已准备好 `env.properties` 和 `agent.properties`。

## 编码风格与命名规范
统一使用 4 空格缩进，函数和模块用 `snake_case`，类和 Pydantic 模型用 `PascalCase`。协议和 topic 常量集中放在 `hydros_agent_sdk/topics.py`，模型定义放在 `hydros_agent_sdk/protocol/`。仓库没有额外的格式化或 lint 配置，按现有风格写，改动保持小而明确。需要注释时，尽量简短，并使用中文口语化表达。

## 测试规范
测试框架使用标准库 `unittest`。新增测试文件命名为 `test_*.py`，断言只聚焦单一行为。优先写隔离测试和 mock，只有 MQTT 或文件系统行为必须验证时才做集成测试。新增命令类型或 topic 规则时，要在 `tests/` 里同步补覆盖。

## 提交与 PR 规范
最近提交通常很短、范围明确，并且常用中文摘要，例如 `智能体指令: 优化`。建议保持这种风格：标题简短、命令式、只描述一个变更点。PR 需要包含简要说明、影响路径、执行过的测试命令，以及配置或启动方式变更。如果行为有变化，说明运行影响；只有在有助于复现问题时才附日志或截图。

## 安全与配置提示
不要把 broker 地址、cluster ID、node ID 写死在代码里。优先使用 `env.properties` 和 `agent.properties`，不要把环境相关值直接塞进源码。MQTT topic 统一通过 `HydrosTopics` 构造，避免在 agent 或 launcher 里重复拼接字符串。
