# coding: utf-8
"""
仿真状态数据结构定义
集中定义所有仿真相关的数据类，便于管理和复用
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any


# ============== 基础状态结构 ==============

@dataclass
class StationState:
    """站位状态数据结构"""
    station_id: int
    h_i_t: float              # 当前水位
    hat_h_i_t: float          # 当前尾水水位
    qtot_i_t: float           # 当前总流量
    inflow_i_t: float         # 当前入流量
    volume: float = 0.0       # 库容
    area: float = 0.0         # 水面面积
    bottom_elevation: float = 0.0  # 底部高程


@dataclass
class DeviceState:
    """设备状态数据结构"""
    device_name: str
    device_type: str          # 设备类型：turbine, gate, pump等
    h_i_t: float              # 设备处水位
    hat_h_i_t: float          # 设备处尾水水位
    q_i_t: float              # 设备流量
    efficiency: float = 1.0   # 设备效率
    status: str = "active"    # 设备状态


@dataclass
class DeviceControl:
    """设备控制变量数据结构"""
    device_name: str
    e_i_t: float              # 开度
    n_i_t: int                # 机组数量
    target_flow: float = 0.0  # 目标流量
    priority: int = 1         # 优先级


@dataclass
class SimulationState:
    """仿真状态主结构"""
    station_state: StationState
    device_states: Dict[str, DeviceState]
    device_controls: Dict[str, DeviceControl]
    time_step: int = 0
    simulation_time: float = 0.0


# ============== 边界和虚拟节点结构 ==============

@dataclass
class BoundaryState:
    """边界状态数据结构"""
    h_i_t: float = 0.0              # 边界水位
    hat_h_i_t: float = 0.0          # 边界尾水水位
    Inflow_i_t: float = 0.0         # 边界入流量
    qtot_i_t: float = 0.0           # 边界总流量
    boundary_type: str = "default"   # 边界类型：upstream/downstream
    boundary_id: str = ""            # 边界ID
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'h_i_t': self.h_i_t,
            'hat_h_i_t': self.hat_h_i_t,
            'Inflow_i_t': self.Inflow_i_t,
            'qtot_i_t': self.qtot_i_t,
            'boundary_type': self.boundary_type,
            'boundary_id': self.boundary_id
        }


@dataclass
class VirtualNodeState:
    """虚拟节点状态数据结构"""
    node_id: str
    h_i_t: float              # 虚拟节点水位（平均值）
    hat_h_i_t: float          # 虚拟节点尾水水位（平均值）
    qtot_i_t: float           # 虚拟节点总流量（总和）
    inflow_i_t: float         # 虚拟节点入流量（总和）
    node_count: int           # 包含的实际节点数量
    actual_nodes: List[int]   # 包含的实际节点ID列表


@dataclass
class ExtendedSimulationState:
    """扩展的仿真状态 - 包含虚拟上下游和边界"""
    station_state: StationState
    device_states: Dict[str, DeviceState]
    device_controls: Dict[str, DeviceControl]
    time_step: int = 0
    simulation_time: float = 0.0

    # 虚拟上下游状态
    virtual_upstream: Optional[VirtualNodeState] = None
    virtual_downstream: Optional[VirtualNodeState] = None

    # 边界状态
    upstream_boundary: Optional[BoundaryState] = None
    downstream_boundary: Optional[BoundaryState] = None


# ============== 导出列表 ==============

__all__ = [
    'StationState',
    'DeviceState',
    'DeviceControl',
    'SimulationState',
    'BoundaryState',
    'VirtualNodeState',
    'ExtendedSimulationState',
]

