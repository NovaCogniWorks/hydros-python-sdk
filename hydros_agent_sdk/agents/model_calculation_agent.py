"""
Model calculation agent for event-driven model calculations.

This module provides the ModelCalculationAgent class which extends BaseHydroAgent
with event-driven model calculation capabilities.
"""

import logging
from typing import Optional, List, Dict, Any
from abc import abstractmethod

from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesCalculationRequest,
    TimeSeriesCalculationResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
    ObjectTimeSeries,
    TimeSeriesValue,
)
from hydros_agent_sdk.protocol.events import HydroEvent

logger = logging.getLogger(__name__)


class ModelCalculationAgent(BaseHydroAgent):
    """
    Event-driven model calculation agent.

    This agent performs one-time model calculations in response to events:
    1. Receives TimeSeriesCalculationRequest from coordinator
    2. Executes complex model calculations (e.g., hydrological models)
    3. Produces ObjectTimeSeries results
    4. Returns TimeSeriesCalculationResponse to coordinator

    Key features:
    - Event-driven execution (not tick-driven)
    - One-time calculation per request
    - Complex model support (weather forecast, hydrological models, etc.)
    - Time series output

    Usage example:
        ```python
        agent = ModelCalculationAgent(
            sim_coordination_client=client,
            agent_id="HYDRO_MODEL_001",
            agent_code="HYDROLOGICAL_MODEL_AGENT",
            agent_type="MODEL_CALCULATION_AGENT",
            agent_name="Hydrological Model Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01",
            drive_mode=AgentDriveMode.EVENT_DRIVEN
        )
        ```

    Subclasses must implement:
    - on_init(): Initialize agent and load model
    - on_model_calculation(): Execute model calculation logic
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
        agent_biz_status: AgentBizStatus = AgentBizStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.EVENT_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize model calculation agent.

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
            drive_mode: Agent drive mode (default: EVENT_DRIVEN)
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

        # Model state
        self._model = None
        self._model_config = {}

        logger.info(f"ModelCalculationAgent initialized: {self.agent_id}")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the model calculation agent.

        Subclasses should:
        1. Load agent configuration using self.load_agent_configuration(request)
        2. Load and initialize the calculation model
        3. Register with state manager
        4. Return SimTaskInitResponse

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        pass

    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        Handle tick command (not applicable for event-driven agents).

        Model calculation agents are event-driven and do not respond to tick commands.
        This method returns a failed response.

        Args:
            request: Tick command request

        Returns:
            Tick command response with FAILED status
        """
        logger.warning(
            f"ModelCalculationAgent received TickCmdRequest (not supported). "
            f"This agent is EVENT_DRIVEN and should not receive tick commands."
        )

        return TickCmdResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.FAILED,
            source_agent_instance=self,
            broadcast=False
        )

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        Handle time series calculation request.

        This method:
        1. Extracts event information from request
        2. Calls on_model_calculation() for subclass-specific logic
        3. Sends TimeSeriesCalculationResponse with results

        Args:
            request: Time series calculation request
        """
        logger.info(f"Received TimeSeriesCalculationRequest, commandId={request.command_id}")
        logger.info(f"Event: {request.hydro_event}")

        try:
            # Execute model calculation (subclass-specific)
            object_time_series_list = self.on_model_calculation(request.hydro_event)

            logger.info(f"Model calculation completed, produced {len(object_time_series_list)} time series")

            # Create response
            response = TimeSeriesCalculationResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                object_time_series_list=object_time_series_list,
                broadcast=False
            )

            # Send response
            self.send_response(response)

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=calculation_response 到MQTT Topic={self.sim_coordination_client.topic}"
            )

        except Exception as e:
            logger.error(f"Error in model calculation: {e}", exc_info=True)

            # Send failed response
            response = TimeSeriesCalculationResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                object_time_series_list=[],
                broadcast=False
            )

            self.send_response(response)

    @abstractmethod
    def on_model_calculation(self, hydro_event: HydroEvent) -> List[ObjectTimeSeries]:
        """
        Execute model calculation logic.

        Subclasses must implement this method to perform their specific
        model calculations (e.g., hydrological model, weather forecast model).

        Args:
            hydro_event: Event that triggered the calculation

        Returns:
            List of ObjectTimeSeries containing calculation results
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the model calculation agent.

        Subclasses should:
        1. Clean up model resources
        2. Unregister from state manager
        3. Return SimTaskTerminateResponse

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        pass

    def create_time_series(
        self,
        object_id: int,
        object_name: str,
        object_type: str,
        metrics_code: str,
        time_series_values: List[Dict[str, Any]],
        time_series_name: Optional[str] = None
    ) -> ObjectTimeSeries:
        """
        Helper method to create ObjectTimeSeries.

        Args:
            object_id: Object ID
            object_name: Object name
            object_type: Object type
            metrics_code: Metrics code
            time_series_values: List of time series values
                Each dict should contain: step, time (optional), value
            time_series_name: Optional time series name

        Returns:
            ObjectTimeSeries instance
        """
        # Convert to TimeSeriesValue objects
        ts_values = []
        for ts_dict in time_series_values:
            ts_value = TimeSeriesValue(
                step=ts_dict.get('step'),
                time=ts_dict.get('time'),
                value=ts_dict.get('value')
            )
            ts_values.append(ts_value)

        # Create ObjectTimeSeries
        return ObjectTimeSeries(
            time_series_name=time_series_name or f"{object_name}_{metrics_code}",
            object_id=object_id,
            object_type=object_type,
            object_name=object_name,
            metrics_code=metrics_code,
            time_series=ts_values
        )
