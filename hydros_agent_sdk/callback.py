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
from typing import Optional
import logging

from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
)
from hydros_agent_sdk.protocol.models import HydroAgentInstance

logger = logging.getLogger(__name__)


class SimCoordinationCallback(ABC):
    """
    Abstract base class for simulation coordination callbacks.

    This interface defines all the callback methods that will be invoked
    when coordination commands are received. Developers should implement
    this interface to provide their business logic.

    Similar to Java's com.hydros.protocol.coordination.node.callback.SimCoordinationCallback
    """

    @abstractmethod
    def get_component(self) -> str:
        """
        Get the agent code for this callback handler.

        Returns:
            Agent code (e.g., "TWINS_SIMULATION_AGENT")
        """
        pass

    @abstractmethod
    def is_remote_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """
        Check if an agent instance is remote (running on another node).

        Args:
            agent_instance: The agent instance to check

        Returns:
            True if the agent is remote, False if local
        """
        pass

    @abstractmethod
    def on_agent_instance_sibling_created(self, response: SimTaskInitResponse):
        """
        Called when a sibling agent instance is created (remote agent initialized).

        Args:
            response: The task init response from the remote agent
        """
        pass

    @abstractmethod
    def on_agent_instance_sibling_status_updated(self, report: AgentInstanceStatusReport):
        """
        Called when a sibling agent instance status is updated.

        Args:
            report: The status report from the remote agent
        """
        pass

    @abstractmethod
    def on_sim_task_init(self, request: SimTaskInitRequest):
        """
        Called when a simulation task initialization request is received.

        This is the main entry point for starting a simulation task.

        Args:
            request: The task initialization request
        """
        pass

    @abstractmethod
    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        Called when a time series calculation request is received.

        Args:
            request: The calculation request
        """
        pass

    @abstractmethod
    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        """
        Called when time series data is updated.

        Args:
            request: The data update request
        """
        pass

    @abstractmethod
    def on_tick(self, request: TickCmdRequest):
        """
        Called when a simulation tick command is received.

        This is called for each simulation step.

        Args:
            request: The tick command request
        """
        pass

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """
        Called when a task termination request is received.

        Default implementation logs the termination. Override to add custom cleanup logic.

        Args:
            request: The task termination request
        """
        logger.info(f"Task termination requested: {request.reason}")

    # Optional callbacks with default implementations
    def on_monitor_rule_updated(self, request):
        """
        Called when monitor rules are updated.

        Default implementation does nothing. Override if needed.

        Args:
            request: The monitor rule update request
        """
        logger.debug("Monitor rule updated (default handler)")

    def on_device_fault_inject(self, request):
        """
        Called when a device fault injection request is received.

        Default implementation does nothing. Override if needed.

        Args:
            request: The fault injection request
        """
        logger.debug("Device fault inject (default handler)")

    def on_noise_simulation(self, request):
        """
        Called when a noise simulation request is received.

        Default implementation does nothing. Override if needed.

        Args:
            request: The noise simulation request
        """
        logger.debug("Noise simulation (default handler)")

    def on_identified_param_updated(self, request):
        """
        Called when identified parameters are updated.

        Default implementation does nothing. Override if needed.

        Args:
            request: The parameter sync request
        """
        logger.debug("Identified parameter updated (default handler)")


class SimpleCallback(SimCoordinationCallback):
    """
    A simple implementation of SimCoordinationCallback with default no-op implementations.

    Developers can extend this class and only override the methods they need,
    rather than implementing all abstract methods.
    """

    def __init__(self, agent_code: str):
        """
        Initialize callback with agent code.

        Args:
            agent_code: Agent code (e.g., "TWINS_SIMULATION_AGENT")
        """
        self.agent_code = agent_code

    def get_component(self) -> str:
        """Get agent code."""
        return self.agent_code

    def is_remote_agent(self, agent_instance: HydroAgentInstance) -> bool:
        # Default: always return False (treat all as local)
        # Override this method to implement proper remote agent detection
        return False

    def on_agent_instance_sibling_created(self, response: SimTaskInitResponse):
        logger.info(f"Sibling agent created: {response.source_agent_instance.agent_id}")

    def on_agent_instance_sibling_status_updated(self, report: AgentInstanceStatusReport):
        logger.info(f"Sibling agent status updated: {report.source_agent_instance.agent_id}")

    def on_sim_task_init(self, request: SimTaskInitRequest):
        logger.warning("on_sim_task_init not implemented")

    def on_monitor_rule_updated(self, request):
        logger.info("Monitor rule updated")

    def on_device_fault_inject(self, request):
        logger.info("Device fault inject received")

    def on_noise_simulation(self, request):
        logger.info("Noise simulation received")

    def on_identified_param_updated(self, request):
        logger.info("Identified parameter updated")

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        logger.info("Time series calculation received")

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        logger.info("Time series data update received")

    def on_tick(self, request: TickCmdRequest):
        logger.info(f"Tick received: step={request.step}")

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        logger.info(f"Task terminate received: {request.reason}")
