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
from typing import Dict, List, Optional
import logging

from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateRequest,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
    MpcResultReport,
    OutflowTimeSeriesRequest,
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

    def _get_or_create_sibling_agent_cache(self) -> Dict[str, Dict[str, Dict[str, HydroAgentInstance]]]:
        """拿兄弟智能体缓存，按需懒初始化。"""
        cache = getattr(self, "_sibling_agent_instances_by_biz_scene_instance_id", None)
        if cache is None:
            cache = {}
            setattr(self, "_sibling_agent_instances_by_biz_scene_instance_id", cache)
        return cache

    def _get_biz_scene_instance_sibling_cache(
        self,
        biz_scene_instance_id: str,
    ) -> Dict[str, Dict[str, HydroAgentInstance]]:
        cache = self._get_or_create_sibling_agent_cache()
        biz_scene_instance_cache = cache.get(biz_scene_instance_id)
        if biz_scene_instance_cache is None:
            biz_scene_instance_cache = {
                "agent_code": {},
            }
            cache[biz_scene_instance_id] = biz_scene_instance_cache
        return biz_scene_instance_cache

    def _store_sibling_agent_instance(self, agent_instance: HydroAgentInstance) -> None:
        biz_scene_instance_id = agent_instance.context.biz_scene_instance_id
        biz_scene_instance_cache = self._get_biz_scene_instance_sibling_cache(biz_scene_instance_id)

        biz_scene_instance_cache["agent_code"][agent_instance.agent_code] = agent_instance

    def get_sibling_agent_instance(
        self,
        agent_code: str,
        biz_scene_instance_id: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        """按 agent_code 找兄弟智能体。"""
        if not agent_code:
            return None

        cache = self._get_or_create_sibling_agent_cache()
        if biz_scene_instance_id:
            biz_scene_instance_cache = cache.get(biz_scene_instance_id)
            if not biz_scene_instance_cache:
                return None
            return biz_scene_instance_cache["agent_code"].get(agent_code)

        for biz_scene_instance_cache in cache.values():
            agent = biz_scene_instance_cache["agent_code"].get(agent_code)
            if agent is not None:
                return agent
        return None

    def clear_sibling_agent_instances(self, biz_scene_instance_id: Optional[str] = None) -> None:
        """清掉兄弟智能体缓存，避免上下文结束后一直占着内存。"""
        cache = self._get_or_create_sibling_agent_cache()
        if biz_scene_instance_id is None:
            cache.clear()
            return
        cache.pop(biz_scene_instance_id, None)

    def on_agent_instance_sibling_created(self, response: SimTaskInitResponse):
        """
        Called when a sibling agent instance is created (remote agent initialized).

        Default implementation logs the event. Override if needed.

        Args:
            response: The task init response from the remote agent
        """
        for agent_instance in response.created_agent_instances:
            self._store_sibling_agent_instance(agent_instance)
        logger.info(f"Sibling agent created: {response.source_agent_instance.agent_id}")

    def on_agent_instance_sibling_status_updated(self, report: AgentInstanceStatusReport):
        """
        Called when a sibling agent instance status is updated.

        Default implementation logs the event. Override if needed.

        Args:
            report: The status report from the remote agent
        """
        self._store_sibling_agent_instance(report.source_agent_instance)
        logger.info(f"Sibling agent status updated: {report.source_agent_instance.agent_id}")

    def on_mpc_result(self, report: MpcResultReport):
        """
        Called when an MPC result report is received.

        Default implementation only logs the event. Coordinator/data side
        consumers should override this to persist or forward MPC results.
        """
        logger.info(
            "MPC result report received: source=%s, result_count=%s",
            report.source_agent_instance.agent_id,
            len(report.mpc_results),
        )

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

    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest):
        """
        Called when outflow time series data is updated.

        Default implementation logs the event. Override if needed.

        Args:
            request: The outflow data update request
        """
        logger.info("Outflow time series data update received")

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """
        Called when a task termination request is received.

        Default implementation logs the termination. Override to add custom cleanup logic.

        Args:
            request: The task termination request
        """
        self.clear_sibling_agent_instances(request.context.biz_scene_instance_id)
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

    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        Called when outflow time series data is requested.

        Default implementation logs the event. Override if needed.

        Args:
            request: The outflow time series request
        """
        logger.debug("Outflow time series request received")
