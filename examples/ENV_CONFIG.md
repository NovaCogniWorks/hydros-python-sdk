# Environment Configuration Guide

本文档说明如何配置 `env.properties` 文件来设置 MQTT broker 连接参数。

## 配置文件位置

默认位置：
```
examples/env.properties
```

## 配置属性

### 必需属性

| 属性 | 说明 | 示例 |
|------|------|------|
| `mqtt_broker_url` | MQTT Broker 地址 | `tcp://192.168.1.24` 或 `ssl://broker.example.com` |
| `mqtt_broker_port` | MQTT Broker 端口 | `1883` (标准) 或 `8883` (SSL) |
| `mqtt_topic` | MQTT 主题 | `/hydros/commands/coordination/your_topic` |

## 配置示例

### 标准 TCP 连接

```properties
# MQTT Broker Configuration
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/weijiahao
```

### SSL/TLS 连接

```properties
# MQTT Broker Configuration (SSL)
mqtt_broker_url=ssl://broker.example.com
mqtt_broker_port=8883
mqtt_topic=/hydros/commands/coordination/secure_topic
```

### 本地开发

```properties
# MQTT Broker Configuration (Local)
mqtt_broker_url=tcp://localhost
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/dev
```

## 配置说明

### mqtt_broker_url

MQTT Broker 的连接地址。

**格式：**
- TCP 连接：`tcp://hostname` 或 `tcp://ip_address`
- SSL 连接：`ssl://hostname`

**示例：**
```properties
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_url=tcp://mqtt.example.com
mqtt_broker_url=ssl://secure-mqtt.example.com
```

### mqtt_broker_port

MQTT Broker 的端口号。

**常用端口：**
- `1883` - 标准 MQTT 端口（无加密）
- `8883` - MQTT over SSL/TLS 端口（加密）
- `9001` - MQTT over WebSocket 端口

**示例：**
```properties
mqtt_broker_port=1883
mqtt_broker_port=8883
```

### mqtt_topic

MQTT 主题，用于订阅和发布消息。

**格式：**
- 必须以 `/` 开头
- 使用 `/` 分隔层级
- 建议使用有意义的命名

**示例：**
```properties
mqtt_topic=/hydros/commands/coordination/weijiahao
mqtt_topic=/hydros/commands/coordination/production
mqtt_topic=/hydros/commands/coordination/test
```

## 验证配置

运行验证脚本检查配置是否正确：

```bash
python3 examples/test_env.py
```

**输出示例：**
```
======================================================================
Environment Configuration Validation
======================================================================
✓ Config file found: examples/env.properties
✓ Config file parsed successfully

Configuration Values:
----------------------------------------------------------------------
✓ mqtt_broker_url           = tcp://192.168.1.24
✓ mqtt_broker_port          = 1883
✓ mqtt_topic                = /hydros/commands/coordination/weijiahao
----------------------------------------------------------------------

✓ All required MQTT configuration properties are present

Validation:
----------------------------------------------------------------------
✓ Broker URL format is valid: tcp://192.168.1.24
✓ Broker port is valid: 1883
✓ Topic format is valid: /hydros/commands/coordination/weijiahao
----------------------------------------------------------------------

======================================================================
✓ Environment configuration is valid
======================================================================
```

## 多环境配置

### 开发环境

创建 `env.dev.properties`：
```properties
mqtt_broker_url=tcp://localhost
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/dev
```

### 测试环境

创建 `env.staging.properties`：
```properties
mqtt_broker_url=tcp://test-broker.example.com
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/staging
```

### 生产环境

创建 `env.prod.properties`：
```properties
mqtt_broker_url=ssl://prod-broker.example.com
mqtt_broker_port=8883
mqtt_topic=/hydros/commands/coordination/production
```

### 使用不同环境配置

修改 `agent_example.py` 中的环境文件路径：

```python
import os

# 从环境变量获取环境名称
env = os.getenv('ENV', 'dev')
ENV_FILE = f"examples/env.{env}.properties"

env_config = load_env_config(ENV_FILE)
```

运行时指定环境：
```bash
ENV=dev python3 examples/agent_example.py
ENV=staging python3 examples/agent_example.py
ENV=prod python3 examples/agent_example.py
```

## 安全建议

### 1. 不要提交敏感信息

如果配置文件包含敏感信息（如生产环境地址），添加到 `.gitignore`：

```bash
# .gitignore
examples/env.prod.properties
examples/env.*.properties
```

### 2. 使用环境变量

对于敏感配置，可以使用环境变量：

```python
import os

# 从环境变量读取
BROKER_URL = os.getenv('MQTT_BROKER_URL', 'tcp://localhost')
BROKER_PORT = int(os.getenv('MQTT_BROKER_PORT', '1883'))
TOPIC = os.getenv('MQTT_TOPIC', '/hydros/commands/coordination/default')
```

### 3. 使用 SSL/TLS

生产环境建议使用 SSL/TLS 加密连接：

```properties
mqtt_broker_url=ssl://secure-broker.example.com
mqtt_broker_port=8883
```

## 故障排查

### 问题 1: 配置文件找不到

```
FileNotFoundError: Environment config file not found: examples/env.properties
```

**解决方案：**
- 检查文件路径是否正确
- 确保从项目根目录运行脚本
- 使用绝对路径

### 问题 2: 缺少必需配置

```
ValueError: Missing required properties in env.properties: mqtt_broker_url
```

**解决方案：**
- 运行 `python3 examples/test_env.py` 检查配置
- 确保所有必需属性都已定义
- 检查属性名称拼写

### 问题 3: 端口格式错误

```
ValueError: invalid literal for int() with base 10: 'abc'
```

**解决方案：**
- 确保 `mqtt_broker_port` 是有效的整数
- 端口范围：1-65535

### 问题 4: 连接失败

```
Connection refused
```

**解决方案：**
- 检查 MQTT broker 是否运行
- 检查网络连接
- 检查防火墙设置
- 验证 broker 地址和端口

## 配置模板

### 基础模板

```properties
# MQTT Broker Configuration
# This file contains the MQTT broker connection settings

# MQTT Broker URL (tcp:// or ssl://)
mqtt_broker_url=tcp://your-broker-address

# MQTT Broker Port
mqtt_broker_port=1883

# MQTT Topic for coordination commands
mqtt_topic=/hydros/commands/coordination/your_topic
```

### 完整模板（带注释）

```properties
# ============================================================================
# MQTT Broker Configuration
# ============================================================================
# This file contains the MQTT broker connection settings for the Hydro Agent.
#
# Required Properties:
#   - mqtt_broker_url: MQTT broker address (tcp:// or ssl://)
#   - mqtt_broker_port: MQTT broker port (1883 for TCP, 8883 for SSL)
#   - mqtt_topic: MQTT topic for coordination commands
#
# Usage:
#   python3 examples/agent_example.py
#
# Validation:
#   python3 examples/test_env.py
# ============================================================================

# MQTT Broker URL
# Format: tcp://hostname or ssl://hostname
# Examples:
#   tcp://192.168.1.24
#   tcp://mqtt.example.com
#   ssl://secure-mqtt.example.com
mqtt_broker_url=tcp://192.168.1.24

# MQTT Broker Port
# Common ports:
#   1883 - Standard MQTT (no encryption)
#   8883 - MQTT over SSL/TLS (encrypted)
#   9001 - MQTT over WebSocket
mqtt_broker_port=1883

# MQTT Topic
# Format: /path/to/topic
# Must start with /
# Use meaningful naming convention
# Examples:
#   /hydros/commands/coordination/production
#   /hydros/commands/coordination/test
#   /hydros/commands/coordination/dev
mqtt_topic=/hydros/commands/coordination/weijiahao
```

## 与 agent.properties 的关系

系统使用两个配置文件：

1. **env.properties** - 环境配置（MQTT 连接）
   - MQTT broker 地址
   - MQTT broker 端口
   - MQTT 主题

2. **agent.properties** - Agent 配置（业务属性）
   - Agent 代码和类型
   - Agent 名称
   - 配置 URL
   - 驱动模式

**分离的好处：**
- 环境配置可以在不同环境间切换
- Agent 配置保持稳定
- 便于管理和维护

## 相关文档

- [AGENT_CONFIG.md](AGENT_CONFIG.md) - Agent 配置说明
- [QUICKSTART.md](QUICKSTART.md) - 快速开始指南
- [README.md](README.md) - 总览

## 获取帮助

如果遇到问题：

1. 运行验证脚本：`python3 examples/test_env.py`
2. 检查配置文件格式
3. 查看错误日志
4. 参考本文档的故障排查部分
