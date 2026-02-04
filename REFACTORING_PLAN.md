# Examples 代码重构优化方案

## 一、现状分析

### 1.1 代码重复问题

当前 `examples` 文件夹中存在与 `hydros_agent_sdk` 重复的基础代码：

**重复的基础代码：**

| examples 中的文件 | SDK 中的对应文件 | 重复内容 |
|------------------|-----------------|---------|
| `examples/agents/common.py` | `hydros_agent_sdk/factory.py` | `HydroAgentFactory`, `generate_agent_instance_id()` |
| `examples/agents/common.py` | `hydros_agent_sdk/multi_agent.py` | `MultiAgentCallback` |
| `examples/agents/common.py` | `hydros_agent_sdk/config_loader.py` | `load_env_config()`, `_load_properties_file()` |
| `examples/load_env.py` | `hydros_agent_sdk/config_loader.py` | `load_env_config()`, `_load_properties_file()` |

**代码对比：**
- `examples/agents/common.py` (509 行) 中约 400 行是基础框架代码
- `examples/load_env.py` (103 行) 完全是基础框架代码
- 这些代码与 SDK 中的实现几乎完全相同，造成维护负担

### 1.2 代码分类

#### ✅ 应该保留在 examples 的代码（业务逻辑 + 示例）

**业务逻辑代码（不同用户会有不同实现）：**
1. `examples/agents/ontology/ontology_rule_engine.py` (153 行)
   - 本体规则引擎的具体实现
   - 包含业务规则定义和推理逻辑
   - 用户需要根据自己的业务场景定制

2. `examples/agents/twins/hydraulic_solver.py` (104 行)
   - 水力求解器的具体实现
   - 包含水力计算的业务逻辑
   - 用户需要根据自己的模型定制

**示例代码（展示如何使用 SDK）：**
3. `examples/agents/ontology/ontology_agent.py` (329 行)
   - 展示如何继承 `OntologySimulationAgent` 实现具体智能体
   - 展示如何集成业务逻辑（规则引擎）
   - 包含完整的 main() 函数，可独立运行

4. `examples/agents/twins/twins_agent.py` (361 行)
   - 展示如何继承 `TwinsSimulationAgent` 实现具体智能体
   - 展示如何集成业务逻辑（水力求解器）
   - 包含完整的 main() 函数，可独立运行

5. `examples/simple_multi_agent_example.py` (150 行)
   - 展示如何使用 `MultiAgentCallback` 管理多个智能体
   - 简单清晰的示例代码

6. `examples/multi_agent_launcher.py` (413 行)
   - 实用工具：命令行启动器
   - 支持动态加载多个智能体
   - 支持调试模式

#### ❌ 应该删除的代码（已在 SDK 中实现）

1. `examples/agents/common.py` (509 行)
   - 其中约 400 行是基础框架代码，与 SDK 重复
   - 应该删除，改为从 SDK 导入

2. `examples/load_env.py` (103 行)
   - 完全是基础框架代码，与 SDK 重复
   - 应该删除，改为从 SDK 导入

## 二、优化方案

### 2.1 目标

1. **明确边界**：清晰区分基础代码（SDK）和业务代码（examples）
2. **消除重复**：删除 examples 中与 SDK 重复的基础代码
3. **简化维护**：开发者只需关注 examples 中的业务逻辑
4. **保持兼容**：确保现有示例代码正常运行

### 2.2 具体步骤

#### 步骤 1：删除重复的基础代码文件

```bash
# 删除重复的基础代码文件
rm examples/agents/common.py
rm examples/load_env.py
```

#### 步骤 2：更新所有 examples 中的导入语句

**需要更新的文件：**
1. `examples/simple_multi_agent_example.py`
2. `examples/multi_agent_launcher.py`
3. `examples/agents/ontology/ontology_agent.py`
4. `examples/agents/twins/twins_agent.py`

**导入语句变更：**

```python
# 旧的导入（从 examples 内部导入）
from examples.agents.common import HydroAgentFactory, MultiAgentCallback, load_env_config
from agents.common import HydroAgentFactory, MultiAgentCallback, load_env_config
from load_env import load_env_config

# 新的导入（从 SDK 导入）
from hydros_agent_sdk import (
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
)
```

#### 步骤 3：验证功能完整性

确保以下功能正常工作：
- ✅ 单个智能体独立运行（ontology_agent.py, twins_agent.py）
- ✅ 多智能体示例运行（simple_multi_agent_example.py）
- ✅ 多智能体启动器运行（multi_agent_launcher.py）
- ✅ 配置文件加载（agent.properties, env.properties）

### 2.3 重构后的目录结构

```
hydros-python-sdk/
├── hydros_agent_sdk/              # SDK 基础代码（不对开发者开放修改）
│   ├── __init__.py                # 导出所有公共 API
│   ├── factory.py                 # ✅ HydroAgentFactory, generate_agent_instance_id
│   ├── multi_agent.py             # ✅ MultiAgentCallback
│   ├── config_loader.py           # ✅ load_env_config, load_agent_config
│   ├── base_agent.py              # ✅ BaseHydroAgent
│   ├── coordination_client.py     # ✅ SimCoordinationClient
│   ├── agents/                    # ✅ 专用智能体基类
│   │   ├── tickable_agent.py
│   │   ├── ontology_simulation_agent.py
│   │   ├── twins_simulation_agent.py
│   │   └── ...
│   └── ...
│
├── examples/                      # 示例和业务逻辑（开发者可修改）
│   ├── env.properties             # 环境配置（MQTT、集群信息）
│   ├── simple_multi_agent_example.py  # ✅ 简单示例
│   ├── multi_agent_launcher.py    # ✅ 启动器工具
│   │
│   └── agents/                    # 具体智能体实现
│       ├── ontology/
│       │   ├── agent.properties   # 智能体配置
│       │   ├── ontology_agent.py  # ✅ 示例：如何实现本体智能体
│       │   └── ontology_rule_engine.py  # ✅ 业务逻辑：规则引擎
│       │
│       └── twins/
│           ├── agent.properties   # 智能体配置
│           ├── twins_agent.py     # ✅ 示例：如何实现孪生智能体
│           └── hydraulic_solver.py  # ✅ 业务逻辑：水力求解器
```

### 2.4 开发者工作流

**重构后，开发者只需关注 examples 目录：**

1. **使用现有智能体类型**：
   ```python
   from hydros_agent_sdk import (
       TwinsSimulationAgent,      # 从 SDK 导入基类
       HydroAgentFactory,         # 从 SDK 导入工厂
       MultiAgentCallback,        # 从 SDK 导入回调
       load_env_config,           # 从 SDK 导入配置加载
   )

   # 实现自己的业务逻辑
   class MyCustomAgent(TwinsSimulationAgent):
       def _initialize_twins_model(self):
           # 自定义初始化逻辑
           pass

       def _execute_twins_simulation(self, step):
           # 自定义仿真逻辑
           pass
   ```

2. **添加业务逻辑模块**：
   - 在 `examples/agents/` 下创建新的业务逻辑模块
   - 例如：`my_solver.py`, `my_rule_engine.py`
   - 这些模块包含具体的计算逻辑、规则定义等

3. **配置和运行**：
   - 修改 `agent.properties` 配置智能体元数据
   - 修改 `env.properties` 配置 MQTT 连接
   - 运行示例或使用启动器

## 三、优势分析

### 3.1 清晰的职责边界

| 层次 | 内容 | 修改权限 | 打包方式 |
|-----|------|---------|---------|
| **hydros_agent_sdk** | 基础框架代码 | ❌ 不允许修改 | pip 包 |
| **examples** | 业务逻辑 + 示例 | ✅ 允许修改 | 源代码 |

### 3.2 降低维护成本

**重构前：**
- 基础代码分散在 SDK 和 examples 中
- 修改基础功能需要同步更新多处
- 容易出现版本不一致问题

**重构后：**
- 基础代码只在 SDK 中维护
- 修改基础功能只需更新 SDK
- examples 自动获得最新功能

### 3.3 简化开发者体验

**重构前：**
- 开发者需要理解 `examples/agents/common.py` 中的复杂代码
- 不清楚哪些代码可以修改，哪些不能修改
- 容易误改基础代码导致问题

**重构后：**
- 开发者只需关注 examples 中的业务逻辑
- 从 SDK 导入的代码不需要理解实现细节
- 清晰的边界：SDK = 框架，examples = 业务

### 3.4 便于版本管理

**重构后：**
- SDK 可以独立发布版本（pip install hydros-agent-sdk==0.1.4）
- examples 作为示例代码，跟随项目仓库
- 开发者可以基于稳定的 SDK 版本开发

## 四、风险评估

### 4.1 潜在风险

1. **导入路径变更**：需要更新所有 examples 中的导入语句
2. **功能差异**：需要确认 SDK 中的实现与 examples 中的实现完全一致
3. **测试覆盖**：需要测试所有示例确保正常运行

### 4.2 缓解措施

1. **逐步迁移**：先更新一个示例，验证通过后再更新其他
2. **保留备份**：在删除前备份 `common.py` 和 `load_env.py`
3. **完整测试**：运行所有示例确保功能正常

## 五、实施计划

### 阶段 1：准备（已完成）
- ✅ 分析 examples 中的代码
- ✅ 识别重复的基础代码
- ✅ 确认 SDK 中已有对应实现
- ✅ 制定重构方案

### 阶段 2：代码重构（待执行）
1. 备份重复的文件
2. 更新 `simple_multi_agent_example.py` 的导入
3. 更新 `multi_agent_launcher.py` 的导入
4. 更新 `ontology_agent.py` 的导入
5. 更新 `twins_agent.py` 的导入
6. 删除 `examples/agents/common.py`
7. 删除 `examples/load_env.py`

### 阶段 3：测试验证（待执行）
1. 测试 `simple_multi_agent_example.py`
2. 测试 `multi_agent_launcher.py`
3. 测试 `ontology_agent.py` 独立运行
4. 测试 `twins_agent.py` 独立运行
5. 验证配置文件加载
6. 验证多智能体协调

### 阶段 4：文档更新（待执行）
1. 更新 README.md
2. 更新 CLAUDE.md
3. 添加开发者指南
4. 更新示例说明

## 六、总结

### 6.1 核心原则

**基础代码下沉到 SDK：**
- `HydroAgentFactory` - 智能体工厂
- `MultiAgentCallback` - 多智能体回调管理
- `generate_agent_instance_id()` - ID 生成
- `load_env_config()` - 环境配置加载
- `load_agent_config()` - 智能体配置加载

**业务逻辑保留在 examples：**
- `ontology_rule_engine.py` - 本体规则引擎（业务逻辑）
- `hydraulic_solver.py` - 水力求解器（业务逻辑）
- `ontology_agent.py` - 本体智能体实现示例
- `twins_agent.py` - 孪生智能体实现示例
- `multi_agent_launcher.py` - 启动器工具

### 6.2 预期效果

1. **代码更清晰**：明确区分框架代码和业务代码
2. **维护更简单**：基础代码只在一处维护
3. **开发更聚焦**：开发者只需关注业务逻辑
4. **版本更规范**：SDK 可以独立发布和管理

### 6.3 下一步行动

**请确认以上方案后，我将执行以下操作：**
1. 更新所有 examples 中的导入语句
2. 删除重复的基础代码文件
3. 运行测试验证功能正常
4. 更新相关文档

---

**方案制定时间**：2026-02-04
**方案版本**：v1.0
