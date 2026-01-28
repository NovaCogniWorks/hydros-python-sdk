# Hydros Python SDK - 文档索引

## 📚 文档概览

本项目包含以下文档，帮助你理解和使用重构后的代码。

---

## 🚀 快速开始

### 1. [QUICKSTART.md](QUICKSTART.md) - 快速开始指南
**适合：** 想要快速上手的开发者

**内容：**
- ✅ 重构完成确认
- 📝 使用示例代码
- 🔍 常见问题解答
- 🎯 下一步操作

**何时阅读：** 重构完成后，想要立即开始使用新 API

---

## 📖 核心文档

### 2. [README.md](README.md) - 项目说明
**适合：** 所有用户

**内容：**
- 项目介绍
- 安装说明
- 基础使用示例
- MQTT 客户端使用

**何时阅读：** 首次接触项目时

---

### 3. [MIGRATION_NOTES.md](MIGRATION_NOTES.md) - 迁移指南
**适合：** 需要更新现有代码的开发者

**内容：**
- 📋 完整的字段名变更列表
- 🔄 迁移步骤
- 💡 代码示例对比
- ⚠️ 注意事项

**何时阅读：** 需要将旧代码迁移到新版本时

**关键信息：**
```python
# 旧代码
context.bizSceneInstanceId
agent.agentCode
response.commandStatus = "SUCCEED"

# 新代码
context.biz_scene_instance_id
agent.agent_code
response.command_status = CommandStatus.SUCCEED
```

---

### 4. [REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md) - 重构总结
**适合：** 想要了解重构细节的开发者和维护者

**内容：**
- ✅ 已完成的工作清单
- 📊 测试结果
- 📁 新增文件列表
- 🔄 Git 提交信息
- 💡 关键变更示例
- ✨ 重构带来的好处

**何时阅读：** 想要全面了解重构内容和影响时

---

### 5. [TESTING_GUIDE.md](TESTING_GUIDE.md) - 测试指南
**适合：** 需要验证代码的开发者和测试人员

**内容：**
- 🧪 4 种测试方法
- 📝 详细的测试步骤
- 🔍 故障排查指南
- ✅ 成功标志
- 📊 测试检查清单

**何时阅读：** 需要验证重构是否成功，或者遇到问题时

**测试方法：**
1. 本地验证测试（推荐）
2. MQTT 集成测试
3. 实际 MQTT Broker 测试
4. 使用 MQTT 客户端工具

---

## 🧪 测试文件

### 6. tests/verify_refactoring.py - 完整验证脚本
**用途：** 一键验证所有重构是否成功

**运行：**
```bash
python tests/verify_refactoring.py
```

**测试内容：**
- ✓ 导入测试
- ✓ CommandStatus 枚举
- ✓ snake_case 字段
- ✓ JSON 序列化
- ✓ MQTT 消息解析
- ✓ 响应创建
- ✓ 所有命令类型

---

### 7. tests/test_mqtt_integration.py - MQTT 集成测试
**用途：** 测试实际 MQTT 消息解析

**运行：**
```bash
python tests/test_mqtt_integration.py
```

**测试内容：**
- MQTT payload 解析
- CommandStatus 枚举使用
- JSON 序列化/反序列化

---

### 8. tests/test_protocol_commands.py - 协议测试
**用途：** 测试协议命令的序列化和反序列化

**运行：**
```bash
python tests/test_protocol_commands.py
```

---

### 9. tests/manual_mqtt_stub.py - MQTT 测试桩
**用途：** 模拟 MQTT 客户端，接收和处理消息

**运行：**
```bash
python tests/manual_mqtt_stub.py
```

**配置：**
- Broker: 192.168.1.24:1883
- Topic: /hydros/commands/coordination/weijiahao

---

### 10. tests/send_test_message.py - 测试消息发送器
**用途：** 发送测试消息到 MQTT broker

**运行：**
```bash
python tests/send_test_message.py
```

---

## 📋 文档阅读顺序建议

### 场景 1: 首次使用项目
1. README.md - 了解项目
2. QUICKSTART.md - 快速上手
3. TESTING_GUIDE.md - 验证安装

### 场景 2: 迁移现有代码
1. MIGRATION_NOTES.md - 了解变更
2. QUICKSTART.md - 查看新 API 示例
3. TESTING_GUIDE.md - 测试迁移结果

### 场景 3: 了解重构细节
1. REFACTORING_SUMMARY.md - 重构概览
2. MIGRATION_NOTES.md - 详细变更
3. TESTING_GUIDE.md - 验证方法

### 场景 4: 遇到问题
1. TESTING_GUIDE.md - 故障排查
2. QUICKSTART.md - 常见问题
3. MIGRATION_NOTES.md - 检查迁移

---

## 🔑 关键概念速查

### 字段命名规范
- **旧规范**: camelCase (例如: `bizSceneInstanceId`)
- **新规范**: snake_case (例如: `biz_scene_instance_id`)

### CommandStatus 枚举
```python
from hydros_agent_sdk.protocol.models import CommandStatus

# 4 个状态
CommandStatus.INIT
CommandStatus.PROCESSING
CommandStatus.SUCCEED
CommandStatus.FAILED
```

### HydroAgentInstance 必需字段
```python
HydroAgentInstance(
    agent_id="...",
    agent_code="...",
    agent_type="...",
    agent_configuration_url="...",
    biz_scene_instance_id="...",
    hydros_cluster_id="...",
    hydros_node_id="...",
    context=...
)
```

### JSON 序列化
```python
# 始终使用 by_alias=True
json_str = command.model_dump_json(by_alias=True)
```

---

## 📊 重构统计

- **修改文件**: 7 个
- **新增文件**: 4 个
- **字段变更**: 40+ 个
- **代码变更**: 1142 insertions, 89 deletions
- **测试通过**: 7/7 (100%)
- **Git Commit**: eceac59

---

## ✅ 验证清单

使用此清单确认重构成功：

- [ ] 阅读 QUICKSTART.md
- [ ] 运行 `python tests/verify_refactoring.py`
- [ ] 运行 `python tests/test_mqtt_integration.py`
- [ ] 运行 `python tests/test_protocol_commands.py`
- [ ] 查看 MIGRATION_NOTES.md
- [ ] 更新应用代码（如果需要）
- [ ] 测试 MQTT stub（如果有 broker）

---

## 🎯 快速命令参考

```bash
# 验证重构
python tests/verify_refactoring.py

# MQTT 集成测试
python tests/test_mqtt_integration.py

# 协议测试
python tests/test_protocol_commands.py

# 启动 MQTT stub
python tests/manual_mqtt_stub.py

# 发送测试消息
python tests/send_test_message.py

# 查看 Git 提交
git log --oneline -1

# 查看文件变更
git diff --stat HEAD~1
```

---

## 📞 获取帮助

如果遇到问题：

1. **查看文档**
   - TESTING_GUIDE.md 的故障排查部分
   - QUICKSTART.md 的常见问题部分

2. **运行诊断**
   ```bash
   python tests/verify_refactoring.py
   ```

3. **检查 Git 状态**
   ```bash
   git log --oneline -1
   # 应该显示: eceac59 Refactor: Unify field naming...
   ```

---

**文档版本**: 1.0
**最后更新**: 2026-01-28
**Git Commit**: eceac59
