"""
Practical Example: Agent with Configuration Loading

This example demonstrates how to integrate agent configuration loading
into a real agent implementation using the factory pattern.
"""

import logging
from typing import Dict, Any
from hydros_agent_sdk.agent_config import AgentConfigLoader, AgentConfiguration
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    TerminateRequest,
    TerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    HydroAgent,
    CommandStatus,
    AgentBizStatus,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConfigurableAgent(HydroAgent):
    """
    A configurable agent that loads its configuration from a YAML file.

    This agent demonstrates how to:
    1. Load configuration from URL or file
    2. Extract required configuration values
    3. Use configuration in business logic
    4. Implement the agent lifecycle methods
    """

    def __init__(self, config: AgentConfiguration):
        """
        Initialize agent with configuration.

        Args:
            config: Loaded agent configuration
        """
        super().__init__(
            agent_code=config.get_agent_code(),
            agent_type=config.agent_type,
            agent_name=config.agent_name,
        )

        self.config = config
        self.modeling_url = config.get_hydros_objects_modeling_url()
        self.idz_config_url = config.get_idz_config_url()
        self.time_series_url = config.get_time_series_config_url()

        # Extract simulation parameters
        self.step_resolution = config.get_property('step_resolution', 60)
        self.total_steps = config.get_property('total_steps', 1000)
        self.environment_type = config.get_property('hydro_environment_type', 'NORMAL')

        # Current simulation state
        self.current_step = 0
        self.simulation_context: SimulationContext | None = None

        logger.info(f"Initialized agent: {self.agent_code}")
        logger.info(f"  Modeling URL: {self.modeling_url}")
        logger.info(f"  Step Resolution: {self.step_resolution}s")
        logger.info(f"  Total Steps: {self.total_steps}")

    def initialize(self, context: SimulationContext) -> bool:
        """
        Initialize agent for a simulation task.

        Args:
            context: Simulation context

        Returns:
            True if initialization successful
        """
        logger.info(f"Initializing agent for context: {context.biz_scene_instance_id}")

        self.simulation_context = context
        self.current_step = 0

        # Load modeling data from URL
        if self.modeling_url:
            logger.info(f"Loading hydro objects from: {self.modeling_url}")
            # In real implementation, fetch and parse the modeling data
            # modeling_data = load_modeling_data(self.modeling_url)

        # Load IDZ configuration if available
        if self.idz_config_url:
            logger.info(f"Loading IDZ config from: {self.idz_config_url}")
            # In real implementation, fetch and parse IDZ config
            # idz_config = load_idz_config(self.idz_config_url)

        # Load time series configuration if available
        if self.time_series_url:
            logger.info(f"Loading time series config from: {self.time_series_url}")
            # In real implementation, fetch and parse time series config
            # time_series_config = load_time_series_config(self.time_series_url)

        self.agent_biz_status = AgentBizStatus.ACTIVE
        logger.info("Agent initialization complete")

        return True

    def tick(self, tick_request: TickCmdRequest) -> Dict[str, Any]:
        """
        Process a simulation tick.

        Args:
            tick_request: Tick command request

        Returns:
            Dictionary with tick results
        """
        self.current_step = tick_request.tick_index

        logger.info(
            f"Processing tick {self.current_step}/{self.total_steps} "
            f"at time {tick_request.tick_time}"
        )

        # Perform simulation calculations based on configuration
        # This is where your business logic goes
        results = {
            "tick_index": self.current_step,
            "tick_time": tick_request.tick_time,
            "step_resolution": self.step_resolution,
            "environment_type": self.environment_type,
            "status": "success",
        }

        # Check if simulation is complete
        if self.current_step >= self.total_steps:
            logger.info("Simulation complete")
            self.agent_biz_status = AgentBizStatus.IDLE

        return results

    def terminate(self) -> bool:
        """
        Terminate agent and clean up resources.

        Returns:
            True if termination successful
        """
        logger.info(f"Terminating agent: {self.agent_code}")

        # Clean up resources
        self.simulation_context = None
        self.current_step = 0
        self.agent_biz_status = AgentBizStatus.IDLE

        logger.info("Agent terminated successfully")
        return True


class ConfigurableAgentCallback(SimCoordinationCallback):
    """
    Callback implementation that uses ConfigurableAgent with configuration.
    """

    def __init__(self, config: AgentConfiguration):
        """
        Initialize callback with configuration.

        Args:
            config: Loaded agent configuration
        """
        self.config = config
        self.agents: Dict[str, ConfigurableAgent] = {}

    def on_sim_task_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """Handle simulation task initialization."""
        logger.info(f"Received task init request: {request.command_id}")

        context = request.simulation_context
        context_id = context.biz_scene_instance_id

        try:
            # Create agent instance for this context
            agent = ConfigurableAgent(self.config)
            success = agent.initialize(context)

            if success:
                self.agents[context_id] = agent

                response = SimTaskInitResponse(
                    command_id=request.command_id,
                    command_status=CommandStatus.SUCCEED,
                    simulation_context=context,
                    hydro_agent=agent,
                )
                logger.info(f"Task initialization successful for context: {context_id}")
            else:
                response = SimTaskInitResponse(
                    command_id=request.command_id,
                    command_status=CommandStatus.FAILED,
                    simulation_context=context,
                    error_message="Agent initialization failed",
                )
                logger.error(f"Task initialization failed for context: {context_id}")

            return response

        except Exception as e:
            logger.error(f"Error during task initialization: {e}", exc_info=True)
            return SimTaskInitResponse(
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                simulation_context=context,
                error_message=str(e),
            )

    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """Handle tick command."""
        context_id = request.simulation_context.biz_scene_instance_id
        agent = self.agents.get(context_id)

        if not agent:
            logger.error(f"No agent found for context: {context_id}")
            return TickCmdResponse(
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                simulation_context=request.simulation_context,
                error_message=f"No agent found for context: {context_id}",
            )

        try:
            results = agent.tick(request)

            return TickCmdResponse(
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                simulation_context=request.simulation_context,
                tick_index=request.tick_index,
                tick_time=request.tick_time,
            )

        except Exception as e:
            logger.error(f"Error during tick processing: {e}", exc_info=True)
            return TickCmdResponse(
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                simulation_context=request.simulation_context,
                error_message=str(e),
            )

    def on_terminate(self, request: TerminateRequest) -> TerminateResponse:
        """Handle termination request."""
        context_id = request.simulation_context.biz_scene_instance_id
        agent = self.agents.get(context_id)

        if not agent:
            logger.warning(f"No agent found for context: {context_id}")
            return TerminateResponse(
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                simulation_context=request.simulation_context,
            )

        try:
            success = agent.terminate()

            if success:
                del self.agents[context_id]

            return TerminateResponse(
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED if success else CommandStatus.FAILED,
                simulation_context=request.simulation_context,
            )

        except Exception as e:
            logger.error(f"Error during termination: {e}", exc_info=True)
            return TerminateResponse(
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                simulation_context=request.simulation_context,
                error_message=str(e),
            )


def main():
    """Main function demonstrating agent with configuration loading."""

    # Configuration URL (can be from environment variable or command line)
    config_url = "http://47.97.1.45:9000/hydros/mdm/京石段/agents/twins_simulation/agent_config.yaml"

    # Alternative: Load from local file
    # config = AgentConfigLoader.from_file("config/agent_config.yaml")

    try:
        # Load configuration from URL
        logger.info("Loading agent configuration...")
        config = AgentConfigLoader.from_url(config_url)

        logger.info(f"Configuration loaded successfully:")
        logger.info(f"  Agent Code: {config.get_agent_code()}")
        logger.info(f"  Agent Name: {config.agent_name}")
        logger.info(f"  Version: {config.version}")

        # Create callback with configuration
        callback = ConfigurableAgentCallback(config)

        # Get MQTT configuration from agent config
        mqtt_broker = config.get_mqtt_broker_config()

        if mqtt_broker:
            mqtt_host = mqtt_broker.mqtt_host
            mqtt_port = mqtt_broker.mqtt_port
            logger.info(f"Using MQTT broker from config: {mqtt_host}:{mqtt_port}")
        else:
            # Fallback to default values
            mqtt_host = "localhost"
            mqtt_port = 1883
            logger.info(f"Using default MQTT broker: {mqtt_host}:{mqtt_port}")

        # Create coordination client
        client = SimCoordinationClient(
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            callback=callback,
        )

        # Start the client
        logger.info("Starting coordination client...")
        client.start()

        logger.info("Agent is running. Press Ctrl+C to stop.")

        # Keep the main thread alive
        import time
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down agent...")
        client.stop()
        logger.info("Agent stopped")

    except Exception as e:
        logger.error(f"Error running agent: {e}", exc_info=True)


if __name__ == "__main__":
    main()
