# Twins 滚动预测实现计划与变更说明

## 1. 目标

基于当前可运行的 `twins` 项目，为数字孪生智能体增加“预测/预报”能力，并保持与现有 coordinator 步进协调机制兼容。

本次实现目标包括：

- 在 agent YAML 配置中增加滚动周期和预测步长参数
- 支持工况事件注入，包括天气预报、用水计划、应急检修
- 在实时步进基础上增加滚动预测逻辑
- 预测结果按步长窗口输出，并支持后续滚动窗口对重叠步进行覆盖
- 在收到新的工况事件后，立即触发最新一轮滚动预测

## 2. 修改计划

### 2.1 配置层

- 从远端 `agent_configuration_url` 对应 YAML 的 `properties` 中读取以下字段：
  - `rolling_cycle`
  - `forecast_horizon`
  - `trigger_forecast_on_condition_update`
- 增加工况指标映射配置：
  - `boundary_condition_metrics`
  - `scenario_metric_groups`
  - `boundary_metric_aliases`
  - `control_metric_aliases`
- 提供本地样例文件，明确配置结构和默认映射

### 2.2 输入注入层

- 复用 SDK 现有 `_time_series_cache`，不新增协议
- 通过 `ObjectTimeSeries.object_id + metrics_code + step` 获取未来步长上的工况输入
- 将天气预报、用水计划映射为边界条件
- 将应急检修映射为控制条件，例如停运/关断

### 2.3 求解层

- 保持实时一步一仿真机制不变
- 为 `HydraulicSolver` 增加快照能力，支持：
  - 获取当前仿真状态快照
  - 基于快照前推未来 N 步
  - 不污染实时主状态
- 补齐边界条件和控制条件更新逻辑，使时间序列输入能实际作用到求解器

### 2.4 输出层

- 正常 tick 仅输出当前步实时结果
- 当满足滚动触发条件时，输出当前步到未来 N 步的预测结果
- 预测结果继续沿用现有 MQTT metrics 输出格式
- 发送侧按 `step_index` 输出窗口数据，接收侧可按步覆盖重叠预测结果

## 3. 实现后的行为

### 3.1 正常步进

- coordinator 下发第 `i` 步 tick
- twins agent 执行第 `i` 步实时计算
- 若未达到滚动周期，则仅输出第 `i` 步结果

### 3.2 滚动预测触发

- 当 `i % rolling_cycle == 0` 时激活预测
- 在输出第 `i` 步实时结果的同时，额外前推未来 `forecast_horizon` 步
- 输出窗口为 `Fi ~ Fi+N`

### 3.3 事件触发预测

- 当收到新的工况事件时间序列后：
  - 更新 `_time_series_cache`
  - 判断该指标是否属于预测相关工况
  - 若属于，并且开启 `trigger_forecast_on_condition_update`，则立即触发当前步起始的新一轮滚动预测

### 3.4 预测数据覆盖语义

- 本地发送侧缓存以 `step -> result` 方式维护窗口结果
- 新一轮窗口结果写入时：
  - 保留旧窗口中不重叠的历史步数据
  - 对重叠步直接覆盖为新窗口结果
- 这样可满足：
  - 旧窗口 `Fi ~ Fi+N`
  - 新窗口 `Fj ~ Fj+N`
  - 若存在重叠区间，则以 `j` 步窗口计算结果为准

## 4. 已完成的代码变更

### 4.1 `twins_agent.py`

已完成内容：

- 新增滚动预测相关配置解析
- 新增工况分类与指标映射
- 新增每步输入收集逻辑
- 新增滚动预测窗口执行逻辑
- 新增工况事件到来时的立即预测触发逻辑
- 新增预测结果窗口缓存
- 保留现有 coordinator tick 驱动模式和 MQTT 输出模式

关键实现点：

- `rolling_cycle` / `forecast_horizon` 配置读取
- `_collect_step_inputs(step)` 按步提取未来工况
- `_run_forecast_window(start_step, anchor_results)` 前推预测窗口
- `_should_trigger_forecast(step)` 判断周期触发
- `on_boundary_condition_update(...)` 判断工况变更后立即触发预测

### 4.2 `hydraulic_solver.py`

已完成内容：

- 增加实时状态快照能力
- 增加基于快照的单步预测接口
- 增加默认边界条件构造
- 增加边界条件注入逻辑
- 增加控制条件注入逻辑
- 保持实时求解接口兼容

关键实现点：

- `snapshot()`
- `solve_step_from_snapshot(...)`
- `_build_default_boundary_params(...)`
- `_apply_boundary_conditions(...)`
- `_apply_control_conditions(...)`

### 4.3 配置样例

新增文件：

- `forecast_agent_config.example.yaml`

用途：

- 给出远端 agent YAML 的最小配置样例
- 显式展示滚动周期、预测步长和 3 类工况映射方式

## 5. 当前默认映射策略

本次先按最小可运行方式实现默认映射：

- 天气预报：
  - `weather_forecast`
  - `weather_inflow`
  - `forecast_inflow`
  - 默认映射到 `Inflow_i_t`

- 用水计划：
  - `water_use_plan`
  - `planned_demand`
  - `planned_outflow`
  - 默认映射到 `qtot_i_t`

- 应急检修：
  - `emergency_maintenance`
  - `maintenance_shutdown`
  - 默认映射到控制侧 `maintenance_shutdown`
  - 当值大于 0 时，将设备开度和目标流量置零

如果线上真实 `metrics_code` 与上述命名不一致，应通过 YAML 中的映射项覆盖。

## 6. 当前验证结果

已完成验证：

- `python -m py_compile .\\twins_agent.py .\\hydraulic_solver.py`
- 模块导入验证：
  - `twins_agent.MyTwinsSimulationAgent`
  - `hydraulic_solver.HydraulicSolver`

验证结果：

- 当前代码语法正确
- 当前模块可成功导入

未完成验证：

- 与真实 coordinator 联调
- 与真实 MQTT 环境联调
- 与真实远端 agent YAML / IDZ 配置联调
- 与 hydros-data 接收端缓存覆盖逻辑联调

## 7. 后续建议

- 用真实业务 `metrics_code` 完善 3 类工况映射
- 与 coordinator 联调确认工况事件的下发时机和步号语义
- 与 hydros-data 联调确认重叠步覆盖逻辑
- 若后续需要区分“实时输出 topic”和“预测输出 topic”，建议在 agent 配置中单独增加 forecast topic
- 若后续需要告警联动，建议在预测结果窗口生成后增加规则评估层，而不是直接耦合在求解器逻辑中
