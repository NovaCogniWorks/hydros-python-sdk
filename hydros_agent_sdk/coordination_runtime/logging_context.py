"""Logging context helpers for coordination runtime."""

from hydros_agent_sdk.logging_config import (
    set_biz_scene_instance_id,
    set_biz_component,
    set_hydros_cluster_id,
    set_hydros_node_id,
)


class LoggingContextBinder:
    """Binds logging context from state manager, callback, and command."""

    def bind(self, command, state_manager, callback) -> None:
        cluster_id = state_manager.get_cluster_id()
        if cluster_id:
            set_hydros_cluster_id(cluster_id)

        node_id = state_manager.get_node_id()
        if node_id:
            set_hydros_node_id(node_id)

        if hasattr(command, 'context') and command.context:
            biz_scene_instance_id = command.context.biz_scene_instance_id
            if biz_scene_instance_id:
                set_biz_scene_instance_id(biz_scene_instance_id)

        component = callback.get_component()
        if component:
            set_biz_component(component)
