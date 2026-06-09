# HydroSimulator 使用指南

## 目录
1. [简介](#简介)
2. [快速开始](#快速开始)
3. [核心概念](#核心概念)
4. [详细使用步骤](#详细使用步骤)
5. [API 参考](#api-参考)
6. [完整示例](#完整示例)
7. [常见问题](#常见问题)

---

## 简介

`HydroSimulator` 是一个水力仿真器，用于模拟水利系统中的流量、水位等状态变化。它支持：

- ✅ 基于配置文件的仿真环境初始化
- ✅ 节点ID的自动映射（原始ID ↔ 连续ID）
- ✅ 设备控制量的灵活配置
- ✅ 上下游边界条件的设定
- ✅ 多步仿真的状态传递

---

## 快速开始

### 1. 导入必要的模块

```python
import corelib
from corelib.core.hydro_simulator import HydroSimulator
from simulation_states import DeviceControl, BoundaryState
```

### 2. 创建仿真器实例

```python
config_file = "./标准10.15.yml"
sim = HydroSimulator(config_file)
```

### 3. 运行第一次仿真

```python
# 获取初始状态
simulation_states = sim.get_initial_states()

# 准备控制量和边界参数（详见后续章节）
controls = {}
boundary_params = {}

# 执行仿真
new_states, results = sim.step(
    simulation_states=simulation_states,
    controls=controls,
    boundary_params=boundary_params
)
```

---

## 核心概念

### 1. ID 映射

HydroSimulator 内部使用**连续ID**（0, 1, 2, ...）来管理节点，而配置文件中使用的是**原始ID**（如 1009, 1018）。

- **原始ID**: 配置文件中定义的节点ID
- **连续ID**: 仿真器内部使用的索引，从 0 开始连续编号

### 2. 控制量 (DeviceControl)

控制量用于描述某个节点上设备的操作状态，包括：

| 参数 | 说明 | 类型 |
|------|------|------|
| `device_name` | 设备标识符 | str |
| `e_i_t` | 设备开度（例如闸门开度） | float |
| `n_i_t` | 设备数量或状态 | int |
| `target_flow` | 目标流量 (m³/s) | float |
| `priority` | 优先级 | int |

### 3. 边界条件 (BoundaryState)

边界条件用于描述节点的上下游边界状态：

| 参数 | 说明 | 类型 |
|------|------|------|
| `h_i_t` | 边界水位 (m) | float |
| `hat_h_i_t` | 边界尾水水位 (m) | float |
| `Inflow_i_t` | 边界入流 (m³/s) | float |
| `qtot_i_t` | 边界总流量 (m³/s) | float |
| `boundary_type` | 边界类型 ("upstream" 或 "downstream") | str |
| `boundary_id` | 边界标识符 | str |

### 4. 仿真状态 (SimulationState)

仿真状态包含节点的当前水力状态，如水位、流量等。通过 `sim.get_initial_states()` 获取初始状态，或使用上一步仿真的输出状态。

---

## 详细使用步骤

### 步骤 1：创建仿真器

```python
config_file = "./标准10.15.yml"
sim = HydroSimulator(config_file)
```

**说明**: 配置文件（YAML 格式）包含水利系统的拓扑结构、节点参数等信息。

---

### 步骤 2：获取 ID 映射信息

#### 方法 A：获取完整映射字典

```python
id_mapping = sim.get_id_mapping()

# 原始ID -> 连续ID
original_to_seq = id_mapping['original_to_sequential']
print(f"原始ID 1009 对应连续ID: {original_to_seq[1009]}")

# 连续ID -> 原始ID
seq_to_original = id_mapping['sequential_to_original']
print(f"连续ID 0 对应原始ID: {seq_to_original[0]}")
```

#### 方法 B：单个 ID 转换

```python
# 原始ID -> 连续ID
seq_id = sim.get_sequential_id(1009)

# 连续ID -> 原始ID
orig_id = sim.get_original_id(seq_id)
```

**⚠️ 重要**: 在构造控制量和边界参数时，必须使用**连续ID**作为字典的键。

---

### 步骤 3：构造控制量

控制量是一个**嵌套字典**，结构如下：

```python
controls = {
    连续ID_1: {
        '设备名称_1': DeviceControl(...),
        '设备名称_2': DeviceControl(...),
    },
    连续ID_2: {
        '设备名称_1': DeviceControl(...),
    }
}
```

#### 示例：

```python
seq_id_1009 = sim.get_sequential_id(1009)

controls = {
    seq_id_1009: {
        'ZM1-节制闸#1': DeviceControl(
            device_name='ZM1-节制闸#1',
            e_i_t=1.2,        # 开度 1.2m
            n_i_t=1,          # 1 个设备
            target_flow=0.0,  # 目标流量
            priority=1        # 优先级
        ),
        'ZM1-节制闸#2': DeviceControl(
            device_name='ZM1-节制闸#2',
            e_i_t=1.2,
            n_i_t=1,
            target_flow=0.0,
            priority=1
        )
    }
}
```

**说明**:
- 如果某个节点没有控制设备，可以不包含该节点的键
- 每个设备用唯一的名称标识

---

### 步骤 4：构造边界参数

边界参数也是**嵌套字典**，结构如下：

```python
boundary_params = {
    连续ID: {
        'upstream_boundary': BoundaryState(...),
        'downstream_boundary': BoundaryState(...)
    }
}
```

#### 示例：

```python
seq_id_1009 = sim.get_sequential_id(1009)

boundary_params = {
    seq_id_1009: {
        'upstream_boundary': BoundaryState(
            h_i_t=130.0,          # 上游水位 130m
            hat_h_i_t=95.0,       # 上游尾水水位 95m
            Inflow_i_t=50.0,      # 上游入流 50 m³/s
            qtot_i_t=30.0,        # 上游总流量 30 m³/s
            boundary_type="upstream",
            boundary_id=f"upstream_boundary_{seq_id_1009}"
        ),
        'downstream_boundary': BoundaryState(
            h_i_t=80.0,           # 下游水位 80m
            hat_h_i_t=75.0,       # 下游尾水水位 75m
            Inflow_i_t=40.0,      # 下游入流 40 m³/s
            qtot_i_t=20.0,        # 下游总流量 20 m³/s
            boundary_type="downstream",
            boundary_id=f"downstream_boundary_{seq_id_1009}"
        )
    }
}
```

**说明**:
- 如果某个节点没有边界条件，可以不包含该节点
- 如果整个系统无边界影响，传入空字典 `{}`

---

### 步骤 5：执行仿真

#### 第一次仿真（使用初始状态）

```python
# 获取初始状态
simulation_states = sim.get_initial_states()

# 执行仿真
new_states, results = sim.step(
    simulation_states=simulation_states,
    controls=controls,
    boundary_params=boundary_params
)
```

**返回值**:
- `new_states`: 更新后的仿真状态（字典，键为连续ID）
- `results`: 仿真结果（字典，键为连续ID），包含入流、出流等信息

#### 查看结果

```python
for node_id, result in results.items():
    orig_id = sim.get_original_id(node_id)
    state = new_states[node_id]
    
    print(f"节点 {node_id} (原始ID {orig_id}):")
    print(f"  水位: {state.station_state.h_i_t:.2f} m")
    print(f"  入流: {result['q_in']:.2f} m³/s")
    print(f"  出流: {result['q_out']:.2f} m³/s")
```

---

### 步骤 6：多步仿真（状态传递）

在连续仿真时，将上一步的 `new_states` 作为下一步的 `simulation_states`：

```python
# 第一步仿真
new_states_1, results_1 = sim.step(
    simulation_states=simulation_states,
    controls=controls,
    boundary_params=boundary_params
)

# 调整控制量（可选）
controls_2 = controls.copy()
seq_id = sim.get_sequential_id(1009)
controls_2[seq_id]['ZM1-节制闸#1'].e_i_t = 1.5  # 增加开度

# 第二步仿真，使用第一步的结果
new_states_2, results_2 = sim.step(
    simulation_states=new_states_1,  # 使用上一步的状态
    controls=controls_2,
    boundary_params=boundary_params
)
```

---

## API 参考

### HydroSimulator 类

#### `__init__(config_file: str)`

创建仿真器实例。

**参数**:
- `config_file`: 配置文件路径（YAML 格式）

---

#### `get_id_mapping() -> dict`

获取完整的 ID 映射字典。

**返回值**:
```python
{
    'original_to_sequential': {原始ID: 连续ID, ...},
    'sequential_to_original': {连续ID: 原始ID, ...}
}
```

---

#### `get_sequential_id(original_id: int) -> int`

将原始ID转换为连续ID。

**参数**:
- `original_id`: 原始节点ID

**返回值**: 连续ID

---

#### `get_original_id(sequential_id: int) -> int`

将连续ID转换为原始ID。

**参数**:
- `sequential_id`: 连续节点ID

**返回值**: 原始ID

---

#### `get_initial_states() -> dict`

获取系统的初始仿真状态。

**返回值**: 初始状态字典（键为连续ID）

---

#### `step(simulation_states: dict, controls: dict, boundary_params: dict) -> tuple`

执行一步仿真。

**参数**:
- `simulation_states`: 当前仿真状态（字典，键为连续ID）
- `controls`: 控制量（嵌套字典）
- `boundary_params`: 边界参数（嵌套字典）

**返回值**: 
- `new_states`: 更新后的仿真状态
- `results`: 仿真结果，包含 `q_in`（入流）、`q_out`（出流）等

---

## 完整示例

```python
import corelib
from corelib.core.hydro_simulator import HydroSimulator
from simulation_states import DeviceControl, BoundaryState

# 1. 创建仿真器
config_file = "./标准10.15.yml"
sim = HydroSimulator(config_file)

# 2. 获取ID映射
seq_id_1009 = sim.get_sequential_id(1009)
seq_id_1018 = sim.get_sequential_id(1018)

# 3. 构造控制量
controls = {
    seq_id_1009: {
        'ZM1-节制闸#1': DeviceControl(
            device_name='ZM1-节制闸#1',
            e_i_t=1.2,
            n_i_t=1,
            target_flow=0.0,
            priority=1
        )
    },
    seq_id_1018: {
        'ZM2-节制闸#1': DeviceControl(
            device_name='ZM2-节制闸#1',
            e_i_t=0.9,
            n_i_t=1,
            target_flow=0.0,
            priority=1
        )
    }
}

# 4. 构造边界参数
boundary_params = {
    seq_id_1009: {
        'upstream_boundary': BoundaryState(
            h_i_t=130.0,
            hat_h_i_t=95.0,
            Inflow_i_t=50.0,
            qtot_i_t=30.0,
            boundary_type="upstream",
            boundary_id=f"upstream_boundary_{seq_id_1009}"
        ),
        'downstream_boundary': BoundaryState(
            h_i_t=80.0,
            hat_h_i_t=75.0,
            Inflow_i_t=40.0,
            qtot_i_t=20.0,
            boundary_type="downstream",
            boundary_id=f"downstream_boundary_{seq_id_1009}"
        )
    }
}

# 5. 获取初始状态
simulation_states = sim.get_initial_states()

# 6. 执行第一步仿真
new_states_1, results_1 = sim.step(
    simulation_states=simulation_states,
    controls=controls,
    boundary_params=boundary_params
)

print(f"仿真成功！更新了 {len(new_states_1)} 个节点的状态")

# 7. 查看结果
for node_id, result in list(results_1.items())[:3]:
    orig_id = sim.get_original_id(node_id)
    state = new_states_1[node_id]
    print(f"\n节点 {node_id} (原始ID {orig_id}):")
    print(f"  水位: {state.station_state.h_i_t:.2f} m")
    print(f"  入流: {result['q_in']:.2f} m³/s")
    print(f"  出流: {result['q_out']:.2f} m³/s")

# 8. 执行第二步仿真（使用第一步结果）
controls_2 = controls.copy()
controls_2[seq_id_1009]['ZM1-节制闸#1'].e_i_t = 1.5  # 调整开度

new_states_2, results_2 = sim.step(
    simulation_states=new_states_1,  # 使用上一步状态
    controls=controls_2,
    boundary_params=boundary_params
)

# 9. 对比结果
if seq_id_1009 in results_1 and seq_id_1009 in results_2:
    print(f"\n节点 {seq_id_1009} (原始ID 1009) 结果对比:")
    print(f"  第1步 - 水位: {new_states_1[seq_id_1009].station_state.h_i_t:.2f}m, "
          f"出流: {results_1[seq_id_1009]['q_out']:.2f} m³/s")
    print(f"  第2步 - 水位: {new_states_2[seq_id_1009].station_state.h_i_t:.2f}m, "
          f"出流: {results_2[seq_id_1009]['q_out']:.2f} m³/s")
```

---

## 常见问题

### Q1: 为什么要使用连续ID？

**A**: 仿真器内部使用数组进行高效计算，需要连续的索引。ID映射机制允许用户使用配置文件中的原始ID，同时保持内部计算效率。

### Q2: 如果某个节点没有控制设备怎么办？

**A**: 在 `controls` 字典中不包含该节点的键即可，或传入空字典 `{}`。

### Q3: 边界参数是必需的吗？

**A**: 是的。`boundary_params` 参数必须传入，但可以是空字典 `{}`（表示无边界影响）。

### Q4: 如何实现长时间序列仿真？

**A**: 使用循环，每次调用 `step()` 方法，并将上一步的 `new_states` 作为下一步的 `simulation_states`：

```python
states = sim.get_initial_states()
for t in range(100):  # 100 个时间步
    # 根据时间 t 更新 controls 和 boundary_params
    states, results = sim.step(states, controls, boundary_params)
    # 处理结果...
```

### Q5: 如何调试仿真结果？

**A**: 
1. 检查ID映射是否正确（`get_sequential_id()` / `get_original_id()`）
2. 打印控制量和边界参数，确保数据结构正确
3. 逐步查看 `results` 中的 `q_in`、`q_out` 等关键变量
4. 对比多步仿真的状态变化趋势

### Q6: 支持哪些配置文件格式？

**A**: 目前支持 YAML 格式（`.yml` 或 `.yaml` 文件）。

---

## 版本信息

- **文档版本**: 1.0
- **最后更新**: 2025-10-17

---

## 技术支持

如有问题，请联系开发团队或查阅配置文件示例：`标准10.15.yml`。

