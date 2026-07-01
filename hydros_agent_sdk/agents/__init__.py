"""
SDK builtin and specialized agent types.

This module provides pre-built BaseHydroAgent extensions:
- TickableAgent: tick-driven simulation agent base
- OntologySimulationAgent: Ontology-based simulation agent
- TwinsSimulationAgent: Digital twins simulation agent
- ModelCalculationAgent: Event-driven model calculation agent
- CentralSchedulingAgent: Central scheduling agent base
- ControllerAgent: Local pump/gate station controller agent base
- OutflowPlanAgent: Event-driven outflow plan agent

MPC capabilities are still available through optional MPC agent modules:
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
