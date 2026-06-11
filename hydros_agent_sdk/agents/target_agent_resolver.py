"""中央调度控制指令的目标智能体解析。"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.protocol.models import HydroAgentInstance, SimulationContext

logger = logging.getLogger(__name__)


class TargetAgentResolver:
    """按 agent_code 或水利对象归属查找目标智能体。"""

    def __init__(
        self,
        sim_coordination_client,
        context: Optional[SimulationContext],
        object_agent_code_map_getter: Callable[[], Dict[str, str]],
    ):
        self.sim_coordination_client = sim_coordination_client
        self.context = context
        self._object_agent_code_map_getter = object_agent_code_map_getter

    def get_sibling_agent_instance(self, agent_code: str) -> Optional[HydroAgentInstance]:
        callback = getattr(self.sim_coordination_client, "sim_coordination_callback", None)
        if callback is None:
            return None

        getter = getattr(callback, "get_sibling_agent_instance", None)
        if getter is None:
            return None

        biz_scene_instance_id = self.context.biz_scene_instance_id if self.context else None
        try:
            return getter(agent_code=agent_code, biz_scene_instance_id=biz_scene_instance_id)
        except TypeError:
            return getter(agent_code)

    def resolve_target_agent_for_object(
        self,
        object_id: Optional[int],
        device_type: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        if object_id is None:
            return None

        agent_code = self.resolve_configured_agent_code_for_object(object_id)
        if agent_code:
            target_agent = self.get_sibling_agent_instance(agent_code)
            if target_agent is not None:
                return target_agent
            logger.warning(
                "Configured object-agent mapping resolved agent_code but sibling agent is unavailable: "
                "objectId=%s, deviceType=%s, agentCode=%s",
                object_id,
                device_type,
                agent_code,
            )

        callback = getattr(self.sim_coordination_client, "sim_coordination_callback", None)
        if callback is None:
            return None

        resolver = getattr(callback, "get_agent_by_object_id", None)
        if resolver is None:
            return None

        biz_scene_instance_id = self.context.biz_scene_instance_id if self.context else None
        try:
            return resolver(object_id=object_id, biz_scene_instance_id=biz_scene_instance_id)
        except TypeError:
            return resolver(object_id)

    def resolve_configured_agent_code_for_object(self, object_id: int) -> Optional[str]:
        object_agent_code_map = self._object_agent_code_map_getter()
        agent_code = object_agent_code_map.get(str(object_id))
        if agent_code:
            return agent_code

        model_context = ContextManager.get_context(self.context)
        topology = getattr(model_context, "topology", None) if model_context is not None else None
        if topology is None:
            return None

        parent_id = topology.child_to_parent_map.get(int(object_id))
        if parent_id is None:
            return None
        return object_agent_code_map.get(str(parent_id))
