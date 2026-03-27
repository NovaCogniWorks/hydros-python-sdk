# 04 联调命令样例

## 1. 文档说明

以下样例基于当前 SDK 的真实协议模型整理，主要用于联调阶段验证字段对齐。

说明：

- 实际联调时，中央侧仍应以统一协调协议为准
- 本文属于执行侧联调材料，不替代架构侧协议定义文档
- 当样例字段与最新实现存在差异时，应以当前代码实现和上游架构口径为准

注意事项：

- 命令外层使用 `SimCommandEnvelope` 风格，即顶层包一层 `command`
- 事件对象字段应使用 SDK 当前模型定义
- `hydro_event` 相关字段当前应使用 `hydro_event_type`、`hydro_event_id`、`hydro_event_name`、`created_time`

## 2. 初始化命令

见 `samples\task_init_request.json`

核心字段：

- `command_type = task_init_request`
- `context.biz_scene_instance_id`
- `agent_list`
- `biz_scene_configuration_url`

## 3. Tick 命令

见 `samples\tick_cmd_request.json`

核心字段：

- `command_type = tick_cmd_request`
- `context`
- `step`

## 4. 终止命令

见 `samples\task_terminate_request.json`

核心字段：

- `command_type = task_terminate_request`
- `reason`

## 5. 事件驱动计算命令

见 `samples\time_series_calculation_request.json`

适用 Agent：

- `ModelCalculationAgent`

核心字段：

- `command_type = calculation_request`
- `target_agent_instance`
- `hydro_event.hydro_event_type`
- `hydro_event.hydro_event_id`

## 6. 外发流量时序命令

见 `samples\outflow_time_series_request.json`

适用 Agent：

- `OutflowPlanAgent`

核心字段：

- `command_type = outflow_time_series_request`
- `target_agent_instance`
- `hydro_event.hydro_event_type = OUTFLOW_TIME_SERIES`
- `hydro_event.event_content_url`

## 7. 联调建议

- 首轮联调只验证 `task_init_request`、`tick_cmd_request`、`task_terminate_request`
- 第二轮再验证事件驱动命令
- 所有响应都要检查 `command_status` 与 `source_agent_instance`
- 如果中央侧走的是 Java 模型，字段命名要特别核对大小写和可选字段

## 8. 关联说明

如需配合启动检查和最终验收，可参考：

- `03-startup-checklist.md`
- `05-delivery-acceptance-checklist.md`
