# 测试指南

## 🧪 如何测试重构后的代码

重构已完成，现在需要验证 MQTT stub 是否能正常工作。

### 方法 1: 本地验证测试（推荐先运行）

这个测试不需要 MQTT broker，直接验证代码逻辑：

```bash
python tests/verify_refactoring.py
```

**预期结果：**
```
🎉 所有测试通过！重构成功完成！
```

### 方法 2: MQTT 集成测试

测试 MQTT 消息解析（不需要实际的 broker）：

```bash
python tests/test_mqtt_integration.py
```

**预期结果：**
```
✓ MQTT 消息解析成功
✓ All integration tests passed!
```

### 方法 3: 实际 MQTT Broker 测试

如果你有可用的 MQTT broker，可以进行完整的端到端测试。

#### 步骤 1: 启动 MQTT Stub

在**第一个终端**运行：

```bash
python tests/manual_mqtt_stub.py
```

**预期输出：**
```
INFO - Registered handler for command type: task_init_request
INFO - Registered handler for command type: tick_cmd_request
INFO - Connecting to MQTT broker at 192.168.1.24:1883
INFO - Connected to MQTT broker successfully
INFO - Subscribing to topic: /hydros/commands/coordination/weijiahao
INFO - Stub started. Listening on /hydros/commands/coordination/weijiahao...
```

#### 步骤 2: 发送测试消息

在**第二个终端**运行：

```bash
python tests/send_test_message.py
```

这个脚本会：
1. 连接到 MQTT broker
2. 发送一条测试消息（使用实际的 MQTT 消息格式）
3. 等待响应

#### 步骤 3: 检查结果

在**第一个终端**（manual_mqtt_stub.py）应该看到：

```
INFO - Received payload: {"context":...}
INFO - Dispatching command task_init_request to handler
INFO - Handling SimTaskInitRequest: SIMCMD202601281447AQSXQJFIPTWY
INFO - Sending response...
INFO - Publishing to /hydros/commands/coordination/weijiahao: {...}
```

**关键点：**
- ✅ **没有** "Validation error" 错误
- ✅ 成功解析命令
- ✅ 成功创建响应
- ✅ 成功发送响应

### 方法 4: 使用 MQTT 客户端工具

如果你有 MQTT 客户端工具（如 MQTT Explorer, mosquitto_pub），可以手动发送消息。

#### 使用 mosquitto_pub

```bash
mosquitto_pub -h 192.168.1.24 -p 1883 \
  -t "/hydros/commands/coordination/weijiahao" \
  -m '{
    "context": {
      "biz_scene_instance_id": "TEST_SCENE_001",
      "task_id": null
    },
    "agent_list": [{
      "agent_code": "TEST_AGENT",
      "agent_type": "TEST_TYPE",
      "agent_name": "测试代理",
      "agent_configuration_url": "http://test.url/config.yaml"
    }],
    "command_id": "TEST_CMD_001",
    "broadcast": true,
    "biz_scene_configuration_url": "http://test.url/config",
    "command_type": "task_init_request"
  }'
```

## 🔍 故障排查

### 问题 1: 连接 MQTT broker 失败

**错误：**
```
ConnectionRefusedError
```

**解决方案：**
1. 检查 MQTT broker 是否运行：
   ```bash
   # 如果使用 mosquitto
   sudo systemctl status mosquitto
   ```

2. 检查 broker 地址和端口：
   - 编辑 `tests/manual_mqtt_stub.py`
   - 修改 `BROKER_URL` 和 `BROKER_PORT`

3. 测试连接：
   ```bash
   mosquitto_sub -h 192.168.1.24 -p 1883 -t "test"
   ```

### 问题 2: 仍然出现验证错误

**错误：**
```
ValidationError: Field required
```

**解决方案：**
1. 确认你已经拉取了最新的代码：
   ```bash
   git log --oneline -1
   # 应该显示: eceac59 Refactor: Unify field naming...
   ```

2. 重新运行验证测试：
   ```bash
   python tests/verify_refactoring.py
   ```

3. 检查 MQTT 消息格式是否使用 snake_case

### 问题 3: 导入错误

**错误：**
```
ImportError: cannot import name 'CommandStatus'
```

**解决方案：**
1. 确认你在正确的虚拟环境中：
   ```bash
   which python
   # 应该显示 .venv 路径
   ```

2. 重新安装依赖：
   ```bash
   pip install -e .
   ```

## ✅ 成功标志

测试成功的标志：

1. **验证测试通过**
   ```
   ✓ 7/7 测试通过
   ```

2. **MQTT 消息解析成功**
   ```
   ✓ Successfully parsed command!
   ```

3. **没有验证错误**
   - 不再出现 "Field required" 错误
   - 不再出现 "agent_code" 等字段缺失的错误

4. **响应创建成功**
   ```
   ✓ 响应创建成功
   Command Status: SUCCEED
   ```

## 📊 测试检查清单

- [ ] 运行 `python tests/verify_refactoring.py` - 全部通过
- [ ] 运行 `python tests/test_mqtt_integration.py` - 全部通过
- [ ] 运行 `python tests/test_protocol_commands.py` - 全部通过
- [ ] 启动 `manual_mqtt_stub.py` - 无错误
- [ ] 发送测试消息 - 成功解析
- [ ] 检查响应 - 格式正确

## 🎯 下一步

测试通过后：

1. **更新你的应用代码**
   - 参考 `MIGRATION_NOTES.md`
   - 将所有 camelCase 改为 snake_case

2. **提交更改**（如果需要）
   ```bash
   git push origin main
   ```

3. **部署新版本**
   - 更新版本号
   - 发布到 PyPI（如果适用）

## 📞 需要帮助？

如果遇到问题：

1. 查看 `MIGRATION_NOTES.md` - 详细的迁移指南
2. 查看 `QUICKSTART.md` - 快速开始指南
3. 查看 `REFACTORING_SUMMARY.md` - 完整的重构总结
4. 运行 `python tests/verify_refactoring.py` - 诊断问题

---

**重构完成时间**: 2026-01-28
**Git Commit**: eceac59
**测试状态**: ✅ 所有测试通过 (7/7)
