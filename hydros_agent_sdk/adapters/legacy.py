from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, MutableMapping, Optional


def _build_context_ref(context: Mapping[str, Any]) -> Dict[str, Any]:
    tenant = context.get("tenant") or {}
    biz_scenario = context.get("biz_scenario") or {}
    waterway = context.get("waterway") or {}
    return {
        "biz_scene_instance_id": context.get("biz_scene_instance_id"),
        "tenant_id": tenant.get("tenant_id"),
        "biz_scenario_id": biz_scenario.get("biz_scenario_id"),
        "waterway_id": waterway.get("waterway_id"),
        "valid": context.get("valid", True),
    }


def _build_legacy_context_from_ref(context_ref: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "biz_scene_instance_id": context_ref.get("biz_scene_instance_id"),
        "tenant": {
            "tenant_id": context_ref.get("tenant_id"),
            "tenant_name": context_ref.get("tenant_id"),
        } if context_ref.get("tenant_id") else None,
        "biz_scenario": {
            "biz_scenario_id": context_ref.get("biz_scenario_id"),
            "biz_scenario_name": context_ref.get("biz_scenario_id"),
        } if context_ref.get("biz_scenario_id") else None,
        "waterway": {
            "waterway_id": context_ref.get("waterway_id"),
            "waterway_name": context_ref.get("waterway_id"),
        } if context_ref.get("waterway_id") else None,
        "valid": context_ref.get("valid", True),
    }


def _build_agent_definition_ref(agent: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "agent_code": agent.get("agent_code"),
        "agent_type": agent.get("agent_type"),
        "agent_name": agent.get("agent_name"),
        "agent_configuration_url": agent.get("agent_configuration_url"),
        "drive_mode": agent.get("drive_mode"),
    }


def _build_legacy_agent_definition_from_ref(agent_ref: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "agent_code": agent_ref.get("agent_code"),
        "agent_type": agent_ref.get("agent_type"),
        "agent_name": agent_ref.get("agent_name"),
        "agent_configuration_url": agent_ref.get("agent_configuration_url"),
        "drive_mode": agent_ref.get("drive_mode"),
    }


def _map_legacy_agent_status(agent_biz_status: Optional[str], agent_instance_status: Optional[str]) -> Optional[str]:
    if agent_biz_status:
        mapped = {
            "INIT": "INIT",
            "IDLE": "IDLE",
            "ACTIVE": "ACTIVE",
            "FAILED": "FAILED",
        }
        return mapped.get(agent_biz_status, agent_biz_status)
    if agent_instance_status in {"RUNNING", "WAITING", "PAUSED"}:
        return "ACTIVE"
    if agent_instance_status in {"READY", "COMPLETED", "CANCELED"}:
        return "IDLE"
    if agent_instance_status == "FAILED":
        return "FAILED"
    return None


def _map_ref_agent_status_to_legacy(agent_status: Optional[str], agent_instance_status: Optional[str]) -> Optional[str]:
    if agent_status:
        mapped = {
            "INIT": "INIT",
            "IDLE": "IDLE",
            "ACTIVE": "ACTIVE",
            "FAILED": "FAILED",
        }
        return mapped.get(agent_status, agent_status)
    if agent_instance_status == "FAILED":
        return "FAILED"
    if agent_instance_status in {"READY", "WAITING", "RUNNING", "PAUSED", "COMPLETED", "CANCELED"}:
        return "ACTIVE"
    return None


def _build_agent_instance_ref(agent_instance: Mapping[str, Any]) -> Dict[str, Any]:
    agent_instance_status = agent_instance.get("agent_instance_status")
    return {
        "agent_id": agent_instance.get("agent_id"),
        "agent_code": agent_instance.get("agent_code"),
        "agent_type": agent_instance.get("agent_type"),
        "biz_scene_instance_id": agent_instance.get("biz_scene_instance_id"),
        "hydros_cluster_id": agent_instance.get("hydros_cluster_id"),
        "hydros_node_id": agent_instance.get("hydros_node_id"),
        "drive_mode": agent_instance.get("drive_mode"),
        "agent_status": _map_legacy_agent_status(
            agent_instance.get("agent_biz_status"),
            agent_instance_status,
        ),
        "agent_instance_status": agent_instance_status,
        "remark": agent_instance.get("remark"),
    }


def _build_legacy_agent_instance_from_ref(agent_instance_ref: Mapping[str, Any],
                                          context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    agent_instance_status = agent_instance_ref.get("agent_instance_status")
    return {
        "agent_id": agent_instance_ref.get("agent_id"),
        "agent_code": agent_instance_ref.get("agent_code"),
        "agent_type": agent_instance_ref.get("agent_type"),
        "agent_name": agent_instance_ref.get("agent_code"),
        "biz_scene_instance_id": agent_instance_ref.get("biz_scene_instance_id"),
        "hydros_cluster_id": agent_instance_ref.get("hydros_cluster_id"),
        "hydros_node_id": agent_instance_ref.get("hydros_node_id"),
        "context": context,
        "agent_biz_status": _map_ref_agent_status_to_legacy(
            agent_instance_ref.get("agent_status"),
            agent_instance_status,
        ),
        "drive_mode": agent_instance_ref.get("drive_mode"),
        "agent_instance_status": agent_instance_status,
        "remark": agent_instance_ref.get("remark"),
    }


def _normalize_event_payload(event_payload: MutableMapping[str, Any]) -> None:
    context = event_payload.get("context")
    if context and not event_payload.get("context_ref"):
        event_payload["context_ref"] = _build_context_ref(context)


def normalize_command_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = deepcopy(dict(payload))

    context = normalized.get("context")
    if context and not normalized.get("context_ref"):
        normalized["context_ref"] = _build_context_ref(context)

    agent_list = normalized.get("agent_list")
    if agent_list and not normalized.get("agent_definition_refs"):
        normalized["agent_definition_refs"] = [
            _build_agent_definition_ref(agent) for agent in agent_list if isinstance(agent, Mapping)
        ]

    source_agent_instance = normalized.get("source_agent_instance")
    if source_agent_instance and not normalized.get("source_agent_instance_ref"):
        normalized["source_agent_instance_ref"] = _build_agent_instance_ref(source_agent_instance)

    target_agent_instance = normalized.get("target_agent_instance")
    if target_agent_instance and not normalized.get("target_agent_instance_ref"):
        normalized["target_agent_instance_ref"] = _build_agent_instance_ref(target_agent_instance)

    if normalized.get("command_type") == "report_agent_instance_status":
        if normalized.get("created_state") and not normalized.get("agent_instance_status"):
            normalized["agent_instance_status"] = normalized["created_state"]

    hydro_event = normalized.get("hydro_event")
    if isinstance(hydro_event, MutableMapping):
        _normalize_event_payload(hydro_event)

    time_series_data_changed_event = normalized.get("time_series_data_changed_event")
    if isinstance(time_series_data_changed_event, MutableMapping):
        _normalize_event_payload(time_series_data_changed_event)

    return normalized


def backfill_legacy_command_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Add legacy rich-model views for old SDK parsing paths without changing
    the canonical contract fields used by contract-first paths.
    """
    normalized = deepcopy(dict(payload))

    context_ref = normalized.get("context_ref")
    if context_ref and not normalized.get("context"):
        normalized["context"] = _build_legacy_context_from_ref(context_ref)

    context = normalized.get("context")

    agent_definition_refs = normalized.get("agent_definition_refs")
    if agent_definition_refs and not normalized.get("agent_list"):
        normalized["agent_list"] = [
            _build_legacy_agent_definition_from_ref(agent_ref)
            for agent_ref in agent_definition_refs
            if isinstance(agent_ref, Mapping)
        ]

    source_agent_instance_ref = normalized.get("source_agent_instance_ref")
    if source_agent_instance_ref and not normalized.get("source_agent_instance"):
        normalized["source_agent_instance"] = _build_legacy_agent_instance_from_ref(
            source_agent_instance_ref,
            context,
        )

    target_agent_instance_ref = normalized.get("target_agent_instance_ref")
    if target_agent_instance_ref and not normalized.get("target_agent_instance"):
        normalized["target_agent_instance"] = _build_legacy_agent_instance_from_ref(
            target_agent_instance_ref,
            context,
        )

    created_agent_instances = normalized.get("created_agent_instances")
    if created_agent_instances and all(isinstance(item, Mapping) for item in created_agent_instances):
        if not any("context" in item for item in created_agent_instances):
            normalized["created_agent_instances"] = [
                _build_legacy_agent_instance_from_ref(item, context)
                for item in created_agent_instances
            ]

    if normalized.get("command_type") == "report_agent_instance_status":
        if normalized.get("agent_instance_status") and not normalized.get("created_state"):
            normalized["created_state"] = normalized["agent_instance_status"]

    return normalized
