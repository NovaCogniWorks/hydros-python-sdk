# 03 启动检查清单

## 1. 文档说明

本文是对外交付包中的启动检查清单，用于帮助外部团队在首次接入和联调前后快速排查常见问题。

说明：

- 本文属于执行侧自检和交付材料，不替代架构验证策略
- 验证分层与放行口径以上游 `architect_agent/outputs/python-sdk-verification-and-acceptance.md` 为准
- 本文只保留外部团队最常用的启动检查项和故障定位顺序

## 2. 启动前检查

- Python 版本不低于 `3.9`
- 已安装 `hydros-agent-sdk`
- `env.properties` 路径正确
- `agent.properties` 路径正确
- `agent_code`、`agent_type`、`agent_name` 均已填写
- MQTT 地址、端口、主题与中央环境一致
- 业务 Agent 类已继承正确 SDK 基类

## 3. 启动中检查

- 能成功导入 `hydros_agent_sdk`
- `SimCoordinationClient` 能正常启动
- 日志中能看到 MQTT 连接成功信息
- 日志中能看到主题订阅成功信息
- `MultiAgentCallback` 已注册目标 `agent_code`

## 4. 启动后检查

- 收到 `task_init_request` 后 Agent 能成功创建实例
- 收到 `tick_cmd_request` 后 Tick 逻辑能正常返回
- 收到 `task_terminate_request` 后能完成资源释放
- 事件驱动 Agent 能正确处理对应事件命令

## 5. 故障定位顺序

1. 先查配置文件
2. 再查 MQTT 连通性
3. 再查 `agent_code` 是否注册成功
4. 再查命令 `command_type` 是否与 SDK 模型一致
5. 最后查业务 Agent 自身逻辑异常

## 6. 关联说明

如需补齐联调字段样例和最终验收项，可参考：

- `04-joint-debug-command-examples.md`
- `05-delivery-acceptance-checklist.md`
