"""Agent 配置装配服务。"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.agent_constants import (
    CENTRAL_SCHEDULING_AGENT_TYPE,
    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
)

logger = logging.getLogger(__name__)


class AgentConfigurationService:
    """从初始化请求解析并应用 Agent 配置。"""

    def load_into(self, agent, request) -> None:
        matching_agent = self._find_matching_agent(agent, request)
        if matching_agent is None:
            logger.info(
                f"Agent '{agent.agent_code}' not found in SimTaskInitRequest.agent_list, "
                f"skipping configuration loading (this is normal if only initializing a subset of agents)"
            )
            return

        if not matching_agent.agent_configuration_url:
            logger.warning(f"No agent_configuration_url provided for agent '{agent.agent_code}'")
            return

        agent_config_url = AgentConfigLoader.normalize_legacy_public_s3_url(
            matching_agent.agent_configuration_url
        )
        logger.info(f"Loading agent configuration from: {agent_config_url}")

        if self._apply_specialized_config_url(agent, matching_agent, agent_config_url):
            object.__setattr__(agent, "agent_configuration_url", agent_config_url)
            return

        try:
            agent_config = AgentConfigLoader.from_url(agent_config_url)
            self._validate_agent_code(agent, matching_agent, agent_config, agent_config_url)
            self._apply_properties(agent, agent_config)
            object.__setattr__(agent, "agent_configuration_url", agent_config_url)
        except Exception as exc:
            logger.error(f"Failed to load agent configuration from {agent_config_url}: {exc}")
            raise

    def _find_matching_agent(self, agent, request):
        for requested_agent in request.agent_list:
            if requested_agent.agent_code == agent.agent_code:
                return requested_agent

        if self._is_system_default_central_scheduling_agent(agent):
            central_agents = [
                requested_agent
                for requested_agent in request.agent_list
                if getattr(requested_agent, "agent_type", None) == CENTRAL_SCHEDULING_AGENT_TYPE
            ]
            if len(central_agents) == 1:
                matching_agent = central_agents[0]
                logger.info(
                    "Using system default %s to load configuration "
                    "for requested central agent '%s'",
                    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
                    matching_agent.agent_code,
                )
                return matching_agent

        return None

    @staticmethod
    def _is_system_default_central_scheduling_agent(agent) -> bool:
        return (
            agent.agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
            and agent.agent_type == CENTRAL_SCHEDULING_AGENT_TYPE
        )

    @staticmethod
    def _apply_specialized_config_url(agent, matching_agent, agent_config_url: str) -> bool:
        agent_type = getattr(matching_agent, "agent_type", None) or getattr(agent, "agent_type", None)
        if agent_type != CENTRAL_SCHEDULING_AGENT_TYPE:
            return False

        config_kind = AgentConfigurationService._detect_specialized_config_kind(agent_config_url)
        if config_kind is None:
            return False

        property_key = (
            "mpc_config_url"
            if config_kind == "mpc"
            else "target_and_constrain_config_url"
        )
        agent.properties.update({property_key: agent_config_url})
        logger.info(
            "Treating %s as %s for central scheduling agent '%s'",
            agent_config_url,
            property_key,
            agent.agent_code,
        )
        return True

    @staticmethod
    def _detect_specialized_config_kind(agent_config_url: str) -> str | None:
        parsed = urlparse(agent_config_url)
        path = (parsed.path or agent_config_url).lower()
        filename = path.rsplit("/", 1)[-1]

        if "mpc_config" in filename:
            return "mpc"
        if "target_and_constrain" in filename or "constraint" in filename or "control" in filename:
            return "target_and_constrain"
        return None

    @staticmethod
    def _validate_agent_code(agent, matching_agent, agent_config, agent_config_url: str) -> None:
        allowed_agent_codes = {agent.agent_code, agent.agent_type}
        if getattr(matching_agent, "agent_code", None):
            allowed_agent_codes.add(matching_agent.agent_code)
        if getattr(matching_agent, "agent_type", None):
            allowed_agent_codes.add(matching_agent.agent_type)

        if agent_config.agent_code not in allowed_agent_codes:
            raise ValueError(
                f"Agent code mismatch: expected one of {sorted(allowed_agent_codes)}, "
                f"but YAML contains '{agent_config.agent_code}'. "
                f"Please check the agent_configuration_url: {agent_config_url}"
            )

        logger.info(
            f"Agent configuration validated successfully for '{agent.agent_code}' "
            f"(YAML agent_code: '{agent_config.agent_code}')"
        )

    @staticmethod
    def _apply_properties(agent, agent_config) -> None:
        if agent_config.properties:
            properties_dict = agent_config.properties.model_dump(exclude_none=True)
            agent.properties.update(properties_dict)

        for component in agent_config.components or []:
            if not component.enabled or not component.properties:
                continue
            component_properties = component.properties.model_dump(exclude_none=True)
            agent.properties.update(component_properties)

        logger.info(f"Loaded {len(agent.properties)} properties from configuration")
        logger.debug(f"Properties: {list(agent.properties.keys())}")
