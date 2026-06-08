# AGENTS.md

本文档约束 Codex 和开发者在 `hydros-python-sdk` 仓库中的开发方式。这个仓库是 Hydros 生态的 Python Agent SDK，默认采用面向对象开发模式；新增功能要先明确对象、职责和边界，再落代码。

<!-- CODEGRAPH_START -->
## CodeGraph

本项目配置了 CodeGraph MCP 索引。处理结构性问题时优先使用 CodeGraph，而不是先用文本搜索。

- 查找类、函数、方法定义：使用 `codegraph_search`。
- 理解某个功能、模块或架构上下文：先用 `codegraph_context`。
- 查看调用方或被调用方：使用 `codegraph_callers` / `codegraph_callees`。
- 分析修改影响面：使用 `codegraph_impact`。
- 查看目录和文件结构：使用 `codegraph_files`。
- 如果 CodeGraph 提示文件刚修改且索引未同步，只对提示中的 pending 文件使用本地读取确认。
<!-- CODEGRAPH_END -->

## 开发原则

- 新增业务能力默认以类建模：先确定核心对象、对象状态、行为方法和协作关系，再决定文件位置。
- 避免把业务流程写成散落的全局函数。纯工具函数可以放在 `utils/`，但有状态、有生命周期、有外部依赖的逻辑必须封装成类。
- 优先组合，谨慎继承。只有稳定的领域层级才使用继承，例如 `BaseHydroAgent`、`TickableAgent`、具体 Agent 类型；运行时能力、传输能力、持久化能力优先通过组合注入。
- 类要保持单一职责。一个类只负责一个清晰角色，例如调度、路由、执行、持久化、配置加载、协议建模、MQTT 传输，不要写“全能管理器”。
- 外部依赖通过构造方法或显式工厂传入，避免在业务类内部偷偷读取环境变量、创建 MQTT 客户端、访问文件系统或初始化全局单例。
- 协议模型只表达数据契约和轻量校验，不承载运行时流程；运行时流程放在 service、runtime、handler、agent 类中。
- SDK 内部代码要面向抽象边界编程。传输层依赖 `transport` 抽象，命令运行时依赖 registry、handler、queue、store 等接口化对象，不直接跨层调用实现细节。

## 面向对象建模约定

- 领域对象：表达 Hydros 中长期存在的概念，例如 Agent、SimulationContext、Command、CommandLog、MPC Task State。领域对象要有明确字段和行为，不要只作为临时字典传递。
- 服务对象：表达一段可复用业务流程，例如命令执行、响应构造、指标上报、优化调用。服务类可以无状态，也可以持有显式依赖。
- 工厂对象：负责根据配置、协议请求或 Agent 类型创建对象。创建逻辑复杂时放进工厂，不要散落在 launcher 或 callback 中。
- Handler 对象：负责处理某类命令或事件。Handler 只处理分派后的单一意图，不负责 MQTT 订阅、队列消费和持久化全流程。
- Repository / Store 对象：负责持久化读写。上层只能通过明确方法访问，不直接操作内部数据结构。
- DTO / Protocol Model：用于进出系统边界的数据结构，优先使用 Pydantic 模型，禁止把任意 dict 在多层之间传递。
- Runtime 对象：负责生命周期编排，例如启动、停止、队列消费、定时报告。Runtime 可以协调多个服务，但不要承载具体业务算法。

## 目录边界

### `hydros_agent_sdk/protocol/`

- 只放协议模型、命令、事件、系统命令和协议基础类型。
- 可以使用 Pydantic 校验和序列化。
- 不允许依赖 MQTT 客户端、Agent 实现、命令运行时、MPC 优化服务或文件系统配置。
- 新增 Java 协调器兼容字段时，优先在这里补模型和兼容测试。

### `hydros_agent_sdk/agent_commands/`

- 只放智能体指令子系统，包含命令模型、分派、持久化、运行时和传输网关。
- `models/` 放命令领域模型和枚举，不放执行流程。
- `runtime/` 放执行服务、handler、registry、queue、report scheduler 和路由逻辑。
- `persistence/` 放命令日志存储，不写 MQTT 发布逻辑。
- `transport/` 放指令传输客户端和网关，不写具体业务算法。
- 新增命令类型时，要同步补模型、handler 注册、topic/路由规则和测试。

### `hydros_agent_sdk/agents/`

- 放 Agent 抽象基类、内置 Agent 类型和 Agent 相关解析器。
- 具体 Agent 要继承合适的基类，例如 `TickableAgent`、`CentralSchedulingAgent`、`OutflowPlanAgent`。
- Agent 负责生命周期入口：初始化、tick、终止、边界条件更新。复杂算法要拆到服务类或领域对象中。
- Agent 不直接拼 MQTT topic；统一使用 `HydrosTopics` 或现有客户端封装。
- Agent 不直接吞异常。生命周期方法优先使用现有错误处理机制，返回符合协议的失败响应。

### `hydros_agent_sdk/runtime/`

- 放 SDK 运行期通用对象，例如 Agent 上下文、环境配置、响应工厂。
- 不放具体泵站、电站、MPC 业务算法。
- 不反向依赖 `custom-agent/`、`examples/` 或某个具体 Agent 实现。

### `hydros_agent_sdk/transport/`

- 放通用传输抽象和实现，例如内存传输、MQTT 指标订阅。
- 传输层只处理消息收发、订阅、连接和适配，不理解具体调度业务。
- 上层调用传输层接口，不绕过接口直接依赖某个测试实现。

### `hydros_agent_sdk/mpc/`

- 放 MPC 相关配置、模型、优化服务、控制指令构造、指标缓存、上报和任务状态。
- MPC 内部可以有领域服务和状态对象，但不要把 Agent 生命周期逻辑塞进这里。
- MPC 对外暴露稳定服务或模型，具体 Agent 通过组合调用。

### `hydros_agent_sdk/utils/`

- 只放无状态或弱状态的通用工具，例如 ID 生成、YAML 加载、属性解析、拓扑工具、指标工具。
- 如果工具开始持有生命周期、缓存、外部连接或复杂策略，应迁移为 service/runtime 类。
- 工具函数要保持输入输出明确，不依赖隐式全局状态。

### 根目录核心模块

- `base_agent.py`、`factory.py`、`state_manager.py`、`coordination_client.py`、`coordination_callback.py` 是 SDK 核心入口，修改前要先确认调用影响面。
- `topics.py` 是 topic 规则集中位置；新增或调整 topic 不要在业务代码里硬编码字符串。
- `logging_config.py` 负责日志上下文和格式，不要在业务类里重复实现日志格式。
- `error_codes.py`、`error_handling.py` 是错误协议入口；新增错误类型要保持和协调器语义一致。

### `examples/` 和 `custom-agent/`

- `examples/` 用于演示 SDK 推荐用法，可以包含较轻量的示例算法，但不能反向成为 SDK 依赖。
- `custom-agent/` 放业务定制 Agent、启动脚本和业务配置。业务算法应封装成类，launcher 只负责组装和启动。
- 示例和业务目录可以依赖 `hydros_agent_sdk`，SDK 源码不能依赖示例或业务目录。
- 环境值放在 `env.properties`、`agent.properties` 或外部配置中，不要写死 broker、cluster、node、topic。

### `tests/`

- 测试文件命名为 `test_*.py`，优先使用标准库 `unittest`，已有 pytest 兼容用例可以保持。
- 测试目录尽量和被测模块对应，例如 topic 规则、指令运行时、MPC 服务、Agent 生命周期分别建独立测试。
- 新增命令类型、协议字段、topic 规则、生命周期行为或错误响应时，必须补对应测试。
- 测试辅助对象放在 `tests/helpers/`，不要塞进 SDK 正式包。

## 代码约定

- Python 版本要求为 `>=3.9`，代码要兼容 3.9 到 3.12。
- 使用 4 空格缩进；模块、函数、变量使用 `snake_case`；类、Pydantic 模型、异常类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
- 公共类和公共方法要有清晰命名，名字体现职责，不使用含糊的 `Manager`、`Processor`、`Helper`，除非职责已经被上下文严格限定。
- 方法长度尽量短。一个方法如果同时做解析、校验、外部调用、状态修改和响应构造，应拆成私有方法或服务类。
- 私有方法使用单下划线前缀，表示类内部协作步骤；不要把大量私有方法当作跨模块 API 调用。
- 类型标注要覆盖新增公共方法、构造方法参数和返回值。复杂结构优先定义 Pydantic 模型、dataclass 或明确类型别名。
- 日志使用 `logging_config` 的上下文机制，业务日志要包含任务、Agent、对象或步骤信息，避免只写“成功/失败”。
- 异常要么在边界转换成协议失败响应，要么向上抛给已有错误处理器；不要静默 `except Exception` 后继续返回成功。
- MQTT topic 必须通过 `HydrosTopics` 或既有封装构造，不允许分散手写 `/hydros/...` 字符串。
- 配置读取集中在配置对象或 loader 中，业务类使用配置对象，不重复解析 properties/YAML。
- Pydantic v2 模型使用现有 `model_config` 风格；动态属性要显式 `exclude=True` 或通过受控方式设置，避免破坏序列化契约。
- 新增 `__init__.py` 导出时要谨慎，只导出稳定公共 API，不把内部 runtime、testing helper 随意暴露。

## 依赖方向

- `protocol` 位于底层，不能依赖 SDK 运行时和具体 Agent。
- `topics`、`utils`、`transport` 是通用基础能力，不能依赖业务 Agent。
- `runtime` 可以依赖协议、topic、transport 和工具，但不依赖示例或定制业务。
- `agents` 可以依赖协议、runtime、utils、mpc 和 transport 抽象，但不要直接依赖 `custom-agent/`。
- `agent_commands` 可以依赖协议、topic、transport 抽象和持久化对象；跨子包调用要走 registry、service、gateway 等明确对象。
- `examples`、`custom-agent` 只能作为上层应用依赖 SDK，不能被 SDK 反向导入。
- 避免循环导入。遇到循环导入时，优先重新划分对象职责或引入接口/工厂，不要用局部 import 掩盖设计问题。

## 当前治理重点

下面这些问题是当前仓库里已经存在的结构性问题，后续开发要优先收敛，不能继续沿着错误形态扩展。

### P0：职责过重的核心类

- `hydros_agent_sdk/coordination_client.py` 当前同时承担 MQTT 连接、订阅、消息解析、过滤、路由、callback 调用、错误响应构造、发送队列、重试和日志上下文职责。后续新增能力不能继续塞进这个类，应逐步拆成 transport adapter、message parser、command router、callback invoker、outbox publisher、error response factory 等对象。
- `custom-agent/pump/multi_agent_launcher.py` 已收敛为应用薄入口：通用 properties 读取、Agent 目录解析、Agent 发现、动态导入、Agent 类解析、CLI 参数解析、`--list` 展示、日志/debug 配置、`MultiAgentCoordinator` 注册/启动流程和 signal/runtime 运行封装已迁移到 `hydros_agent_sdk/launcher/`。泵站入口只保留目录、env、日志和调试端口等部署配置，后续其他自定义 Agent 独立部署应复用 SDK launcher，而不是重新复制启动逻辑。
- `hydros_agent_sdk/base_agent.py` 当前同时继承协议模型并承载行为基类，还维护动态运行时属性、配置加载和多个生命周期默认入口。新增 Agent 能力要优先放到服务类或组合对象中，不要继续膨胀基类。

### P0：方向反转的对象关系

- `hydros_agent_sdk/agent_commands/transport/client.py` 已支持外部绑定 `AgentCommandRuntime`，生产路径由 `AgentCommandGateway` 组装 runtime 后注入 transport。旧版 `AgentCommandClient.runtime` 懒创建只作为兼容过渡，后续不能再依赖它扩展新功能。
- `hydros_agent_sdk/context_manager.py` 当前使用类级别状态管理上下文，容易形成隐式全局单例。后续新功能应通过实例化上下文仓储或 state manager 注入依赖，不再增加类级全局状态。

### P1：目录放置不合理

- SDK 包内不再允许放 `env.properties`。`load_env_config()` 默认从当前应用目录向上查找最近的 `env.properties`；环境配置只能放在示例、定制 Agent 目录或部署配置中。
- 泵站 MPC 回放/调试脚本已从 `custom-agent/pump/scheduling/test_mpc.py`、`custom-agent/pump/scheduling/test_mpc_debug.py` 迁移到 `tests/pump_mpc/`，生产调度目录不再放 `test_*.py` 调试脚本。
- `examples/logs/`、`__pycache__/`、`*.pyc`、`output/` 等运行产物不属于源码结构，不应作为开发依据，也不应进入提交。

### P1：业务算法和 Agent 生命周期耦合

- `custom-agent/pump/scheduling/`、`custom-agent/power/outflowplan/` 等业务目录中，Agent 类只负责生命周期适配，泵站、电站、出流、调度、MPC 等算法要封装成领域服务或求解器类。
- 示例代码可以为了演示保持轻量，但不能把长流程业务算法直接写进 `on_init()`、`on_tick()`、`on_outflow_time_series()` 等生命周期方法。

### 迁移要求

- 重构时先补兼容测试，再做小步迁移，避免一次性移动大量文件导致导入路径失控。
- 对外公共 API 需要保留旧入口时，可以增加薄 wrapper，但 wrapper 只能委托给新对象，不再承载新逻辑。
- 每迁移一个目录或核心类，都要同步更新 `__init__.py` 导出、测试导入路径和示例启动脚本。
- 不确定归属的类，先按“谁拥有状态、谁承担生命周期、谁依赖谁”判断；仍不清楚时宁可先放到更具体的子包，不放入根目录或 `utils/`。

## 开发命令

```bash
pip install -e .
python -m unittest discover -s tests
python -m unittest tests.test_agent_commands_refactor
python -m py_compile hydros_agent_sdk/**/*.py custom-agent/**/**/*.py
python -m build
```

运行示例前准备好对应目录下的 `env.properties` 和 `agent.properties`：

```bash
python -m hydros_agent_sdk.launcher --launcher-dir examples --project-root .
python custom-agent/pump/multi_agent_launcher.py
```

## 变更检查清单

- 新增功能是否已经建模为清晰对象，而不是散落函数和 dict。
- 新类是否放在正确目录，是否遵守依赖方向。
- 是否复用了现有基类、工厂、topic、错误处理、日志上下文和配置 loader。
- 是否避免硬编码 broker、cluster、node、topic、文件路径等环境值。
- 是否为协议、topic、命令运行时、Agent 生命周期或 MPC 行为补了测试。
- 是否运行了最小必要测试命令，并在 PR 或提交说明中记录。

## 提交与 PR

- 提交标题保持简短、单一主题，建议使用中文命令式摘要，例如 `智能体指令: 优化执行路由`。
- PR 说明应包含变更动机、影响目录、对象边界变化、执行过的测试命令和配置影响。
- 如果修改协议、topic、Agent 生命周期或错误响应，要明确说明对 Java 协调器和已有 Agent 的兼容性影响。
