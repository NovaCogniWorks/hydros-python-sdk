"""
Agent factory for creating agent instances.

This module provides the HydroAgentFactory class for creating agent instances
with standardized ID generation and configuration loading.
"""

import os
import logging
import random
import string
from datetime import datetime
from typing import Dict, Optional, Type, TypeVar, Generic, TYPE_CHECKING
from configparser import ConfigParser

from hydros_agent_sdk.protocol.models import SimulationContext

if TYPE_CHECKING:
    from hydros_agent_sdk import BaseHydroAgent, SimCoordinationClient

logger = logging.getLogger(__name__)

# Type variable for agent type (must be a BaseHydroAgent subclass)
AgentType = TypeVar('AgentType', bound='BaseHydroAgent')


def generate_agent_instance_id(agent_code: str) -> str:
    """
    Generate agent instance ID following the Java implementation pattern.

    Format: AGT{yyyyMMddHHmm}{6_random_alphanumeric}_{agent_code}
    Example: AGT202602040856HZ18NF_TWINS_SIMULATION_AGENT

    This matches the Java implementation:
    public static String generateAgentInstanceId(HydroAgent hydroAgent) {
        String timestampStr = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmm"));
        String randomLetters = RandomStringUtils.secure().nextAlphanumeric(6).toUpperCase();
        return "AGT" + timestampStr + randomLetters + "_" + hydroAgent.getAgentCode();
    }

    Args:
        agent_code: The agent code (e.g., "TWINS_SIMULATION_AGENT")

    Returns:
        Generated agent instance ID
    """
    # Generate timestamp string (yyyyMMddHHmm)
    timestamp_str = datetime.now().strftime("%Y%m%d%H%M")

    # Generate 6 random alphanumeric characters (uppercase)
    random_letters = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    # Combine: AGT + timestamp + random + _ + agent_code
    return f"AGT{timestamp_str}{random_letters}_{agent_code}"


class HydroAgentFactory(Generic[AgentType]):
    """
    Factory class for creating Hydro agent instances.

    This class provides common functionality for all agent factories,
    including standardized ID generation and configuration loading.

    Example:
        factory = HydroAgentFactory(
            agent_class=MyTwinsSimulationAgent,
            config_file="./agent.properties",
            env_config=env_config
        )
        agent = factory.create_agent(sim_coordination_client, context)
    """

    def __init__(
        self,
        agent_class: Type[AgentType],
        config_file: str = "./agent.properties",
        env_config: Optional[Dict[str, str]] = None
    ):
        """
        Initialize factory.

        Args:
            agent_class: The agent class to instantiate
            config_file: Path to agent configuration file
            env_config: Optional environment configuration (if not provided, will be loaded from env.properties)
        """
        self.agent_class = agent_class
        self.config_file = config_file
        self.env_config = env_config
        logger.info(f"{self.__class__.__name__} created with config: {config_file}")

    def create_agent(
        self,
        sim_coordination_client: 'SimCoordinationClient',
        context: SimulationContext
    ) -> AgentType:
        """
        Create a new agent instance.

        Args:
            sim_coordination_client: MQTT coordination client
            context: Simulation context

        Returns:
            New agent instance
        """
        # Load agent configuration
        config = self._load_config(self.config_file)

        # Load environment configuration if not provided
        if self.env_config is None:
            from hydros_agent_sdk.config_loader import load_env_config
            # Load from shared env.properties
            script_dir = os.path.dirname(self.config_file)
            env_file = os.path.join(script_dir, "env.properties")
            self.env_config = load_env_config(env_file)

        # Get hydros_cluster_id and hydros_node_id from env_config (required)
        hydros_cluster_id = self.env_config['hydros_cluster_id']
        hydros_node_id = self.env_config['hydros_node_id']

        # Generate agent ID using the standard pattern
        # Format: AGT{yyyyMMddHHmm}{6_random_alphanumeric}_{agent_code}
        agent_id = generate_agent_instance_id(config['agent_code'])

        # Create agent
        agent = self.agent_class(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=config['agent_code'],
            agent_type=config['agent_type'],
            agent_name=config['agent_name'],
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id
        )

        logger.info(f"Created agent: {agent_id}")

        return agent

    def _load_config(self, config_file: str) -> Dict[str, str]:
        """
        Load agent configuration from properties file.

        Args:
            config_file: Path to configuration file

        Returns:
            Configuration dictionary

        Raises:
            FileNotFoundError: If config file does not exist
            ValueError: If required properties are missing
        """
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file not found: {config_file}")

        config = ConfigParser()

        try:
            # Read properties file
            with open(config_file, 'r') as f:
                config_string = '[DEFAULT]\n' + f.read()
            config.read_string(config_string)

            # Required properties
            required_props = ['agent_code', 'agent_type', 'agent_name']
            missing_props = []

            for prop in required_props:
                if not config.has_option('DEFAULT', prop):
                    missing_props.append(prop)

            if missing_props:
                raise ValueError(
                    f"Missing required properties in {config_file}: "
                    f"{', '.join(missing_props)}"
                )

            # Load configuration
            # Note: hydros_cluster_id and hydros_node_id should NOT be in agent.properties
            # They are loaded from env.properties
            return {
                'agent_code': config.get('DEFAULT', 'agent_code'),
                'agent_type': config.get('DEFAULT', 'agent_type'),
                'agent_name': config.get('DEFAULT', 'agent_name'),
            }

        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            raise
