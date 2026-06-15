"""
面向不同使用场景的专用智能体类型。

本模块提供预置的 BaseHydroAgent 扩展类型：
- TickableAgent: tick 驱动仿真智能体基类
- OntologySimulationAgent: 基于本体的仿真智能体
- TwinsSimulationAgent: 数字孪生仿真智能体
- ModelCalculationAgent: 事件驱动模型计算智能体
- CentralSchedulingAgent: 中央调度智能体通用基类
- MpcCentralSchedulingAgent: 带默认 MPC 优化能力的中央调度智能体
- SystemCentralSchedulingAgent: 系统默认 CENTRAL_SCHEDULING_AGENT 实现
- OutflowPlanAgent: 事件驱动外发流量计划智能体
"""

from .tickable_agent import TickableAgent
from .ontology_simulation_agent import OntologySimulationAgent
from .twins_simulation_agent import TwinsSimulationAgent
from .model_calculation_agent import ModelCalculationAgent
from .central_scheduling_agent import CentralSchedulingAgent
from .mpc_central_scheduling_agent import MpcCentralSchedulingAgent
from .system_central_scheduling_agent import SystemCentralSchedulingAgent
from .outflow_plan_agent import OutflowPlanAgent

__all__ = [
    'TickableAgent',
    'OntologySimulationAgent',
    'TwinsSimulationAgent',
    'ModelCalculationAgent',
    'CentralSchedulingAgent',
    'MpcCentralSchedulingAgent',
    'SystemCentralSchedulingAgent',
    'OutflowPlanAgent',
]
