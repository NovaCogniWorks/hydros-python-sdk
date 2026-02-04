"""
Tickable agent base class for tick-driven simulation agents.

This module provides the TickableAgent base class which extends BaseHydroAgent
with tick-driven simulation capabilities and time series data update handling.
"""

import logging
from abc import abstractmethod
from typing import Optional, List, Dict, Any

from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


class TickableAgent(BaseHydroAgent):
    """
    Base class for tick-driven simulation agents.

    This class provides common functionality for agents that:
    1. Execute simulation steps in response to TickCmdRequest
    2. Handle time series data updates (boundary conditions)
    3. Output metrics data via MQTT

    Subclasses:
    - OntologySimulationAgent: Ontology-based simulation
    - TwinsSimulationAgent: Digital twins simulation
    - CentralSchedulingAgent: Central scheduling with MPC optimization

    Key features:
    - Tick-driven execution (responds to TickCmdRequest)
    - Time series data update handling (boundary conditions)
    - MQTT metrics output support
    - Common lifecycle management (init, tick, terminate)

    Subclasses must implement:
    - on_init(): Initialize agent and load configuration
    - on_tick_simulation(): Execute simulation step logic
    - on_terminate(): Clean up resources

    Subclasses can override:
    - on_time_series_data_update(): Handle boundary condition updates
    - send_metrics(): Send metrics data via MQTT
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
        agent_biz_status: AgentBizStatus = AgentBizStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize tickable agent.

        Args:
            sim_coordination_client: Required MQTT client
            agent_id: Unique agent instance ID
            agent_code: Agent code
            agent_type: Agent type
            agent_name: Agent name
            context: Simulation context
            hydros_cluster_id: Cluster ID
            hydros_node_id: Node ID
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

        # Current simulation step
        self._current_step: int = 0

        # Time series data cache (for boundary conditions)
        self._time_series_cache: Dict[str, ObjectTimeSeries] = {}

        logger.info(f"TickableAgent initialized: {self.agent_id}")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the agent.

        Subclasses should:
        1. Load agent configuration using self.load_agent_configuration(request)
        2. Load water network topology if needed
        3. Initialize simulation state
        4. Register with state manager
        5. Return SimTaskInitResponse

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        pass

    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        Handle simulation tick.

        This method:
        1. Sets agent logging context
        2. Updates current step
        3. Calls on_tick_simulation() for subclass-specific logic
        4. Sends metrics data via MQTT
        5. Returns TickCmdResponse

        Args:
            request: Tick command request

        Returns:
            Tick command response
        """
        # Set agent logging context for agent business logic
        self._set_agent_logging_context()

        self._current_step = request.step

        logger.info(f"Processing tick: step={request.step}, commandId={request.command_id}")

        try:
            # Execute simulation step (subclass-specific logic)
            metrics_list = self.on_tick_simulation(request)

            # Send metrics data via MQTT
            if metrics_list:
                self.send_metrics_batch(metrics_list)
                logger.info(f"Sent {len(metrics_list)} metrics for step {request.step}")

            # Create response
            response = TickCmdResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                broadcast=False
            )

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=tick_cmd_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

            return response

        except Exception as e:
            logger.error(f"Error processing tick {request.step}: {e}", exc_info=True)

            # Return failed response
            return TickCmdResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                broadcast=False
            )

    @abstractmethod
    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[Dict[str, Any]]]:
        """
        Execute simulation step logic.

        This is where subclasses implement their specific simulation logic.

        Args:
            request: Tick command request

        Returns:
            List of metrics dictionaries to send via MQTT, or None
            Each metrics dict should contain: object_id, object_name, metrics_code, value
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the agent and clean up resources.

        Subclasses should:
        1. Clean up simulation state
        2. Unregister from state manager
        3. Return SimTaskTerminateResponse

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        pass

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        Handle time series data update (boundary conditions).

        This method:
        1. Sets agent logging context
        2. Extracts time series data from the event
        3. Updates internal cache
        4. Calls on_boundary_condition_update() for subclass-specific handling
        5. Returns TimeSeriesDataUpdateResponse

        Subclasses can override on_boundary_condition_update() to handle
        boundary condition changes.

        Args:
            request: Time series data update request

        Returns:
            Time series data update response
        """
        # Set agent logging context for agent business logic
        self._set_agent_logging_context()

        logger.info(f"Received time series data update: commandId={request.command_id}")

        try:
            # Extract time series data from event
            event = request.time_series_data_changed_event
            if event and event.object_time_series:
                for time_series in event.object_time_series:
                    # Cache time series data by object_id and metrics_code
                    cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._time_series_cache[cache_key] = time_series

                    logger.info(
                        f"Updated time series: object={time_series.object_name}, "
                        f"metrics={time_series.metrics_code}, "
                        f"values={len(time_series.time_series)}"
                    )

                # Call subclass-specific handler
                self.on_boundary_condition_update(event.object_time_series)

            # Create response
            response = TimeSeriesDataUpdateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                broadcast=False
            )

            return response

        except Exception as e:
            logger.error(f"Error handling time series data update: {e}", exc_info=True)

            # Return failed response
            return TimeSeriesDataUpdateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                broadcast=False
            )

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        Handle boundary condition updates.

        Subclasses can override this method to handle boundary condition changes.
        Default implementation does nothing.

        Args:
            time_series_list: List of updated time series data
        """
        pass

    def get_time_series_value(
        self,
        object_id: int,
        metrics_code: str,
        step: Optional[int] = None
    ) -> Optional[float]:
        """
        Get time series value from cache.

        Args:
            object_id: Object ID
            metrics_code: Metrics code
            step: Simulation step (default: current step)

        Returns:
            Time series value, or None if not found
        """
        cache_key = f"{object_id}_{metrics_code}"
        time_series = self._time_series_cache.get(cache_key)

        if not time_series or not time_series.time_series:
            return None

        # Use current step if not specified
        target_step = step if step is not None else self._current_step

        # Find value for the target step
        for ts_value in time_series.time_series:
            if ts_value.step == target_step:
                return ts_value.value

        return None

    def send_metrics_batch(self, metrics_list: List[Dict[str, Any]]):
        """
        Send batch of metrics data via MQTT.

        Args:
            metrics_list: List of metrics dictionaries
                Each dict should contain: object_id, object_name, metrics_code, value
        """
        from hydros_agent_sdk.utils import create_mock_metrics, send_metrics_batch

        # Convert to MqttMetrics objects
        mqtt_metrics_list = []
        for metrics_dict in metrics_list:
            mqtt_metrics = create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=metrics_dict['object_id'],
                object_name=metrics_dict['object_name'],
                step_index=self._current_step,
                metrics_code=metrics_dict['metrics_code'],
                value=metrics_dict['value']
            )
            mqtt_metrics_list.append(mqtt_metrics)

        # Send via MQTT
        metrics_topic = f"{self.sim_coordination_client.topic}/metrics"
        send_metrics_batch(
            mqtt_client=self.sim_coordination_client.mqtt_client,
            topic=metrics_topic,
            metrics_list=mqtt_metrics_list,
            qos=0
        )

    @property
    def current_step(self) -> int:
        """Get current simulation step."""
        return self._current_step
