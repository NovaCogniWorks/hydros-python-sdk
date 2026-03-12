# Hydros Agent SDK 文档中心

欢迎使用 Hydros Agent SDK！本文档中心提供了完整的开发指南、参考文档和示例代码。

---

## 📚 文档导航

### 🎓 新手入门

1. **[新手智能体开发指南](./新手智能体开发指南.md)** ⭐ 推荐首先阅读
   - 完整的开发流程
   - 详细的代码示例
   - 最佳实践和技巧
   - 适合零基础开发者

2. **[快速参考](./快速参考.md)**
   - 常用 API 速查
   - 代码片段集合
   - 配置模板
   - 适合快速查找

3. **[模板项目](../examples/template_agent/)**
   - 可直接使用的项目模板
   - 包含完整的配置和代码
   - 复制即用，快速上手

---

### 🔧 进阶开发

4. **[智能体类型对比](./智能体类型对比.md)**
   - 各种智能体类型详解
   - 适用场景分析
   - 性能和复杂度对比
   - 帮助选择合适的基类

5. **[错误处理指南](./ERROR_HANDLING.md)**
   - 完整的错误处理机制
   - 错误码定义
   - 最佳实践
   - 示例代码

6. **[故障排查指南](./故障排查指南.md)**
   - 常见问题诊断
   - 解决方案
   - 调试技巧
   - 性能优化

---

### 📖 参考文档

7. **[API 参考](../hydros_agent_sdk/)**
   - SDK 源码和注释
   - 详细的 API 文档
   - 类和方法说明

8. **[协议定义](../hydros_agent_sdk/protocol/)**
   - 通信协议模型
   - 命令和响应格式
   - 事件定义

---

## 🚀 快速开始

### 5 分钟快速上手

```bash
# 1. 复制模板项目
cp -r examples/template_agent my_agent
cd my_agent

# 2. 修改配置
# 编辑 agent.properties 和 env.properties

# 3. 运行智能体
python run.py
```

### 学习路径

```
第 1 步: 阅读《新手智能体开发指南》
   ↓
第 2 步: 复制并运行模板项目
   ↓
第 3 步: 查看示例代码（twins/ontology）
   ↓
第 4 步: 实现自己的业务逻辑
   ↓
第 5 步: 参考《快速参考》和《故障排查指南》
```

---

## 📂 示例代码

### 完整示例

- **[模板智能体](../examples/template_agent/)** - 通用模板，适合所有场景
- **[孪生仿真智能体](../examples/agents/twins/)** - 高精度水力仿真
- **[本体仿真智能体](../examples/agents/ontology/)** - 基于规则的推理
- **[中央调度智能体](../examples/agents/centralscheduling/)** - MPC 优化调度

### 代码片段

```python
# 最简单的智能体实现
from hydros_agent_sdk.agents import TickableAgent

class MyAgent(TickableAgent):
    def on_init(self, request):
        self.load_agent_configuration(request)
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)
        return SimTaskInitResponse(...)

    def on_tick_simulation(self, request):
        # 你的仿真逻辑
        return []

    def on_terminate(self, request):
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)
        return SimTaskTerminateResponse(...)
```

---

## 🎯 按场景查找

### 我想...

- **学习如何开发智能体** → [新手智能体开发指南](./新手智能体开发指南.md)
- **快速查找 API** → [快速参考](./快速参考.md)
- **选择智能体类型** → [智能体类型对比](./智能体类型对比.md)
- **解决问题** → [故障排查指南](./故障排查指南.md)
- **处理错误** → [错误处理指南](./ERROR_HANDLING.md)
- **查看示例** → [examples/](../examples/)

### 我遇到了...

- **连接问题** → [故障排查指南 - 连接问题](./故障排查指南.md#连接问题)
- **初始化失败** → [故障排查指南 - 初始化问题](./故障排查指南.md#初始化问题)
- **配置错误** → [故障排查指南 - 配置问题](./故障排查指南.md#配置问题)
- **性能问题** → [故障排查指南 - 性能问题](./故障排查指南.md#性能问题)
- **拓扑加载失败** → [故障排查指南 - 拓扑加载问题](./故障排查指南.md#拓扑加载问题)

---

## 📊 文档结构

```
docs/
├── README.md                      # 本文件 - 文档导航
├── 新手智能体开发指南.md          # 完整开发指南
├── 快速参考.md                    # API 速查手册
├── 智能体类型对比.md              # 类型选择指南
├── 故障排查指南.md                # 问题诊断和解决
└── ERROR_HANDLING.md              # 错误处理详解

examples/
├── template_agent/                # 模板项目
│   ├── README.md                  # 模板使用说明
│   ├── template_agent.py          # 智能体实现
│   ├── run.py                     # 启动脚本
│   ├── agent.properties           # 智能体配置
│   └── env.properties             # 环境配置
├── agents/
│   ├── twins/                     # 孪生仿真示例
│   ├── ontology/                  # 本体仿真示例
│   └── centralscheduling/         # 中央调度示例
└── error_handling_example.py      # 错误处理示例

hydros_agent_sdk/
├── __init__.py                    # SDK 入口
├── base_agent.py                  # 基础智能体类
├── agents/                        # 专门智能体类型
├── protocol/                      # 协议定义
└── utils/                         # 工具类
```

---

## 🔍 常见问题 FAQ

### Q1: 我应该从哪里开始？

**A**: 按以下顺序学习：
1. 阅读《新手智能体开发指南》前 3 章
2. 复制 `template_agent` 并运行
3. 查看 `twins` 或 `ontology` 示例
4. 实现自己的业务逻辑

### Q2: 如何选择智能体类型？

**A**: 参考《智能体类型对比》文档，或使用决策树：
- 不确定 → `TickableAgent`（最灵活）
- 高精度仿真 → `TwinsSimulationAgent`
- 规则推理 → `OntologySimulationAgent`
- 全局优化 → `CentralSchedulingAgent`

### Q3: 遇到错误怎么办？

**A**: 按以下步骤排查：
1. 查看日志文件 `logs/hydros.log`
2. 启用 DEBUG 日志级别
3. 参考《故障排查指南》对应章节
4. 查看《错误处理指南》了解错误码含义

### Q4: 如何调试智能体？

**A**: 使用以下方法：
```python
# 1. 启用详细日志
setup_logging(level=logging.DEBUG, console=True)

# 2. 添加调试日志
logger.debug(f"变量值: {my_var}")

# 3. 使用 Python 调试器
import pdb; pdb.set_trace()
```

### Q5: 如何优化性能？

**A**: 参考《故障排查指南 - 性能问题》，常用方法：
- 使用缓存 `@lru_cache`
- 批量处理数据
- 避免重复计算
- 使用生成器

---

## 💡 最佳实践

### 开发流程

1. **规划阶段**
   - 明确仿真需求
   - 选择合适的智能体类型
   - 设计数据流和接口

2. **开发阶段**
   - 从模板开始
   - 逐步实现功能
   - 添加错误处理
   - 编写日志

3. **测试阶段**
   - 单元测试
   - 集成测试
   - 性能测试
   - 边界条件测试

4. **部署阶段**
   - 配置生产环境
   - 监控日志
   - 性能调优
   - 文档更新

### 代码规范

```python
# 1. 使用类型注解
def on_tick_simulation(self, request: TickCmdRequest) -> List[MqttMetrics]:
    pass

# 2. 添加文档字符串
def _execute_simulation(self, step: int) -> Dict:
    """
    执行仿真计算

    Args:
        step: 当前仿真步

    Returns:
        仿真结果字典
    """
    pass

# 3. 使用错误处理
@handle_agent_errors(ErrorCodes.AGENT_TICK_FAILURE)
def on_tick_simulation(self, request):
    pass

# 4. 添加日志
logger.info(f"开始执行: step={step}")
logger.debug(f"详细信息: {details}")
logger.error(f"错误: {error}", exc_info=True)
```

---

## 🛠️ 开发工具

### 推荐工具

- **IDE**: PyCharm, VS Code
- **调试**: Python Debugger, IPython
- **MQTT 客户端**: MQTT Explorer, mosquitto_sub/pub
- **日志查看**: tail, less, grep
- **性能分析**: cProfile, memory_profiler

### 有用的命令

```bash
# 查看日志
tail -f logs/hydros.log

# 监听 MQTT 消息
mosquitto_sub -h 192.168.1.24 -t "#" -v

# 测试 MQTT 连接
mosquitto_pub -h 192.168.1.24 -t "test" -m "hello"

# 查看进程
ps aux | grep python

# 查看端口占用
netstat -an | grep 1883
```

---

## 📞 获取帮助

### 文档资源

- **本地文档**: `docs/` 目录
- **示例代码**: `examples/` 目录
- **源码注释**: `hydros_agent_sdk/` 目录

### 社区支持

- **GitHub Issues**: 报告问题和建议
- **技术文档**: 查看最新文档
- **示例项目**: 参考实际应用

---

## 🔄 文档更新

本文档持续更新中，最后更新时间：2024-01

### 版本历史

- **v1.0** (2024-01): 初始版本
  - 新手智能体开发指南
  - 快速参考手册
  - 智能体类型对比
  - 故障排查指南
  - 模板项目

---

## 📝 贡献文档

欢迎贡献文档改进！

1. Fork 项目
2. 创建文档分支
3. 提交改进
4. 发起 Pull Request

---

**祝你开发顺利！** 🚀

如有问题，请参考对应的文档章节，或查看示例代码。
