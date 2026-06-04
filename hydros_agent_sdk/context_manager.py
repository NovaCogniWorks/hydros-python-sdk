"""
Runtime hydro model context for central coordination.

This module mirrors the Java central ContextManager pattern: one model context is
kept per simulation task, and sibling-agent init responses populate an object
owner index used by central scheduling commands.
"""

import logging
from threading import RLock
from typing import Any, Dict, List, Optional, Union

from hydros_agent_sdk.protocol.models import HydroAgentInstance, SimulationContext
from hydros_agent_sdk.scenario_config import BizScenarioConfiguration
from hydros_agent_sdk.utils import HydroObjectUtilsV2, WaterwayTopology
from hydros_agent_sdk.utils.yaml_loader import YamlLoader

logger = logging.getLogger(__name__)


class HydroModelContext:
    """Per-task hydro model context and object owner index."""

    def __init__(
        self,
        context: SimulationContext,
        topology: Optional[WaterwayTopology] = None,
        scenario_config: Optional[BizScenarioConfiguration] = None,
    ) -> None:
        self.context = context
        self.topology = topology
        self.scenario_config = scenario_config
        self._object_owner_by_id: Dict[str, HydroAgentInstance] = {}

    @property
    def sim_agent_properties(self):
        if self.scenario_config is None:
            return None
        return self.scenario_config.sim_agent_properties

    @staticmethod
    def _extract_object_id(hydro_object: Any) -> Optional[int]:
        if hydro_object is None:
            return None

        value = None
        if isinstance(hydro_object, dict):
            value = hydro_object.get("object_id")
        else:
            value = getattr(hydro_object, "object_id", None)

        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_child_hydro_objects(hydro_object: Any) -> List[Any]:
        if hydro_object is None:
            return []

        if isinstance(hydro_object, dict):
            children = hydro_object.get("children")
        else:
            children = getattr(hydro_object, "children", None)

        if children is None:
            return []
        if isinstance(children, dict):
            return list(children.values())
        if isinstance(children, list):
            return children
        return []

    def _resolve_full_top_object(self, managed_top_object: Any) -> Any:
        object_id = self._extract_object_id(managed_top_object)
        if object_id is None or self.topology is None:
            return managed_top_object

        return self.topology.get_top_object(object_id) or managed_top_object

    def _index_hydro_object_owner(
        self,
        agent_instance: HydroAgentInstance,
        hydro_object: Any,
    ) -> int:
        indexed_count = 0
        object_id = self._extract_object_id(hydro_object)
        if object_id is not None:
            self._object_owner_by_id[str(object_id)] = agent_instance
            indexed_count += 1

        for child in self._get_child_hydro_objects(hydro_object):
            indexed_count += self._index_hydro_object_owner(agent_instance, child)
        return indexed_count

    def on_agent_instance_sibling_created(
        self,
        agent_instance: HydroAgentInstance,
        managed_top_objects: Optional[List[Any]],
    ) -> int:
        """Index top hydro objects and all known child objects to the owner agent."""
        if not managed_top_objects:
            return 0

        indexed_count = 0
        for managed_top_object in managed_top_objects:
            full_top_object = self._resolve_full_top_object(managed_top_object)
            indexed_count += self._index_hydro_object_owner(agent_instance, full_top_object)
        return indexed_count

    def get_owner_agent_instance(self, object_id: Union[int, str]) -> Optional[HydroAgentInstance]:
        return self._object_owner_by_id.get(str(object_id))


class ContextKeyResolver:
    """Resolve supported context key inputs into biz_scene_instance_id."""

    @staticmethod
    def resolve(context_or_biz_scene_instance_id: Union[SimulationContext, str, None]) -> Optional[str]:
        if context_or_biz_scene_instance_id is None:
            return None

        if isinstance(context_or_biz_scene_instance_id, SimulationContext):
            return context_or_biz_scene_instance_id.biz_scene_instance_id

        return str(context_or_biz_scene_instance_id)


class HydroModelContextRepository:
    """Instance-owned task-scoped hydro model context registry."""

    def __init__(self) -> None:
        self._contexts: Dict[str, HydroModelContext] = {}
        self._lock = RLock()

    def create_from_init_request(self, request: Any) -> Optional[HydroModelContext]:
        """
        Create model context from SimTaskInitRequest scenario configuration.

        Java central does this in SimTaskAgentInitializer#onInit. Python keeps it
        small: only read the scenario config URL, pick the modeling URL, and let
        create() load the topology.
        """
        context = getattr(request, "context", None)
        if context is None:
            return None

        existing = self.get_context(context)
        if existing is not None:
            return existing

        config_url = getattr(request, "biz_scene_configuration_url", None)
        if not config_url:
            return None

        config = YamlLoader.from_url(config_url)
        scenario_config = BizScenarioConfiguration.model_validate(config)
        modeling_url = scenario_config.hydros_objects_modeling_url
        if not modeling_url and scenario_config.sim_agent_properties is None:
            logger.info(
                "Skip hydro model context init: hydros_objects_modeling_url missing, bizSceneInstanceId=%s",
                context.biz_scene_instance_id,
            )
            return None

        return self.create(
            context=context,
            hydros_objects_modeling_url=str(modeling_url) if modeling_url else None,
            scenario_config=scenario_config,
        )

    def create(
        self,
        context: SimulationContext,
        hydros_objects_modeling_url: Optional[str] = None,
        topology: Optional[WaterwayTopology] = None,
        param_keys: Optional[set[str]] = None,
        scenario_config: Optional[BizScenarioConfiguration] = None,
    ) -> HydroModelContext:
        loaded_topology = topology
        if loaded_topology is None and hydros_objects_modeling_url:
            loaded_topology = HydroObjectUtilsV2.build_waterway_topology(
                modeling_yml_uri=hydros_objects_modeling_url,
                param_keys=param_keys,
                with_metrics_code=True,
            )

        model_context = HydroModelContext(
            context=context,
            topology=loaded_topology,
            scenario_config=scenario_config,
        )
        with self._lock:
            self._contexts[context.biz_scene_instance_id] = model_context

        if loaded_topology is None:
            logger.info(
                "Created hydro model context without topology: bizSceneInstanceId=%s",
                context.biz_scene_instance_id,
            )
        else:
            logger.info(
                "Created hydro model context: bizSceneInstanceId=%s, topObjectCount=%s",
                context.biz_scene_instance_id,
                len(loaded_topology.top_objects),
            )
        return model_context

    def get_context(
        self,
        context_or_biz_scene_instance_id: Union[SimulationContext, str, None],
    ) -> Optional[HydroModelContext]:
        biz_scene_instance_id = ContextKeyResolver.resolve(context_or_biz_scene_instance_id)
        if biz_scene_instance_id is None:
            return None

        with self._lock:
            return self._contexts.get(biz_scene_instance_id)

    def get_agent_by_object_id(
        self,
        object_id: Union[int, str],
        biz_scene_instance_id: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        with self._lock:
            if biz_scene_instance_id:
                model_context = self._contexts.get(biz_scene_instance_id)
                if model_context is None:
                    return None
                return model_context.get_owner_agent_instance(object_id)

            for model_context in self._contexts.values():
                owner = model_context.get_owner_agent_instance(object_id)
                if owner is not None:
                    return owner
        return None

    def remove(self, context_or_biz_scene_instance_id: Union[SimulationContext, str, None]) -> None:
        biz_scene_instance_id = ContextKeyResolver.resolve(context_or_biz_scene_instance_id)
        if biz_scene_instance_id is None:
            return

        with self._lock:
            self._contexts.pop(biz_scene_instance_id, None)

    def clear(self) -> None:
        with self._lock:
            self._contexts.clear()


class ContextManager:
    """Compatibility facade for the default hydro model context repository."""

    _default_repository = HydroModelContextRepository()

    @classmethod
    def repository(cls) -> HydroModelContextRepository:
        return cls._default_repository

    @classmethod
    def set_repository(cls, repository: HydroModelContextRepository) -> None:
        cls._default_repository = repository

    @classmethod
    def create_from_init_request(cls, request: Any) -> Optional[HydroModelContext]:
        return cls.repository().create_from_init_request(request)

    @classmethod
    def create(
        cls,
        context: SimulationContext,
        hydros_objects_modeling_url: Optional[str] = None,
        topology: Optional[WaterwayTopology] = None,
        param_keys: Optional[set[str]] = None,
        scenario_config: Optional[BizScenarioConfiguration] = None,
    ) -> HydroModelContext:
        return cls.repository().create(
            context=context,
            hydros_objects_modeling_url=hydros_objects_modeling_url,
            topology=topology,
            param_keys=param_keys,
            scenario_config=scenario_config,
        )

    @classmethod
    def get_context(
        cls,
        context_or_biz_scene_instance_id: Union[SimulationContext, str, None],
    ) -> Optional[HydroModelContext]:
        return cls.repository().get_context(context_or_biz_scene_instance_id)

    @classmethod
    def get_agent_by_object_id(
        cls,
        object_id: Union[int, str],
        biz_scene_instance_id: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        return cls.repository().get_agent_by_object_id(object_id, biz_scene_instance_id)

    @classmethod
    def remove(cls, context_or_biz_scene_instance_id: Union[SimulationContext, str, None]) -> None:
        cls.repository().remove(context_or_biz_scene_instance_id)

    @classmethod
    def clear(cls) -> None:
        cls.repository().clear()
