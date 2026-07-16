"""
用于创建智能体实例的 agent 工厂。

本模块提供 HydroAgentFactory，用于通过标准化 ID 生成和配置加载创建智能体实例。
"""

import os
import logging
from typing import Dict, Optional, Type, TypeVar, Generic, TYPE_CHECKING
from configparser import ConfigParser

from hydros_agent_sdk.utils import generate_agent_instance_id
from hydros_agent_sdk.protocol.models import SimulationContext
from hydros_agent_sdk.agent_constants import (
    CENTRAL_SCHEDULING_AGENT_TYPE,
    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
)

if TYPE_CHECKING:
    from hydros_agent_sdk.base_agent import BaseHydroAgent
    from hydros_agent_sdk.coordination_client import SimCoordinationClient
    from hydros_agent_sdk.developer_api import CustomAgent

logger = logging.getLogger(__name__)

# 智能体类型变量（必须是 BaseHydroAgent 子类）
AgentType = TypeVar('AgentType', bound='BaseHydroAgent')


class HydroAgentFactory(Generic[AgentType]):
    """
    创建 Hydro 智能体实例的工厂类。

    该类为全部智能体工厂提供通用能力，包括标准化 ID 生成和配置加载。

    示例：
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
        初始化工厂。

        Args:
            agent_class: 要实例化的智能体类
            config_file: 智能体配置文件路径
            env_config: 可选环境配置（未提供时从 env.properties 加载）
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
        创建新的智能体实例。

        Args:
            sim_coordination_client: MQTT 协调客户端
            context: 仿真上下文

        Returns:
            新的智能体实例
        """
        # 加载智能体配置
        config = self._load_config(self.config_file)

        # 未提供环境配置时自动加载
        if self.env_config is None:
            from hydros_agent_sdk.config_loader import load_env_config
            # 从共享 env.properties 加载
            script_dir = os.path.dirname(self.config_file)
            env_file = os.path.join(script_dir, "env.properties")
            self.env_config = load_env_config(env_file)

        # 从 env_config 获取必填的 hydros_cluster_id 和 hydros_node_id
        hydros_cluster_id = self.env_config['hydros_cluster_id']
        hydros_node_id = self.env_config['hydros_node_id']

        # 使用标准模式生成智能体 ID
        # 格式：AGT{yyyyMMddHHmm}{6_random_alphanumeric}_{agent_code}
        agent_id = generate_agent_instance_id(config['agent_code'])

        # 创建智能体
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
        从 properties 文件加载智能体配置。

        Args:
            config_file: 配置文件路径

        Returns:
            配置字典

        Raises:
            FileNotFoundError: 配置文件不存在时抛出
            ValueError: 缺少必填属性时抛出
        """
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file not found: {config_file}")

        config = ConfigParser()

        try:
            # 读取 properties 文件
            with open(config_file, "r") as config_stream:
                config_string = "[DEFAULT]\n" + config_stream.read()
            config.read_string(config_string)

            # 必填属性
            required_props = ["agent_code", "agent_type", "agent_name"]
            missing_props = []

            for prop in required_props:
                if not config.has_option("DEFAULT", prop):
                    missing_props.append(prop)

            if missing_props:
                raise ValueError(
                    f"Missing required properties in {config_file}: "
                    f"{', '.join(missing_props)}"
                )

            # 加载配置
            # 注意：hydros_cluster_id 和 hydros_node_id 不应放在 agent.properties 中，
            # 它们从 env.properties 加载。
            return {
                "agent_code": config.get("DEFAULT", "agent_code"),
                "agent_type": config.get("DEFAULT", "agent_type"),
                "agent_name": config.get("DEFAULT", "agent_name"),
            }
        except Exception as error:
            logger.error(f"Error loading config file: {error}")
            raise


class CustomAgentFactory(HydroAgentFactory):
    """Create the internal runtime adapter for a developer ``CustomAgent``."""

    def __init__(
        self,
        custom_agent_class: Type['CustomAgent'],
        config_file: str = "./agent.properties",
        env_config: Optional[Dict[str, str]] = None,
    ):
        from hydros_agent_sdk.runtime.custom_agent_runtime_adapter import CustomAgentRuntimeAdapter

        super().__init__(CustomAgentRuntimeAdapter, config_file=config_file, env_config=env_config)
        self.custom_agent_class = custom_agent_class

    def create_agent(self, sim_coordination_client: 'SimCoordinationClient', context: SimulationContext):
        config = self._load_config(self.config_file)
        if self.env_config is None:
            from hydros_agent_sdk.config_loader import load_env_config

            self.env_config = load_env_config(os.path.join(os.path.dirname(self.config_file), "env.properties"))

        custom_agent = self.custom_agent_class()
        return self.agent_class(
            custom_agent=custom_agent,
            sim_coordination_client=sim_coordination_client,
            agent_id=generate_agent_instance_id(config["agent_code"]),
            agent_code=config["agent_code"],
            agent_type=config["agent_type"],
            agent_name=config["agent_name"],
            context=context,
            hydros_cluster_id=self.env_config["hydros_cluster_id"],
            hydros_node_id=self.env_config["hydros_node_id"],
        )
class SystemCentralSchedulingAgentFactory:
    """内置 CENTRAL_SCHEDULING_AGENT 的工厂。"""

    agent_type = CENTRAL_SCHEDULING_AGENT_TYPE

    def __init__(self, env_config: Optional[Dict[str, str]] = None):
        self.env_config = env_config

    def create_agent(
        self,
        sim_coordination_client: 'SimCoordinationClient',
        context: SimulationContext
    ):
        from hydros_agent_sdk.agents.system_central_scheduling_agent import SystemCentralSchedulingAgent
        from hydros_agent_sdk.runtime.env_settings import load_runtime_env_settings

        settings = load_runtime_env_settings(env_config=self.env_config)
        if self.env_config is None:
            self.env_config = settings.raw
        hydros_cluster_id = (
            settings.hydros_cluster_id
            or sim_coordination_client.state_manager.get_cluster_id()
            or "hydros-k3s-staging"
        )
        hydros_node_id = settings.hydros_node_id or sim_coordination_client.state_manager.get_node_id() or "LOCAL"

        agent_code = SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
        agent_id = generate_agent_instance_id(agent_code)

        agent = SystemCentralSchedulingAgent(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=self.agent_type,
            agent_name="中央调度智能体",
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            mpc_service_base_url=settings.mpc_service_base_url,
            mpc_request_timeout_seconds=settings.mpc_request_timeout_seconds,
        )

        logger.info(f"Created system central scheduling agent: {agent_id}")
        return agent
