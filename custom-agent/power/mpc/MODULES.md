# MPC 工程结构及模块说明

本文档用于说明 `F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc` 目录下当前工程结构，以及每个模块文件的用途、职责和调用关系。

## 1. 工程结构

当前源码目录如下：

```text
mpc/
├── hydrosim_api.py
├── hydrosim_demo.py
├── MODULES.md
└── hydrosim/
    ├── __init__.py
    ├── config.py
    ├── core.py
    ├── result_factory.py
    ├── runtime.py
    ├── service.py
    └── types.py
```

说明：
- `__pycache__/` 是 Python 运行缓存目录，不属于工程源码结构，不作为模块说明对象。
- 当前 `mpc` 目录已经收敛成“2 个顶层入口文件 + 1 个内部实现包”的结构。

## 2. 目录职责

### `mpc/`

这是 HydroSim MPC 的应用目录。

主要放两类内容：
- 对外入口文件
- 内部实现包 `hydrosim/`

### `mpc/hydrosim/`

这是 HydroSim 的内部实现包。

这里放的是实际算法实现、配置、类型定义、结果导出和服务编排代码。  
外部调用方原则上不需要直接依赖这个目录里的细节模块，除非是在做内部开发或重构。

## 3. 顶层文件说明

### `hydrosim_api.py`

文件定位：对外 API 入口文件。

主要作用：
- 给外部系统提供稳定调用入口
- 屏蔽内部 `service/core/runtime` 的实现细节
- 提供函数式和类式两种调用方式

当前主要内容：
- `HydroSimulationApi`
- `describe_simulation_capabilities()`
- `run_random_simulation()`
- `run_configured_simulation()`

适用场景：
- 被其他 Python 工程集成
- 被上层业务服务直接调用
- 作为统一外部接入点

调用关系：
- 依赖 `hydrosim` 包中的 `HydroSimulationService`
- 不直接承载仿真算法细节

建议：
- 外部对接优先从这个文件进入

### `hydrosim_demo.py`

文件定位：演示脚本和命令行入口文件。

主要作用：
- 提供本地可直接运行的 Demo
- 解析命令行参数
- 调用 `hydrosim_api.py`
- 打印仿真输出结果

当前主要内容：
- `HydroSimulationDemo`
- `_build_parser()`
- `main()`

适用场景：
- 本地运行验证
- smoke 测试
- 命令行查看 JSON 输出结果

调用关系：
- 依赖 `hydrosim_api.py`
- 不直接依赖底层 runtime 细节

建议：
- 这个文件是“演示入口”，不是“外部集成入口”

## 4. `hydrosim` 包内文件说明

### `hydrosim/__init__.py`

文件定位：包导出文件。

主要作用：
- 统一暴露包内稳定对象
- 让外部 import 更简洁

当前导出的对象主要包括：
- `HydroSimulationCore`
- `HydroSimulationResultFactory`
- `HydroSimulationService`
- `HydroRandomSimulationRequest`
- `HydroConfiguredSimulationRequest`
- `HydroSimulationArtifacts`
- `HydroSimulationFileOutputs`
- `HydroSimulationJsonOutputs`

说明：
- 这个文件本身不承载业务逻辑
- 它的职责是“统一出口”

### `hydrosim/config.py`

文件定位：静态配置模块。

主要作用：
- 管理版本号
- 管理电站、机组、水库等静态配置
- 管理站点 ID 与索引映射关系
- 提供配置校验辅助方法

当前包含的核心内容：
- `__version__`
- `FLOW_CONFIGS`
- `FLOW_STATION_CFGS`
- `POWER_CONFIGS`
- `UNIT_CONFIGS`
- `CAPA_LOC`
- `STATION_NODE_IDS`
- `STATION_CANAL_IDS`
- `NODE_TO_INDEX`
- `CANAL_TO_NODE`

当前主要函数：
- `validate_hydrosim_config()`
- `build_station_name_map()`
- `list_station_names()`

适合放在本文件的内容：
- 固定配置
- 静态映射
- 版本信息

不适合放在本文件的内容：
- 仿真执行流程
- 输出文件生成
- CLI 参数处理

### `hydrosim/types.py`

文件定位：类型与数据契约模块。

主要作用：
- 定义输入请求对象
- 定义输出结果对象
- 约束输出模式

当前主要对象：
- `HydroOutputMode`
- `HydroSimulationFileOutputs`
- `HydroSimulationJsonOutputs`
- `HydroSimulationArtifacts`
- `HydroRandomSimulationRequest`
- `HydroConfiguredSimulationRequest`

说明：
- 这个文件定义的是“数据长什么样”
- 不负责“数据怎么生成”

### `hydrosim/service.py`

文件定位：服务层模块。

主要作用：
- 面向外部调用提供稳定服务方法
- 处理 `file/json/mixed` 三种输出模式
- 在纯 JSON 模式下隔离临时文件副作用

当前核心类：
- `HydroSimulationService`

当前主要方法：
- `run_random()`
- `run_configured()`

说明：
- 这是外部调用和内部核心之间的一个缓冲层
- 它不直接负责算法推演细节，而是负责组织调用和整理返回方式

### `hydrosim/core.py`

文件定位：核心编排模块。

主要作用：
- 组装仿真所需运行对象
- 调用随机仿真流程
- 调用配置驱动仿真流程
- 协调结果工厂导出结果

当前核心类：
- `HydroSimulationCore`

当前主要方法：
- `run_random()`
- `run_configured()`
- `_validate_configs()`
- `_build_runtime_components()`

说明：
- 这个文件是“核心编排层”
- 它把 `runtime.py` 和 `result_factory.py` 串起来
- 算法不是写在这里最底层执行，而是在这里统一调度

### `hydrosim/result_factory.py`

文件定位：结果工厂模块。

主要作用：
- 导出仿真结果文件
- 组装对外返回结果
- 汇总机组出力 JSON 数据

当前核心类：
- `HydroSimulationResultFactory`

当前主要能力：
- 导出调度最小单位 JSON
- 导出正式结果 CSV
- 导出配置结果 YAML
- 导出运行摘要 JSON
- 导出 Markdown 报告
- 组装 `HydroSimulationArtifacts`
- 生成 `unit_outputs` 机组出力数据

说明：
- 只要是“结果怎么落文件、怎么组装返回值”的问题，都应优先放这里
- 这个文件不负责仿真主流程执行

### `hydrosim/runtime.py`

文件定位：运行时与算法实现模块。

主要作用：
- 提供水电仿真所需的核心运行对象
- 承载仿真执行过程
- 承载配置驱动仿真的输入解析辅助函数

当前主要类：
- `NormalizedSignal`
- `HydroNHQGenerator`
- `HydroUnit`
- `HydroStation`
- `HydroStair`
- `PIDController`
- `HydroReservoir`
- `HydroResStairs`
- `RiverArray`

当前主要函数：
- `_configure_output_dir()`
- `_validate_range()`
- `_read_yaml()`
- `_read_json()`
- `_time_axis_from_event()`
- `_apply_yaml_basic_parameters()`
- `_apply_initial_conditions()`
- `_power_series_by_station()`
- `_upstream_inflow_series()`
- `_target_stage_series_by_node()`
- `_run_phase()`
- `_run_phase_v16()`

说明：
- 这是当前最重的底层模块
- 它已经剥离了结果导出职责，但仍然同时包含：
  - 领域运行对象
  - 仿真执行函数
  - 输入事件解析辅助函数

这个文件当前是整个工程里最值得继续拆薄的部分。

## 5. 模块调用关系

当前主要调用链如下：

```text
hydrosim_demo.py
    -> hydrosim_api.py
        -> hydrosim/service.py
            -> hydrosim/core.py
                -> hydrosim/runtime.py
                -> hydrosim/result_factory.py

hydrosim_api.py
    -> hydrosim/service.py
        -> hydrosim/core.py
```

可以这样理解：
- `hydrosim_demo.py` 负责运行入口
- `hydrosim_api.py` 负责对外接口
- `service.py` 负责服务包装
- `core.py` 负责核心编排
- `runtime.py` 负责算法运行
- `result_factory.py` 负责结果输出
- `types.py` 负责数据定义
- `config.py` 负责静态配置

## 6. 对外使用建议

### 外部系统调用

建议入口：
- `hydrosim_api.py`

不建议直接调用：
- `hydrosim/runtime.py`
- `hydrosim/core.py`

原因：
- 这两个文件属于内部实现层，后续仍可能继续重构

### 本地命令行运行

建议入口：
- `hydrosim_demo.py`

示例：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode smoke --output-mode json
```

#### 运行模式说明

`hydrosim_demo.py` 当前支持 3 种运行模式：

- `--mode smoke`  
  最小化快速验证，适合检查程序是否能正常跑通。

- `--mode random`  
  使用随机来水和随机总出力指令做完整仿真。

- `--mode configured`  
  使用外部时间序列和配置文件驱动仿真。

#### 输出模式说明

`hydrosim_demo.py` 当前支持 3 种输出模式：

- `--output-mode json`  
  只输出 JSON 数据，不在指定输出目录写正式结果文件。

- `--output-mode file`  
  只输出文件路径结果，主要用于文件落盘场景。

- `--output-mode mixed`  
  同时输出文件路径和 JSON 数据。

#### 常用命令示例

1. 最小 smoke 验证，只返回 JSON：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode smoke --output-mode json
```

说明：
- 适合快速检查程序是否可运行
- 终端输出纯 JSON
- JSON 中通常包含：
  - `run_summary`
  - `dispatch_min_p`
  - `unit_outputs`

2. 最小 smoke 验证，只输出文件：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode smoke --output-mode file --output-dir F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\output_smoke --make-plots
```

说明：
- 会把结果文件写入 `--output-dir`
- 传入 `--make-plots` 时，会额外输出大量 JPG 图像
- 返回内容以文件路径为主
- 通常会生成：
  - `formal_results_v16.csv`
  - `dispatch_min_p_v16.json`
  - `simulation_report_v16.md`
  - `run_summary_v16.json`
  - 多张 `*.jpg` 图像文件

3. 最小 smoke 验证，同时输出文件和 JSON：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode smoke --output-mode mixed --output-dir F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\output_smoke --make-plots
```

说明：
- 同时适合人工查看和程序接收
- 返回结果一般包含两部分：
  - `files`
  - `json`

4. 随机仿真，输出 JSON：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode random --sim-steps 60 --warm-steps 60 --output-mode json
```

说明：
- `--sim-steps` 表示正式仿真步数
- `--warm-steps` 表示预热步数
- 适合查看程序返回的结构化结果

5. 随机仿真，输出文件：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode random --sim-steps 60 --warm-steps 60 --output-mode file --output-dir F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\output_random --make-plots
```

说明：
- 适合保留 CSV、报告、摘要文件
- 传入 `--make-plots` 时，会额外生成图像文件
- 结果会写入 `output_random`

6. 随机仿真，同时输出文件和 JSON：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode random --sim-steps 60 --warm-steps 60 --output-mode mixed --output-dir F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\output_random --make-plots
```

7. 配置驱动仿真，输出 JSON：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode configured --time-series-file F:\path\to\time_series.json --mpc-config-file F:\path\to\mpc_config.yaml --initial-states-file F:\path\to\initial_states.yaml --constraints-file F:\path\to\constrains_targets.yaml --output-mode json
```

说明：
- `configured` 模式下必须提供 `--time-series-file`
- 其余 3 个配置文件可按实际路径传入
- 适合接入真实外部输入数据

8. 配置驱动仿真，输出文件：

```bash
python F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\hydrosim_demo.py --mode configured --time-series-file F:\path\to\time_series.json --mpc-config-file F:\path\to\mpc_config.yaml --initial-states-file F:\path\to\initial_states.yaml --constraints-file F:\path\to\constrains_targets.yaml --output-mode file --output-dir F:\sl\hydros\hydros-python-sdk\custom-agent\power\mpc\output_configured --make-plots
```

说明：
- 一般会输出：
  - `formal_results_v16.csv`
  - `configured_outputs_v16.yaml`
  - `run_summary_v16.json`
  - 多张 `*.jpg` 图像文件

#### 图片输出说明

当前图片输出不是默认开启的，需要显式加上：

```bash
--make-plots
```

不加这个参数时，即使是 `file` 或 `mixed` 模式，也只会输出结果文件，不会生成图片。

开启后，通常会额外输出以下图像：
- 上游来流信号图
- 电网调度功率信号图
- 预热阶段河道图
- 预热阶段水库历史图
- 预热阶段水库 ODD 图
- 预热阶段梯级电站调度图
- 正式阶段河道图
- 正式阶段水库历史图
- 正式阶段水库 ODD 图
- 正式阶段梯级电站调度图
- 各电站历史图

图片文件当前以 `jpg` 格式输出，文件名中会带阶段前缀和时间戳，例如：

```text
预热_河道热图_大渡河_水力_20260616.173531.jpg
正式_水库历史_瀑布沟_20260616.173609.jpg
正式_梯级电站调度_大渡河_电站_20260616.173626.jpg
```

#### `json` / `file` / `mixed` 返回差异

1. `--output-mode json`

返回示意：

```json
{
  "run_summary": {},
  "dispatch_min_p": [],
  "unit_outputs": {}
}
```

特点：
- 终端输出结构化 JSON
- 不依赖输出目录中的正式文件
- 适合被其他程序直接解析

2. `--output-mode file`

返回示意：

```json
{
  "output_dir": "F:\\...\\output_random",
  "formal_results_csv": "F:\\...\\formal_results_v16.csv",
  "dispatch_min_p_json": "F:\\...\\dispatch_min_p_v16.json",
  "simulation_report_md": "F:\\...\\simulation_report_v16.md",
  "run_summary_json": "F:\\...\\run_summary_v16.json"
}
```

特点：
- 以文件路径为主
- 适合文件留档和人工查看

3. `--output-mode mixed`

返回示意：

```json
{
  "files": {},
  "json": {}
}
```

特点：
- 同时保留文件产物和结构化数据
- 适合调试、联调和阶段性过渡

### 内部维护修改

如果修改目标是：

- 调整静态参数  
  改 `hydrosim/config.py`

- 调整输入输出数据结构  
  改 `hydrosim/types.py`

- 调整外部接入方式  
  改 `hydrosim_api.py`

- 调整命令行运行方式  
  改 `hydrosim_demo.py`

- 调整仿真主流程编排  
  改 `hydrosim/core.py`

- 调整结果文件与 JSON 输出  
  改 `hydrosim/result_factory.py`

- 调整底层算法与仿真运行逻辑  
  改 `hydrosim/runtime.py`

## 7. 当前工程结构结论

当前 `mpc` 工程已经形成比较清晰的结构：

- 顶层入口层  
  `hydrosim_api.py`、`hydrosim_demo.py`

- 内部实现包  
  `hydrosim/`

- 包内按职责继续分成：
  - 配置模块 `config.py`
  - 类型模块 `types.py`
  - 服务模块 `service.py`
  - 编排模块 `core.py`
  - 结果模块 `result_factory.py`
  - 运行时模块 `runtime.py`
