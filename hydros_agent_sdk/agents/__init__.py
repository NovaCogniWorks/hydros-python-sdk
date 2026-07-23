"""
SDK 内置和专用 Agent 类型。

本模块提供预构建的 BaseHydroAgent 扩展：
- TickableAgent：由 tick 驱动的仿真 Agent 基类
- OntologySimulationAgent：基于本体的仿真 Agent
- TwinsSimulationAgent：数字孪生仿真 Agent
- ModelCalculationAgent：事件驱动的模型计算 Agent
- CentralSchedulingAgent：中央调度 Agent 基类
- ControllerAgent：泵站、闸站等现地控制器 Agent 基类
- OutflowPlanAgent：事件驱动的出流计划 Agent

MPC 能力由以下可选 Agent 模块提供：
hydros_agent_sdk.agents.mpc_central_scheduling_agent
hydros_agent_sdk.agents.system_central_scheduling_agent
"""

from .tickable_agent import TickableAgent
from .ontology_simulation_agent import OntologySimulationAgent
from .twins_simulation_agent import TwinsSimulationAgent
from .model_calculation_agent import ModelCalculationAgent
from .central_scheduling_agent import CentralSchedulingAgent
from .controller_agent import ControllerAgent
from .outflow_plan_agent import OutflowPlanAgent

__all__ = [
    'TickableAgent',
    'OntologySimulationAgent',
    'TwinsSimulationAgent',
    'ModelCalculationAgent',
    'CentralSchedulingAgent',
    'ControllerAgent',
    'OutflowPlanAgent',
]
