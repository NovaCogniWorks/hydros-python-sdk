"""
Central scheduling agent with MPC optimization.

This module provides the CentralSchedulingAgent class which extends TickableAgent
with Model Predictive Control (MPC) optimization capabilities.
"""

import logging
from typing import Optional, List, Dict, Any
from abc import abstractmethod

from .tickable_agent import TickableAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


class CentralSchedulingAgent(TickableAgent):
    """
    Central scheduling agent with MPC optimization.

    This agent performs Model Predictive Control (MPC) optimization:
    1. Executes on rolling optimization horizon (multiple of tick period)
    2. Subscribes to MQTT to receive real-time metrics from field devices
    3. Handles boundary condition updates
    4. Executes MPC optimization
    5. Sends agent-to-agent control commands (future implementation)

    Key features:
    - Rolling horizon optimization (MPC)
    - Real-time metrics subscription via MQTT
    - Boundary condition handling
    - Optimization-based control
    - Agent-to-agent command support (future)

    Usage example:
        ```python
        agent = CentralSchedulingAgent(
            sim_coordination_client=client,
            agent_id="CENTRAL_SCHEDULING_001",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Central Scheduling Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01",
            optimization_horizon=10  # Optimize every 10 ticks
        )
        ```

    Subclasses must implement:
    - on_init(): Initialize agent and load optimization model
    - on_optimization(): Execute MPC optimization logic
    - on_terminate(): Clean up resources
    """

    def __init__(
        self,
        sim_coordination_client,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        optimization_horizon: int = 10,
        agent_biz_status: AgentBizStatus = AgentBizStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize central scheduling agent.

        Args:
            sim_coordination_client: Required MQTT client
            agent_id: Unique agent instance ID
            agent_code: Agent code
            agent_type: Agent type
            agent_name: Agent name
            context: Simulation context
            hydros_cluster_id: Cluster ID
            hydros_node_id: Node ID
            optimization_horizon: Rolling optimization horizon (number of ticks)
            agent_biz_status: Initial business status
            drive_mode: Agent drive mode (default: SIM_TICK_DRIVEN)
            agent_configuration_url: Optional configuration URL
            **kwargs: Additional keyword arguments
        """
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            agent_biz_status=agent_biz_status,
            drive_mode=drive_mode,
            agent_configuration_url=agent_configuration_url,
            **kwargs
        )

        # MPC configuration
        self._optimization_horizon = optimization_horizon
        self._last_optimization_step = 0

        # Optimization model
        self._optimization_model = None
        self._topology = None

        # Real-time metrics cache (from field devices)
        self._field_metrics_cache: Dict[str, Any] = {}

        # MQTT subscription for field metrics
        self._metrics_subscription_topic = None

        logger.info(f"CentralSchedulingAgent initialized: {self.agent_id}")
        logger.info(f"Optimization horizon: {self._optimization_horizon} ticks")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the central scheduling agent.

        Subclasses should:
        1. Load agent configuration using self.load_agent_configuration(request)
        2. Load water network topology
        3. Initialize optimization model
        4. Subscribe to MQTT for field metrics
        5. Register with state manager
        6. Return SimTaskInitResponse

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        pass

    def subscribe_to_field_metrics(self, metrics_topic: str):
        """
        Subscribe to MQTT topic for real-time field metrics.

        This method subscribes to a topic where field devices publish
        their real-time metrics data.

        Args:
            metrics_topic: MQTT topic for field metrics
        """
        logger.info(f"Subscribing to field metrics topic: {metrics_topic}")

        self._metrics_subscription_topic = metrics_topic

        # Subscribe to MQTT topic
        self.sim_coordination_client.mqtt_client.subscribe(
            topic=metrics_topic,
            callback=self._on_field_metrics_received
        )

        logger.info(f"Subscribed to field metrics: {metrics_topic}")

    def _on_field_metrics_received(self, topic: str, payload: Dict[str, Any]):
        """
        Callback for receiving field metrics via MQTT.

        This method is called when field metrics are received.
        It updates the internal cache for use in optimization.

        Args:
            topic: MQTT topic
            payload: Metrics payload
        """
        logger.debug(f"Received field metrics from topic: {topic}")

        try:
            # Extract metrics information
            object_id = payload.get('object_id')
            metrics_code = payload.get('metrics_code')
            value = payload.get('value')
            timestamp = payload.get('timestamp')

            if object_id and metrics_code:
                cache_key = f"{object_id}_{metrics_code}"
                self._field_metrics_cache[cache_key] = {
                    'object_id': object_id,
                    'metrics_code': metrics_code,
                    'value': value,
                    'timestamp': timestamp
                }

                logger.debug(f"Cached field metrics: {cache_key} = {value}")

        except Exception as e:
            logger.error(f"Error processing field metrics: {e}", exc_info=True)

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[Dict[str, Any]]]:
        """
        Execute central scheduling step.

        This method:
        1. Checks if optimization should run (based on horizon)
        2. If yes, executes MPC optimization
        3. Sends control commands to agents (future implementation)
        4. Returns metrics data (optional)

        Args:
            request: Tick command request

        Returns:
            List of metrics dictionaries to send via MQTT (optional)
        """
        logger.info(f"Central scheduling step {request.step}")

        try:
            # Check if optimization should run
            steps_since_last_optimization = request.step - self._last_optimization_step

            if steps_since_last_optimization >= self._optimization_horizon:
                logger.info(
                    f"Executing MPC optimization at step {request.step} "
                    f"(horizon: {self._optimization_horizon})"
                )

                # Execute optimization
                control_commands = self.on_optimization(request.step)

                # Update last optimization step
                self._last_optimization_step = request.step

                # Send control commands to agents (future implementation)
                if control_commands:
                    self._send_control_commands(control_commands)

                logger.info(f"MPC optimization completed at step {request.step}")

            else:
                logger.debug(
                    f"Skipping optimization at step {request.step} "
                    f"(next optimization at step {self._last_optimization_step + self._optimization_horizon})"
                )

            # Return optional metrics
            return None

        except Exception as e:
            logger.error(f"Error in central scheduling step {request.step}: {e}", exc_info=True)
            return None

    @abstractmethod
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        """
        Execute MPC optimization logic.

        Subclasses must implement this method to perform their specific
        MPC optimization logic.

        Args:
            step: Current simulation step

        Returns:
            List of control commands to send to agents, or None
            Each command dict should contain: target_agent, command_type, parameters
        """
        pass

    def _send_control_commands(self, control_commands: List[Dict[str, Any]]):
        """
        Send control commands to target agents.

        This is a placeholder for future agent-to-agent command implementation.

        Args:
            control_commands: List of control commands
        """
        logger.info(f"Sending {len(control_commands)} control commands to agents")

        for command in control_commands:
            target_agent = command.get('target_agent')
            command_type = command.get('command_type')
            parameters = command.get('parameters', {})

            logger.info(
                f"Control command: target={target_agent}, "
                f"type={command_type}, params={parameters}"
            )

            # TODO: Implement agent-to-agent command sending
            # This will be implemented in future versions

    def get_field_metrics_value(
        self,
        object_id: int,
        metrics_code: str
    ) -> Optional[float]:
        """
        Get field metrics value from cache.

        Args:
            object_id: Object ID
            metrics_code: Metrics code

        Returns:
            Field metrics value, or None if not found
        """
        cache_key = f"{object_id}_{metrics_code}"
        metrics_data = self._field_metrics_cache.get(cache_key)

        if metrics_data:
            return metrics_data.get('value')

        return None

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        Handle boundary condition updates for optimization.

        This method updates the optimization model with new boundary conditions.

        Args:
            time_series_list: List of updated time series data
        """
        logger.info(f"Updating optimization model with {len(time_series_list)} boundary conditions")

        # Update optimization model with boundary conditions
        for time_series in time_series_list:
            logger.debug(
                f"Boundary condition: object={time_series.object_name}, "
                f"metrics={time_series.metrics_code}"
            )
            # TODO: Update optimization model constraints

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the central scheduling agent.

        Subclasses should:
        1. Clean up optimization model
        2. Unsubscribe from MQTT topics
        3. Unregister from state manager
        4. Return SimTaskTerminateResponse

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        pass

    @property
    def optimization_horizon(self) -> int:
        """Get optimization horizon (number of ticks)."""
        return self._optimization_horizon

    @property
    def last_optimization_step(self) -> int:
        """Get last optimization step."""
        return self._last_optimization_step
