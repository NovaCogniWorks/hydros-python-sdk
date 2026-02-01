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
from typing import Optional, Dict, TYPE_CHECKING
from abc import ABC, abstractmethod
from configparser import ConfigParser
from pydantic import Field

from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.callback import SimCoordinationCallback
from hydros_agent_sdk import setup_logging, BaseHydroAgent
from hydros_agent_sdk.agent_properties import AgentProperties

# Import for type checking only to avoid runtime circular imports
if TYPE_CHECKING:
    from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
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

# Configure Hydros logging format (matches Java logback pattern)
# Format: NODE_ID|TIMESTAMP|LEVEL|TASK_ID|BIZ_COMPONENT|TYPE|CONTENT|LOGGER|MESSAGE
setup_logging(
    level=logging.INFO,
    node_id=os.getenv("HYDROS_NODE_ID", "DATA"),  # Get from environment or default to "DATA"
    console=True,
    log_file="logs/agent.log"  # Optional: log to file
)
logger = logging.getLogger(__name__)


class MySampleHydroAgent(BaseHydroAgent):
    """
    Sample implementation of HydroAgent.

    This demonstrates the improved design with:
    - Required sim_coordination_client in constructor
    - Context as member property
    - biz_scene_instance_id as direct property
    - Clear lifecycle methods
    - All configuration loaded from properties file

    Attributes:
        config: Configuration dictionary loaded from properties file
        sim_coordination_client: MQTT coordination client (inherited from BaseHydroAgent)
        state_manager: Agent state manager (inherited from BaseHydroAgent)
        properties: Agent properties with typed accessors (inherited from BaseHydroAgent)
    """

    # Type hints for dynamically set attributes (set via object.__setattr__)
    # These are set in __init__ or inherited from BaseHydroAgent
    # Using Field(exclude=True) to prevent Pydantic from treating these as model fields
    # Using TYPE_CHECKING to provide proper types for IDE without affecting runtime
    if TYPE_CHECKING:
        config: Dict[str, str]
        sim_coordination_client: SimCoordinationClient
        state_manager: 'AgentStateManager'
        properties: AgentProperties

    # Runtime field definitions (excluded from Pydantic validation)
    # Using __annotations__ to avoid type checking errors
    config: Dict[str, str] = Field(default=None, exclude=True)  # type: ignore[assignment]
    sim_coordination_client: SimCoordinationClient = Field(default=None, exclude=True)  # type: ignore[assignment]
    state_manager: 'AgentStateManager' = Field(default=None, exclude=True)  # type: ignore[assignment]
    properties: AgentProperties = Field(default=None, exclude=True)  # type: ignore[assignment]

    def __init__(
        self,
        sim_coordination_client: SimCoordinationClient,
        context: SimulationContext,
        config_file: str = "./agent.properties"
    ):
        """
        Initialize agent with configuration from properties file.

        Args:
            sim_coordination_client: Required MQTT client
            context: Simulation context
            config_file: Path to agent configuration properties file (default: ./agent.properties)
                        Supports relative paths for multi-agent deployments
        """
        # Load configuration from properties file FIRST
        # Use object.__setattr__ to bypass Pydantic validation before super().__init__()
        config = self._load_config(config_file)
        object.__setattr__(self, 'config', config)
        logger.info(f"Loaded configuration from: {config_file}")

        # Parse drive mode from config
        drive_mode_str = self.config.get('drive_mode', 'SIM_TICK_DRIVEN')
        try:
            drive_mode = AgentDriveMode[drive_mode_str]
        except KeyError:
            logger.warning(f"Invalid drive_mode '{drive_mode_str}', using SIM_TICK_DRIVEN")
            drive_mode = AgentDriveMode.SIM_TICK_DRIVEN

        # Generate agent_id
        agent_id = f"{self.config['agent_code']}_{context.biz_scene_instance_id}"

        # Initialize parent with values from config
        # Note: agent_configuration_url is now optional and will be loaded from SimTaskInitRequest
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=self.config['agent_code'],
            agent_type=self.config['agent_type'],
            agent_name=self.config['agent_name'],
            context=context,
            hydros_cluster_id=self.config['hydros_cluster_id'],
            hydros_node_id=self.config['hydros_node_id'],
            agent_biz_status=AgentBizStatus.INIT,
            drive_mode=drive_mode
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

            # Required properties - must be present (agent_configuration_url removed)
            required_props = ['agent_code', 'agent_type', 'agent_name']
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
                'drive_mode': config.get('DEFAULT', 'drive_mode', fallback='SIM_TICK_DRIVEN'),
                'hydros_cluster_id': config.get('DEFAULT', 'hydros_cluster_id', fallback='default_cluster'),
                'hydros_node_id': config.get('DEFAULT', 'hydros_node_id', fallback='default_node')
            }
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            raise

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        Initialize the agent.

        Note: Logging context is automatically set by SimCoordinationClient:
        - task_id = request.context.biz_scene_instance_id
        - biz_component = self.agent_code
        - node_id = from state_manager
        """
        logger.info("="*70)
        logger.info(f"INITIALIZING AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        # Load agent configuration from SimTaskInitRequest
        # This will extract agent_configuration_url from request.agent_list,
        # load the YAML, validate agent_code, and set self.properties
        logger.info("Loading agent configuration from SimTaskInitRequest...")
        self.load_agent_configuration(request)
        logger.info(f"Agent configuration loaded successfully with {len(self.properties)} properties")

        # Access properties using typed accessors
        logger.info("Accessing agent properties...")
        hydros_objects_modeling_url = self.properties.get_property('hydros_objects_modeling_url')

        # Load water network topology objects if URL is provided
        if hydros_objects_modeling_url:
            logger.info("Loading water network topology...")
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
            logger.warning("No hydros_objects_modeling_url configured in properties")

        # Update agent status to ACTIVE
        object.__setattr__(self, 'agent_biz_status', AgentBizStatus.ACTIVE)

        # Register with state manager
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        logger.info(f"Agent initialized: {self.agent_id}")
        logger.info(f"  - Agent Code: {self.agent_code}")
        logger.info(f"  - Agent Type: {self.agent_type}")
        logger.info(f"  - Agent Name: {self.agent_name}")
        logger.info(f"  - Config URL: {self.agent_configuration_url}")
        logger.info(f"  - Drive Mode: {self.drive_mode}")
        logger.info(f"  - Status: {self.agent_biz_status}")

        # Create response
        response = SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,  # self is already a HydroAgentInstance
            created_agent_instances=[self],  # Return self as the created instance
            managed_top_objects={},
            broadcast=False
        )

        # Log in Java-style format (matching coordinator logs)
        logger.info(
            f"发布协调指令成功,commandId={response.command_id},"
            f"commandType=sim_task_init_response 到MQTT Topic={self.sim_coordination_client.topic}"
        )

        return response

    def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
        """
        Handle simulation tick.

        Note: Logging context is automatically set, so logs will include:
        - task_id = request.context.biz_scene_instance_id
        - biz_component = agent_code
        """
        logger.info(f"Received TickCmdRequest, step={request.step}, commandId={request.command_id}")
        logger.info(f"Processing simulation step {request.step}")

        # Your simulation logic here
        # Access context directly: self.context
        # Access biz_scene_instance_id directly: self.biz_scene_instance_id

        # Send mock metrics data via MQTT
        from hydros_agent_sdk.utils import create_mock_metrics, send_metrics

        # Create mock metrics for demonstration
        mock_metrics = create_mock_metrics(
            source_id=self.agent_code,
            job_instance_id=self.biz_scene_instance_id,
            object_id=1001,
            object_name="Gate_01",
            step_index=request.step,
            metrics_code="gate_opening",
            value=0.75 + (request.step % 10) * 0.01  # Mock value that changes with step
        )

        # Send metrics via MQTT
        metrics_topic = f"{self.sim_coordination_client.topic}/metrics"
        send_metrics(
            mqtt_client=self.sim_coordination_client.mqtt_client,
            topic=metrics_topic,
            metrics=mock_metrics,
            qos=0
        )
        logger.info(f"Sent mock metrics: {mock_metrics.metrics_code}={mock_metrics.value} "
                   f"for {mock_metrics.object_name} at step {request.step}")

        # Create response
        response = TickCmdResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,  # self is already a HydroAgentInstance
            broadcast=False
        )

        # Log in Java-style format
        logger.info(
            f"发布协调指令成功,commandId={response.command_id},"
            f"commandType=tick_cmd_response 到MQTT Topic={self.sim_coordination_client.topic}"
        )

        return response

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        Terminate the agent.

        Note: Logging context is automatically set.
        """
        logger.info("="*70)
        logger.info(f"TERMINATING AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)
        logger.info(f"Received SimTaskTerminateRequest, commandId={request.command_id}")
        logger.info(f"Reason: {request.reason or 'Normal termination'}")

        # Clean up resources
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        # Create response
        response = SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,  # self is already a HydroAgentInstance
            broadcast=False
        )

        logger.info(f"Agent terminated: {self.agent_id}")

        # Log in Java-style format
        logger.info(
            f"发布协调指令成功,commandId={response.command_id},"
            f"commandType=sim_task_terminate_response 到MQTT Topic={self.sim_coordination_client.topic}"
        )

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
    ) -> BaseHydroAgent:
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

    def __init__(self, config_file: str = "./agent.properties"):
        """
        Initialize factory with configuration file path.

        Args:
            config_file: Path to agent configuration properties file (default: ./agent.properties)
                        Supports relative paths for multi-agent deployments
        """
        self.config_file = config_file

    def create_agent(
        self,
        sim_coordination_client: SimCoordinationClient,
        context: SimulationContext
    ) -> BaseHydroAgent:
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
        config_file: str = "./agent.properties"
    ):
        """
        Initialize callback with agent factory.

        Args:
            agent_factory: Factory for creating agent instances
            config_file: Path to agent configuration file (default: ./agent.properties)
                        Supports relative paths for multi-agent deployments
        """
        self.agent_factory = agent_factory
        self.config_file = config_file
        self._client: Optional[SimCoordinationClient] = None

        # Load config to get agent code
        self._agent_code = self._load_agent_code()

        # Map: biz_scene_instance_id -> HydroAgent
        self.agents: Dict[str, BaseHydroAgent] = {}

        logger.info(f"MultiAgentCoordinationCallback created for: {self._agent_code}")

    def _load_agent_code(self) -> str:
        """Load agent code from config file."""
        if not os.path.exists(self.config_file):
            logger.warning(f"Config file not found: {self.config_file}, using default agent code")
            return "UNKNOWN_AGENT"

        try:
            config = ConfigParser()
            with open(self.config_file, 'r') as f:
                config_string = '[DEFAULT]\n' + f.read()
            config.read_string(config_string)
            return config.get('DEFAULT', 'agent_code', fallback='UNKNOWN_AGENT')
        except Exception as e:
            logger.error(f"Error loading agent code from config: {e}")
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
        logger.debug(f"SimCoordinationClient reference set for {self._agent_code}")

    def get_component(self) -> str:
        """Get agent code (component name)."""
        return self._agent_code

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


def load_env_config(env_file: str = "./env.properties") -> Dict[str, str]:
    """
    Load environment configuration from properties file.

    Args:
        env_file: Path to environment properties file (default: ./env.properties)
                 Supports relative paths for multi-agent deployments

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
    6. Supports relative paths for multi-agent deployments

    Configuration:
    - Agent properties: loaded from ./agent.properties (relative to working directory)
    - MQTT settings: loaded from ./env.properties (relative to working directory)
    - Supports multiple agent instances in different directories (agent001/, agent002/, etc.)

    Multi-Agent Deployment Example:
        agent001/
            ├── agent.properties  (agent_code=AGENT_001)
            ├── env.properties
            └── run.py
        agent002/
            ├── agent.properties  (agent_code=AGENT_002)
            ├── env.properties
            └── run.py
    """
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load environment configuration (relative to script location)
    ENV_FILE = os.path.join(script_dir, "env.properties")
    env_config = load_env_config(ENV_FILE)

    BROKER_URL = env_config['mqtt_broker_url']
    BROKER_PORT = int(env_config['mqtt_broker_port'])
    TOPIC = env_config['mqtt_topic']

    # Agent configuration file path (relative to script location)
    CONFIG_FILE = os.path.join(script_dir, "agent.properties")

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