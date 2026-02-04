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

    This interface defines callback methods that will be invoked when coordination
    commands are received. Developers must implement the three core methods:
    - get_component(): Return agent code
    - on_sim_task_init(): Handle task initialization
    - on_tick(): Handle simulation steps

    All other methods have default implementations and can be optionally overridden.

    Similar to Java's com.hydros.protocol.coordination.node.callback.SimCoordinationCallback
    """

    @abstractmethod
    def get_component(self) -> str:
        """
        Get the agent code for this callback handler.

        This method must be implemented by subclasses.

        Returns:
            Agent code (e.g., "TWINS_SIMULATION_AGENT")
        """
        pass

    @abstractmethod
    def on_sim_task_init(self, request: SimTaskInitRequest):
        """
        Called when a simulation task initialization request is received.

        This is the main entry point for starting a simulation task.
        This method must be implemented by subclasses.

        Args:
            request: The task initialization request
        """
        pass

    @abstractmethod
    def on_tick(self, request: TickCmdRequest):
        """
        Called when a simulation tick command is received.

        This is called for each simulation step.
        This method must be implemented by subclasses.

        Args:
            request: The tick command request
        """
        pass

    # Optional callbacks with default implementations
    def is_remote_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """
        Check if an agent instance is remote (running on another node).

        Default implementation returns False (treats all agents as local).
        Override this method to implement proper remote agent detection.

        Args:
            agent_instance: The agent instance to check

        Returns:
            True if the agent is remote, False if local
        """
        return False

    def on_agent_instance_sibling_created(self, response: SimTaskInitResponse):
        """
        Called when a sibling agent instance is created (remote agent initialized).

        Default implementation logs the event. Override if needed.

        Args:
            response: The task init response from the remote agent
        """
        logger.info(f"Sibling agent created: {response.source_agent_instance.agent_id}")

    def on_agent_instance_sibling_status_updated(self, report: AgentInstanceStatusReport):
        """
        Called when a sibling agent instance status is updated.

        Default implementation logs the event. Override if needed.

        Args:
            report: The status report from the remote agent
        """
        logger.info(f"Sibling agent status updated: {report.source_agent_instance.agent_id}")

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        Called when a time series calculation request is received.

        Default implementation logs a warning. Override if needed.

        Args:
            request: The calculation request
        """
        logger.warning("Time series calculation received but not implemented")

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        """
        Called when time series data is updated.

        Default implementation logs the event. Override if needed.

        Args:
            request: The data update request
        """
        logger.info("Time series data update received")

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """
        Called when a task termination request is received.

        Default implementation logs the termination. Override to add custom cleanup logic.

        Args:
            request: The task termination request
        """
        logger.info(f"Task termination requested: {request.reason}")

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
