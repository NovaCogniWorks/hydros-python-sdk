"""
Specialized agent types for different use cases.

This module provides pre-built agent types that extend BaseHydroAgent:
- TickableAgent: Base class for tick-driven simulation agents
- OntologySimulationAgent: Ontology-based simulation agent
- TwinsSimulationAgent: Digital twins simulation agent
- ModelCalculationAgent: Event-driven model calculation agent
- CentralSchedulingAgent: Central scheduling agent with MPC optimization
"""

from .tickable_agent import TickableAgent
from .ontology_simulation_agent import OntologySimulationAgent
from .twins_simulation_agent import TwinsSimulationAgent
from .model_calculation_agent import ModelCalculationAgent
from .central_scheduling_agent import CentralSchedulingAgent

__all__ = [
    'TickableAgent',
    'OntologySimulationAgent',
    'TwinsSimulationAgent',
    'ModelCalculationAgent',
    'CentralSchedulingAgent',
]
