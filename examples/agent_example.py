"""
Improved agent design with factory pattern and instance management.

This module demonstrates a better architecture where:
1. Each SimulationContext gets its own agent instance
2. Agent instances have clear lifecycle (created on task init, destroyed on terminate)
3. SimCoordinationClient manages multiple agent instances
4. Agent class has clean, required constructor parameters
"""

import time
import logging
import os
from typing import Optional, Dict
from abc import ABC, abstractmethod
from configparser import ConfigParser

from hydros_agent_sdk import agent_config
from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    HydroAgentInstance,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ImprovedAgent")


class HydroAgent(ABC):
    """
    Base class for Hydro agents with improved design.

    Key improvements:
    1. sim_coordination_client is required in constructor (non-null)
    2. context is a member property
    3. biz_scene_instance_id is a direct property
    4. Clear lifecycle: created on task init, destroyed on terminate
    5. Each agent instance corresponds to one simulation task
    """

    def __init__(
        self,
        sim_coordination_client: SimCoordinationClient,
        context: SimulationContext,
        component_name: str,
        hydros_cluster_id: str,
        hydros_node_id: str
    ):
        """
        Initialize agent instance.

        Args:
            sim_coordination_client: Required MQTT client (non-null)
            context: Simulation context for this agent
            component_name: Component name (e.g., "TWINS_SIMULATION_AGENT")
            node_id: Node ID where this agent runs
        """
        # Required parameters
        if sim_coordination_client is None:
            raise ValueError("sim_coordination_client is required")
        if context is None:
            raise ValueError("context is required")

        self.sim_coordination_client = sim_coordination_client
        self.context = context
        self.component_name = component_name
        self.hydros_cluster_id = hydros_cluster_id
        self.hydros_node_id = hydros_node_id

        # Direct property for easy access
        self.biz_scene_instance_id = context.biz_scene_instance_id

        # Agent instance (created during initialization)
        self.hydro_agent_instance: Optional[HydroAgentInstance] = None

        # State manager reference
        self.state_manager = sim_coordination_client.state_manager

        logger.info(f"Created agent for context: {self.biz_scene_instance_id}")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the agent and create HydroAgentInstance.

        This is called when the task is initialized.

        Args:
            request: Task initialization request

        Returns:
            Task initialization response
        """
        pass

    @abstractmethod
    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        Handle simulation tick.

        This is called for each simulation step.

        Args:
            request: Tick command request

        Returns:
            Tick command response
        """
        pass

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the agent and clean up resources.

        This is called when the task is terminated.

        Args:
            request: Task termination request

        Returns:
            Task termination response
        """
        pass

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        Handle time series data update.

        Default implementation. Override if needed.

        Args:
            request: Time series data update request

        Returns:
            Time series data update response
        """
        logger.info(f"Time series data update: {request.command_id}")

        if self.hydro_agent_instance is None:
            raise RuntimeError("Agent instance not initialized")

        return TimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.hydro_agent_instance,
            broadcast=False
        )

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        Handle time series calculation.

        Default implementation. Override if needed.

        Args:
            request: Time series calculation request
        """
        logger.info(f"Time series calculation: {request.command_id}")

    def send_response(self, response):
        """
        Send a response via the coordination client.

        Args:
            response: Response to send
        """
        self.sim_coordination_client.enqueue(response)


class MySampleHydroAgent(HydroAgent):
    """
    Sample implementation of HydroAgent.

    This demonstrates the improved design with:
    - Required sim_coordination_client in constructor
    - Context as member property
    - biz_scene_instance_id as direct property
    - Clear lifecycle methods
    - All configuration loaded from properties file
    """

    def __init__(
        self,
        sim_coordination_client: SimCoordinationClient,
        context: SimulationContext,
        config_file: str = "examples/agent.properties"
    ):
        """
        Initialize agent with configuration from properties file.

        Args:
            sim_coordination_client: Required MQTT client
            context: Simulation context
            config_file: Path to agent configuration properties file (required)
        """
        # Load configuration from properties file FIRST
        self.config = self._load_config(config_file)
        logger.info(f"Loaded configuration from: {config_file}")

        # Initialize parent with values from config
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            context=context,
            component_name=self.config['agent_code'],
            hydros_cluster_id=self.config['hydros_cluster_id'],
            hydros_node_id=self.config['hydros_node_id']
        )

    def _load_config(self, config_file: str) -> Dict[str, str]:
        """
        Load agent configuration from properties file.

        All configuration must be present in the file.

        Args:
            config_file: Path to the properties file

        Returns:
            Dictionary containing configuration values

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If required properties are missing
        """
        # Check if file exists
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file not found: {config_file}")

        config = ConfigParser()

        # Read properties file (supports # comments)
        try:
            # Add a default section for properties files without sections
            with open(config_file, 'r') as f:
                config_string = '[DEFAULT]\n' + f.read()
            config.read_string(config_string)

            # Required properties - must be present
            required_props = ['agent_code', 'agent_type', 'agent_name', 'agent_configuration_url']
            missing_props = []

            for prop in required_props:
                if not config.has_option('DEFAULT', prop):
                    missing_props.append(prop)

            if missing_props:
                raise ValueError(f"Missing required properties in {config_file}: {', '.join(missing_props)}")

            # Load all configuration
            return {
                'agent_code': config.get('DEFAULT', 'agent_code'),
                'agent_type': config.get('DEFAULT', 'agent_type'),
                'agent_name': config.get('DEFAULT', 'agent_name'),
                'agent_configuration_url': config.get('DEFAULT', 'agent_configuration_url'),
                'drive_mode': config.get('DEFAULT', 'drive_mode', fallback='SIM_TICK_DRIVEN'),
                'hydros_cluster_id': config.get('DEFAULT', 'hydros_cluster_id', fallback='default_cluster'),
                'hydros_node_id': config.get('DEFAULT', 'hydros_node_id', fallback='default_node')
            }
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            raise

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """Initialize the agent."""
        logger.info("="*70)
        logger.info(f"INITIALIZING AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        # Parse drive mode from config
        drive_mode_str = self.config.get('drive_mode', 'SIM_TICK_DRIVEN')
        try:
            drive_mode = AgentDriveMode[drive_mode_str]
        except KeyError:
            logger.warning(f"Invalid drive_mode '{drive_mode_str}', using SIM_TICK_DRIVEN")
            drive_mode = AgentDriveMode.SIM_TICK_DRIVEN

        agent_config_url = self.config['agent_configuration_url']

        # Load configuration from URL
        logger.info("Loading agent configuration...")
        agent_config = AgentConfigLoader.from_url(agent_config_url)
        print('================================================')
        print(agent_config)
        print('================================================')

        # Load water network topology objects
        logger.info("Loading water network topology...")
        hydros_objects_modeling_url = agent_config.get_property('hydros_objects_modeling_url')

        if hydros_objects_modeling_url:
            from hydros_agent_sdk.utils import HydroObjectUtilsV2

            # Load topology with specific parameters and metrics
            param_keys = {'max_opening'}
            hydros_objects_modeling = HydroObjectUtilsV2.build_waterway_topology(
                modeling_yml_uri=hydros_objects_modeling_url,
                param_keys=param_keys,
                with_metrics_code=True
            )

            logger.info(f"Loaded topology with {len(hydros_objects_modeling.top_objects)} top-level objects")

            # Example: Access topology information
            for top_obj in hydros_objects_modeling.top_objects[:3]:  # Show first 3 objects
                logger.info(f"  - {top_obj.object_name} ({top_obj.object_type}): "
                          f"{len(top_obj.children)} children")
        else:
            logger.warning("No hydros_objects_modeling_url configured")

        # Create agent instance using configuration from properties file
        self.hydro_agent_instance = HydroAgentInstance(
            agent_id=f"{self.config['agent_code']}_{self.biz_scene_instance_id}",
            agent_code=self.config['agent_code'],
            agent_name=self.config['agent_name'],
            agent_type=self.config['agent_type'],
            agent_biz_status=AgentBizStatus.ACTIVE,
            drive_mode=drive_mode,
            agent_configuration_url=self.config['agent_configuration_url'],
            biz_scene_instance_id=self.biz_scene_instance_id,
            hydros_cluster_id=self.hydros_cluster_id,
            hydros_node_id=self.hydros_node_id,
            context=self.context
        )

        # Register with state manager
        self.state_manager.init_task(self.context, [self.hydro_agent_instance])
        self.state_manager.add_local_agent(self.hydro_agent_instance)

        logger.info(f"Agent initialized: {self.hydro_agent_instance.agent_id}")
        logger.info(f"  - Agent Code: {self.config['agent_code']}")
        logger.info(f"  - Agent Type: {self.config['agent_type']}")
        logger.info(f"  - Agent Name: {self.config['agent_name']}")
        logger.info(f"  - Config URL: {self.config['agent_configuration_url']}")
        logger.info(f"  - Drive Mode: {drive_mode}")

        # Create response
        response = SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.hydro_agent_instance,
            created_agent_instances=[self.hydro_agent_instance],
            managed_top_objects={},
            broadcast=False
        )

        return response

    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """Handle simulation tick."""
        logger.info(f"[{self.biz_scene_instance_id}] Tick: step={request.step}")

        # Your simulation logic here
        # Access context directly: self.context
        # Access biz_scene_instance_id directly: self.biz_scene_instance_id

        if self.hydro_agent_instance is None:
            raise RuntimeError("Agent instance not initialized")

        # Create response
        response = TickCmdResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.hydro_agent_instance,
            broadcast=False
        )

        return response

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """Terminate the agent."""
        logger.info("="*70)
        logger.info(f"TERMINATING AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)
        logger.info(f"Reason: {request.reason}")

        if self.hydro_agent_instance is None:
            raise RuntimeError("Agent instance not initialized")

        # Clean up resources
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self.hydro_agent_instance)

        # Create response
        response = SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.hydro_agent_instance,
            broadcast=False
        )

        logger.info(f"Agent terminated: {self.hydro_agent_instance.agent_id}")

        return response


class AgentFactory(ABC):
    """
    Abstract factory for creating agent instances.

    This allows different agent implementations to be plugged in.
    """

    @abstractmethod
    def create_agent(
        self,
        sim_coordination_client: SimCoordinationClient,
        context: SimulationContext
    ) -> HydroAgent:
        """
        Create a new agent instance.

        Args:
            sim_coordination_client: MQTT client
            context: Simulation context

        Returns:
            New agent instance
        """
        pass


class MySampleAgentFactory(AgentFactory):
    """Factory for creating MySampleHydroAgent instances."""

    def __init__(self, config_file: str = "examples/agent.properties"):
        """
        Initialize factory with configuration file path.

        Args:
            config_file: Path to agent configuration properties file
        """
        self.config_file = config_file

    def create_agent(
        self,
        sim_coordination_client: SimCoordinationClient,
        context: SimulationContext
    ) -> HydroAgent:
        """Create a new MySampleHydroAgent instance."""
        return MySampleHydroAgent(
            sim_coordination_client=sim_coordination_client,
            context=context,
            config_file=self.config_file
        )


class MultiAgentCoordinationCallback(SimCoordinationCallback):
    """
    Coordination callback that manages multiple agent instances.

    This is the bridge between SimCoordinationClient and agent instances.
    It creates a new agent instance for each task and routes messages to the correct agent.

    Design Note:
    This class needs access to SimCoordinationClient to create agents. To avoid circular
    dependency, we use a lazy initialization pattern where the client is passed after
    construction via set_client() method, which is called by the client itself.
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        config_file: str = "examples/agent.properties"
    ):
        """
        Initialize callback with agent factory.

        Args:
            agent_factory: Factory for creating agent instances
            config_file: Path to agent configuration file
        """
        self.agent_factory = agent_factory
        self.config_file = config_file
        self._client: Optional[SimCoordinationClient] = None

        # Load config to get component name
        self._component_name = self._load_component_name()

        # Map: biz_scene_instance_id -> HydroAgent
        self.agents: Dict[str, HydroAgent] = {}

        logger.info(f"MultiAgentCoordinationCallback created for: {self._component_name}")

    def _load_component_name(self) -> str:
        """Load component name from config file."""
        if not os.path.exists(self.config_file):
            logger.warning(f"Config file not found: {self.config_file}, using default component name")
            return "UNKNOWN_AGENT"

        try:
            config = ConfigParser()
            with open(self.config_file, 'r') as f:
                config_string = '[DEFAULT]\n' + f.read()
            config.read_string(config_string)
            return config.get('DEFAULT', 'agent_code', fallback='UNKNOWN_AGENT')
        except Exception as e:
            logger.error(f"Error loading component name from config: {e}")
            return "UNKNOWN_AGENT"

    def set_client(self, client: SimCoordinationClient):
        """
        Set the coordination client reference.

        This is called by SimCoordinationClient after construction to establish
        the bidirectional relationship without circular dependency in constructors.

        Args:
            client: The SimCoordinationClient instance
        """
        self._client = client
        logger.debug(f"SimCoordinationClient reference set for {self._component_name}")

    def get_component(self) -> str:
        """Get component name."""
        return self._component_name

    def is_remote_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """Check if agent is remote."""
        if self._client:
            return self._client.state_manager.is_remote_agent(agent_instance)
        return False

    def on_sim_task_init(self, request: SimTaskInitRequest):
        """
        Handle task initialization by creating a new agent instance.

        This is where the factory pattern shines: we create a new agent for each task.
        """
        context_id = request.context.biz_scene_instance_id

        logger.info(f"Creating new agent for task: {context_id}")

        if self._client is None:
            raise RuntimeError("SimCoordinationClient not set. Call set_client() first.")

        # Create new agent instance using factory
        agent = self.agent_factory.create_agent(
            sim_coordination_client=self._client,
            context=request.context
        )

        # Store agent instance
        self.agents[context_id] = agent

        # Initialize agent
        response = agent.on_init(request)

        # Send response
        agent.send_response(response)

        logger.info(f"Agent created and initialized: {context_id}")

    def on_tick(self, request: TickCmdRequest):
        """Route tick to the correct agent instance."""
        context_id = request.context.biz_scene_instance_id
        agent = self.agents.get(context_id)

        if agent is None:
            logger.error(f"No agent found for context: {context_id}")
            return

        # Handle tick
        response = agent.on_tick(request)

        # Send response
        agent.send_response(response)

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """Route termination to the correct agent instance and clean up."""
        context_id = request.context.biz_scene_instance_id
        agent = self.agents.get(context_id)

        if agent is None:
            logger.error(f"No agent found for context: {context_id}")
            return

        # Terminate agent
        response = agent.on_terminate(request)

        # Send response
        agent.send_response(response)

        # Remove agent from map
        del self.agents[context_id]

        logger.info(f"Agent removed from registry: {context_id}")

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        """Route time series update to the correct agent instance."""
        context_id = request.context.biz_scene_instance_id
        agent = self.agents.get(context_id)

        if agent is None:
            logger.error(f"No agent found for context: {context_id}")
            return

        # Handle update
        response = agent.on_time_series_data_update(request)

        # Send response
        agent.send_response(response)

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """Route calculation to the correct agent instance."""
        context_id = request.context.biz_scene_instance_id
        agent = self.agents.get(context_id)

        if agent is None:
            logger.error(f"No agent found for context: {context_id}")
            return

        # Handle calculation
        agent.on_time_series_calculation(request)

    # Other callback methods with default implementations
    def on_agent_instance_sibling_created(self, response: SimTaskInitResponse):
        logger.info(f"Sibling agent created: {response.source_agent_instance.agent_id}")

    def on_agent_instance_sibling_status_updated(self, report: AgentInstanceStatusReport):
        logger.info(f"Sibling agent status updated: {report.source_agent_instance.agent_id}")


def load_env_config(env_file: str = "examples/env.properties") -> Dict[str, str]:
    """
    Load environment configuration from properties file.

    Args:
        env_file: Path to environment properties file

    Returns:
        Dictionary containing environment configuration

    Raises:
        FileNotFoundError: If env file doesn't exist
        ValueError: If required properties are missing
    """
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"Environment config file not found: {env_file}")

    config = ConfigParser()
    try:
        with open(env_file, 'r') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        # Required properties
        required_props = ['mqtt_broker_url', 'mqtt_broker_port', 'mqtt_topic']
        missing_props = []

        for prop in required_props:
            if not config.has_option('DEFAULT', prop):
                missing_props.append(prop)

        if missing_props:
            raise ValueError(f"Missing required properties in {env_file}: {', '.join(missing_props)}")

        return {
            'mqtt_broker_url': config.get('DEFAULT', 'mqtt_broker_url'),
            'mqtt_broker_port': config.get('DEFAULT', 'mqtt_broker_port'),
            'mqtt_topic': config.get('DEFAULT', 'mqtt_topic')
        }
    except Exception as e:
        logger.error(f"Error loading environment config: {e}")
        raise


def main():
    """
    Main entry point demonstrating the improved architecture.

    Key improvements:
    1. Factory pattern for creating agents
    2. Each task gets its own agent instance
    3. Clear separation of concerns
    4. All configuration loaded from properties files
    5. No hardcoded agent or MQTT properties

    Configuration:
    - Agent properties: loaded from examples/agent.properties
    - MQTT settings: loaded from examples/env.properties
    - See examples/AGENT_CONFIG.md for configuration details
    - Run examples/test_config.py to verify configuration
    """
    # Load environment configuration
    ENV_FILE = "examples/env.properties"
    env_config = load_env_config(ENV_FILE)

    BROKER_URL = env_config['mqtt_broker_url']
    BROKER_PORT = int(env_config['mqtt_broker_port'])
    TOPIC = env_config['mqtt_topic']

    # Agent configuration file path
    CONFIG_FILE = "examples/agent.properties"

    # Create agent factory with configuration file
    # All agent properties will be loaded from the config file
    agent_factory = MySampleAgentFactory(
        config_file=CONFIG_FILE
    )

    # Create multi-agent callback
    callback = MultiAgentCoordinationCallback(
        agent_factory=agent_factory,
        config_file=CONFIG_FILE
    )

    # Create coordination client
    sim_coordination_client = SimCoordinationClient(
        broker_url=BROKER_URL,
        broker_port=BROKER_PORT,
        topic=TOPIC,
        callback=callback
    )

    # Set client reference in callback (breaks circular dependency)
    callback.set_client(sim_coordination_client)

    # Start client
    try:
        logger.info("Starting multi-agent service with improved architecture...")
        logger.info(f"Environment config: {ENV_FILE}")
        logger.info(f"Agent config: {CONFIG_FILE}")
        logger.info(f"MQTT Broker: {BROKER_URL}:{BROKER_PORT}")
        logger.info(f"MQTT Topic: {TOPIC}")

        sim_coordination_client.start()

        logger.info("Service started successfully!")
        logger.info(f"Component: {callback.get_component()}")
        logger.info("Ready to create agent instances for incoming tasks...")
        logger.info("Press Ctrl+C to stop...")

        # Keep running
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Stopping service...")
        sim_coordination_client.stop()
        logger.info("Service stopped")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sim_coordination_client.stop()


if __name__ == "__main__":
    main()