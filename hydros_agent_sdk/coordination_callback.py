"""
Callback interfaces for Hydro agent coordination.

This module provides callback interfaces similar to Java's SimCoordinationCallback,
allowing developers to focus on business logic while the SDK handles:
- Message parsing and serialization
- MQTT connection and subscription
- Message filtering and routing
- Automatic response handling
"""

from abc import ABC, abstractmethod
from typing import Any
import logging

from hydros_agent_sdk.contract.v1 import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
    OutflowTimeSeriesRequest,
)

logger = logging.getLogger(__name__)


def _agent_id_for_log(agent_like) -> str:
    if agent_like is None:
        return "UNKNOWN_AGENT"
    if isinstance(agent_like, dict):
        return agent_like.get("agent_id", "UNKNOWN_AGENT")
    return getattr(agent_like, "agent_id", "UNKNOWN_AGENT")


class SimCoordinationCallback(ABC):
    """
    Abstract base class for simulation coordination callbacks.

    This interface defines callback methods that will be invoked when coordination
    commands are received. Developers must implement the three core methods:
    - get_component(): Return agent code
    - on_sim_task_init(): Handle task initialization
    - on_tick(): Handle simulation steps

    All other methods have default implementations and can be optionally overridden.
    """

    @abstractmethod
    def get_component(self) -> str:
        pass

    @abstractmethod
    def on_sim_task_init(self, request: SimTaskInitRequest):
        pass

    @abstractmethod
    def on_tick(self, request: TickCmdRequest):
        pass

    def is_remote_agent(self, agent_instance: Any) -> bool:
        return False

    def on_agent_instance_sibling_created(self, response: SimTaskInitResponse):
        agent_like = response.source_agent_instance_ref
        logger.info(f"Sibling agent created: {_agent_id_for_log(agent_like)}")

    def on_agent_instance_sibling_status_updated(self, report: AgentInstanceStatusReport):
        agent_like = report.source_agent_instance_ref
        logger.info(f"Sibling agent status updated: {_agent_id_for_log(agent_like)}")

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        logger.warning("Time series calculation received but not implemented")

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        logger.info("Time series data update received")

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        logger.info(f"Task termination requested: {request.reason}")

    def on_monitor_rule_updated(self, request):
        logger.debug("Monitor rule updated (default handler)")

    def on_device_fault_inject(self, request):
        logger.debug("Device fault inject (default handler)")

    def on_noise_simulation(self, request):
        logger.debug("Noise simulation (default handler)")

    def on_identified_param_updated(self, request):
        logger.debug("Identified parameter updated (default handler)")

    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        logger.debug("Outflow time series request received")
