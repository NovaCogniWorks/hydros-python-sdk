"""配置解析辅助对象，用于 MPC。"""

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.utils.property_parse_utils import PropertyParseUtils

if TYPE_CHECKING:
    from hydros_agent_sdk.runtime.env_settings import RuntimeEnvSettings


@dataclass(frozen=True)
class MpcRuntimeConfig:
    mpc_config_url: Optional[str] = None
    target_and_constrain_config_url: Optional[str] = None
    mpc_service_base_url: Optional[str] = None


class MpcConfigResolver:
    """从 agent properties 和运行时默认值解析 MPC 配置。"""

    @classmethod
    def resolve(
        cls,
        properties: AgentProperties,
        configured_mpc_config_url: Optional[str] = None,
        configured_target_and_constrain_config_url: Optional[str] = None,
        configured_mpc_service_base_url: Optional[str] = None,
        runtime_settings: Optional["RuntimeEnvSettings"] = None,
    ) -> MpcRuntimeConfig:
        return MpcRuntimeConfig(
            mpc_config_url=cls.get_mpc_config_url(properties, configured_mpc_config_url),
            target_and_constrain_config_url=cls.get_target_and_constrain_config_url(
                properties,
                configured_target_and_constrain_config_url,
            ),
            mpc_service_base_url=cls.get_mpc_service_base_url(
                properties,
                configured_mpc_service_base_url,
                runtime_settings=runtime_settings,
            ),
        )

    @staticmethod
    def get_mpc_config_url(
        properties: AgentProperties,
        configured_url: Optional[str] = None,
    ) -> Optional[str]:
        return PropertyParseUtils.get_string(properties, "mpc_config_url", configured_url)

    @staticmethod
    def get_target_and_constrain_config_url(
        properties: AgentProperties,
        configured_url: Optional[str] = None,
    ) -> Optional[str]:
        return PropertyParseUtils.get_string(
            properties,
            "target_and_constrain_config_url",
            configured_url,
        )

    @staticmethod
    def get_mpc_service_base_url(
        properties: AgentProperties,
        configured_url: Optional[str] = None,
        runtime_settings: Optional["RuntimeEnvSettings"] = None,
    ) -> Optional[str]:
        configured_url = PropertyParseUtils.get_string(
            properties,
            "mpc_service_base_url",
            configured_url,
        )
        if configured_url:
            return configured_url

        if runtime_settings is None:
            from hydros_agent_sdk.runtime.env_settings import load_runtime_env_settings

            runtime_settings = load_runtime_env_settings()
        settings = runtime_settings
        return settings.mpc_service_base_url
