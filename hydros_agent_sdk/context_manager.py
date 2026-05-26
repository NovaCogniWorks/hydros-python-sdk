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
from hydros_agent_sdk.utils import HydroObjectUtilsV2, WaterwayTopology
from hydros_agent_sdk.utils.yaml_loader import YamlLoader

logger = logging.getLogger(__name__)


class HydroModelContext:
    """Per-task hydro model context and object owner index."""

    def __init__(
        self,
        context: SimulationContext,
        topology: Optional[WaterwayTopology] = None,
    ) -> None:
        self.context = context
        self.topology = topology
        self._object_owner_by_id: Dict[str, HydroAgentInstance] = {}

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


class ContextManager:
    """Task-scoped hydro model context registry."""

    _contexts: Dict[str, HydroModelContext] = {}
    _lock = RLock()

    @staticmethod
    def _get_config_value(config: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in config:
                return config[key]

        properties = config.get("properties")
        if isinstance(properties, dict):
            for key in keys:
                if key in properties:
                    return properties[key]
        return None

    @classmethod
    def create_from_init_request(cls, request: Any) -> Optional[HydroModelContext]:
        """
        Create model context from SimTaskInitRequest scenario configuration.

        Java central does this in SimTaskAgentInitializer#onInit. Python keeps it
        small: only read the scenario config URL, pick the modeling URL, and let
        create() load the topology.
        """
        context = getattr(request, "context", None)
        if context is None:
            return None

        existing = cls.get_context(context)
        if existing is not None:
            return existing

        config_url = getattr(request, "biz_scene_configuration_url", None)
        if not config_url:
            return None

        config = YamlLoader.from_url(config_url)
        modeling_url = cls._get_config_value(
            config,
            "hydros_objects_modeling_url",
            "hydrosObjectsModelingUrl",
        )
        if not modeling_url:
            logger.info(
                "Skip hydro model context init: hydrosObjectsModelingUrl missing, bizSceneInstanceId=%s",
                context.biz_scene_instance_id,
            )
            return None

        return cls.create(
            context=context,
            hydros_objects_modeling_url=str(modeling_url),
        )

    @classmethod
    def create(
        cls,
        context: SimulationContext,
        hydros_objects_modeling_url: Optional[str] = None,
        topology: Optional[WaterwayTopology] = None,
        param_keys: Optional[set[str]] = None,
    ) -> HydroModelContext:
        loaded_topology = topology
        if loaded_topology is None and hydros_objects_modeling_url:
            loaded_topology = HydroObjectUtilsV2.build_waterway_topology(
                modeling_yml_uri=hydros_objects_modeling_url,
                param_keys=param_keys,
                with_metrics_code=True,
            )

        model_context = HydroModelContext(context=context, topology=loaded_topology)
        with cls._lock:
            cls._contexts[context.biz_scene_instance_id] = model_context

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

    @classmethod
    def get_context(
        cls,
        context_or_biz_scene_instance_id: Union[SimulationContext, str, None],
    ) -> Optional[HydroModelContext]:
        if context_or_biz_scene_instance_id is None:
            return None

        if isinstance(context_or_biz_scene_instance_id, SimulationContext):
            biz_scene_instance_id = context_or_biz_scene_instance_id.biz_scene_instance_id
        else:
            biz_scene_instance_id = str(context_or_biz_scene_instance_id)

        with cls._lock:
            return cls._contexts.get(biz_scene_instance_id)

    @classmethod
    def get_agent_by_object_id(
        cls,
        object_id: Union[int, str],
        biz_scene_instance_id: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        with cls._lock:
            if biz_scene_instance_id:
                model_context = cls._contexts.get(biz_scene_instance_id)
                if model_context is None:
                    return None
                return model_context.get_owner_agent_instance(object_id)

            for model_context in cls._contexts.values():
                owner = model_context.get_owner_agent_instance(object_id)
                if owner is not None:
                    return owner
        return None

    @classmethod
    def remove(cls, context_or_biz_scene_instance_id: Union[SimulationContext, str, None]) -> None:
        if context_or_biz_scene_instance_id is None:
            return

        if isinstance(context_or_biz_scene_instance_id, SimulationContext):
            biz_scene_instance_id = context_or_biz_scene_instance_id.biz_scene_instance_id
        else:
            biz_scene_instance_id = str(context_or_biz_scene_instance_id)

        with cls._lock:
            cls._contexts.pop(biz_scene_instance_id, None)

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._contexts.clear()
