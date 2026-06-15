"""
面向不同使用场景的专用智能体类型。

本模块提供预置的 BaseHydroAgent 扩展类型：
- TickableAgent: tick 驱动仿真智能体基类
- OntologySimulationAgent: 基于本体的仿真智能体
- TwinsSimulationAgent: 数字孪生仿真智能体
- ModelCalculationAgent: 事件驱动模型计算智能体
- CentralSchedulingAgent: 中央调度智能体通用基类
- OutflowPlanAgent: 事件驱动外发流量计划智能体

MPC 中央调度基类属于可选 MPC 能力，请从具体模块导入：
hydros_agent_sdk.agents.mpc_central_scheduling_agent
hydros_agent_sdk.agents.system_central_scheduling_agent
"""

from .tickable_agent import TickableAgent
from .ontology_simulation_agent import OntologySimulationAgent
from .twins_simulation_agent import TwinsSimulationAgent
from .model_calculation_agent import ModelCalculationAgent
from .central_scheduling_agent import CentralSchedulingAgent
from .outflow_plan_agent import OutflowPlanAgent

__all__ = [
    'TickableAgent',
    'OntologySimulationAgent',
    'TwinsSimulationAgent',
    'ModelCalculationAgent',
    'CentralSchedulingAgent',
    'OutflowPlanAgent',
]
