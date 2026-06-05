"""Java-compatible agent instance status transition support."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from hydros_agent_sdk.protocol.commands import (
    AgentInstanceStatusReport,
    SimCoordinationResponse,
)
from hydros_agent_sdk.protocol.models import (
    AgentInstanceStatus,
    AgentStatus,
    CommandStatus,
    HydroAgentInstance,
)
from hydros_agent_sdk.utils import generate_coordination_command_id

logger = logging.getLogger(__name__)


class AgentInstanceStatusSupport:
    """Mirror Java AgentInstanceStatusSupport for Python coordination callbacks."""

    def __init__(self, sim_coordination_client=None):
        self.sim_coordination_client = sim_coordination_client

    def execute_with_status(
        self,
        agent_instance: HydroAgentInstance,
        action: Callable[[], Any],
        phase: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        self.transition_status(
            agent_instance,
            AgentInstanceStatus.RUNNING,
            phase=f"{phase}_STARTED",
            metadata=metadata,
        )

        try:
            result = action()
        except Exception as exc:
            self.transition_status(
                agent_instance,
                AgentInstanceStatus.FAILED,
                phase=f"{phase}_FAILED",
                metadata=self._with_error(metadata, exc),
            )
            raise

        if self._is_failed_result(result):
            self.transition_status(
                agent_instance,
                AgentInstanceStatus.FAILED,
                phase=f"{phase}_FAILED",
                metadata=metadata,
            )
        else:
            self.transition_status(
                agent_instance,
                AgentInstanceStatus.WAITING,
                phase=f"{phase}_COMPLETED",
                metadata=metadata,
            )

        return result

    def transition_status(
        self,
        agent_instance: HydroAgentInstance,
        target_status: AgentInstanceStatus,
        phase: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentInstanceStatusReport]:
        if (
            agent_instance is None
            or getattr(agent_instance, "context", None) is None
            or target_status is None
        ):
            return None

        if getattr(agent_instance, "agent_instance_status", None) == target_status:
            return None

        object.__setattr__(agent_instance, "agent_instance_status", target_status)
        self._sync_agent_status(agent_instance, target_status)

        report = self._build_report(
            agent_instance=agent_instance,
            target_status=target_status,
            phase=phase,
            metadata=metadata,
        )
        self._publish_report(report)
        return report

    def _build_report(
        self,
        agent_instance: HydroAgentInstance,
        target_status: AgentInstanceStatus,
        phase: str,
        metadata: Optional[Dict[str, Any]],
    ) -> AgentInstanceStatusReport:
        return AgentInstanceStatusReport(
            command_id=generate_coordination_command_id(),
            context=agent_instance.context,
            broadcast=True,
            source_agent_instance=agent_instance,
            agent_instance_status=target_status,
            init_result=self._build_init_result(
                agent_instance=agent_instance,
                target_status=target_status,
                phase=phase,
                metadata=metadata,
            ),
        )

    def _publish_report(self, report: AgentInstanceStatusReport) -> None:
        client = self.sim_coordination_client or getattr(
            report.source_agent_instance,
            "sim_coordination_client",
            None,
        )
        if client is None:
            logger.warning(
                "Agent instance status report built but no coordination client is available: "
                "agentId=%s, status=%s",
                report.source_agent_instance.agent_id,
                report.agent_instance_status.value,
            )
            return

        try:
            client.enqueue(report)
            logger.info(
                "Agent instance status report enqueued: agentId=%s, agentCode=%s, "
                "status=%s, phase=%s, commandId=%s",
                report.source_agent_instance.agent_id,
                report.source_agent_instance.agent_code,
                report.agent_instance_status.value,
                (report.init_result or {}).get("phase"),
                report.command_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to enqueue agent instance status report: agentId=%s, status=%s, error=%s",
                report.source_agent_instance.agent_id,
                report.agent_instance_status.value,
                exc,
                exc_info=True,
            )

    @staticmethod
    def _sync_agent_status(
        agent_instance: HydroAgentInstance,
        target_status: AgentInstanceStatus,
    ) -> None:
        if target_status == AgentInstanceStatus.FAILED:
            object.__setattr__(agent_instance, "agent_status", AgentStatus.FAILED)
            return

        if target_status in (
            AgentInstanceStatus.RUNNING,
            AgentInstanceStatus.WAITING,
            AgentInstanceStatus.READY,
        ):
            if agent_instance.agent_status not in (
                AgentStatus.FAILED,
                AgentStatus.TERMINATED,
            ):
                object.__setattr__(agent_instance, "agent_status", AgentStatus.ACTIVE)
            return

        if target_status in (
            AgentInstanceStatus.COMPLETED,
            AgentInstanceStatus.CANCELED,
        ):
            object.__setattr__(agent_instance, "agent_status", AgentStatus.TERMINATED)

    @staticmethod
    def _build_init_result(
        agent_instance: HydroAgentInstance,
        target_status: AgentInstanceStatus,
        phase: str,
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        init_result = {
            "phase": phase,
            "status": target_status.value,
            "agent_id": agent_instance.agent_id,
            "agent_code": agent_instance.agent_code,
            "agent_type": agent_instance.agent_type,
            "biz_scene_instance_id": agent_instance.context.biz_scene_instance_id,
        }
        if metadata:
            for key, value in metadata.items():
                if value is not None:
                    init_result[key] = value
        return init_result

    @classmethod
    def _is_failed_result(cls, result: Any) -> bool:
        if result is None:
            return False

        if isinstance(result, SimCoordinationResponse):
            return result.command_status == CommandStatus.FAILED

        if isinstance(result, list):
            return any(cls._is_failed_result(item) for item in result)

        if isinstance(result, tuple):
            return any(cls._is_failed_result(item) for item in result)

        return False

    @staticmethod
    def _with_error(
        metadata: Optional[Dict[str, Any]],
        exc: Exception,
    ) -> Dict[str, Any]:
        result = dict(metadata or {})
        result["error_message"] = str(exc)
        return result
