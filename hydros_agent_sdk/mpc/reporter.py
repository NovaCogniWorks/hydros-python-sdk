from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional, TYPE_CHECKING

from hydros_agent_sdk.protocol.commands import MpcResultReport
from hydros_agent_sdk.protocol.models import HydroAgentInstance, SimulationContext
from hydros_agent_sdk.utils import generate_coordination_command_id

from .models import (
    DeviceOpening,
    MpcOptimizeResponse,
    MpcResult,
    MpcResultDetail,
    TargetNode,
)

if TYPE_CHECKING:
    from hydros_agent_sdk.agents.central_scheduling_agent import MpcTaskState

logger = logging.getLogger(__name__)

MPC_OPERATION_OPENING = "OPENING"
MPC_OPERATION_WATER_LEVEL = "WATER_LEVEL"
DEFAULT_REPORT_HORIZON_STEP_LOG_LIMIT = 2


class MpcResultReporter:
    """Build and publish MPC result reports through the coordination channel."""

    def __init__(self, sim_coordination_client=None):
        self.sim_coordination_client = sim_coordination_client

    def build_report(
        self,
        source_agent_instance: HydroAgentInstance,
        mpc_task_state: "MpcTaskState",
        responses: Iterable[MpcOptimizeResponse],
    ) -> Optional[MpcResultReport]:
        results = self.build_results(mpc_task_state, responses)
        if not results:
            return None
        return MpcResultReport(
            command_id=generate_coordination_command_id(),
            context=source_agent_instance.context,
            source_agent_instance=source_agent_instance,
            mpc_results=results,
            broadcast=True,
        )

    def publish(
        self,
        source_agent_instance: HydroAgentInstance,
        mpc_task_state: "MpcTaskState",
        responses: Iterable[MpcOptimizeResponse],
    ) -> Optional[MpcResultReport]:
        report = self.build_report(source_agent_instance, mpc_task_state, responses)
        if report is None:
            return None
        payload = self._format_report_for_log(report)
        logger.info(
            "MPC result report prepared for coordinator: biz_scene_instance_id=%s, "
            "step=%s, command_id=%s, result_count=%s, payload=%s",
            mpc_task_state.context.biz_scene_instance_id,
            mpc_task_state.current_step,
            report.command_id,
            len(report.mpc_results),
            payload,
        )
        client = self.sim_coordination_client or getattr(source_agent_instance, "sim_coordination_client", None)
        if client is None:
            logger.warning(
                "MPC result report built but no coordination client is available: "
                "command_id=%s, payload=%s",
                report.command_id,
                payload,
            )
            return report
        client.enqueue(report)
        logger.info(
            "MPC result report enqueued to coordinator: command_id=%s, result_count=%s, payload=%s",
            report.command_id,
            len(report.mpc_results),
            payload,
        )
        return report

    @classmethod
    def build_results(
        cls,
        mpc_task_state: "MpcTaskState",
        responses: Iterable[MpcOptimizeResponse],
    ) -> List[MpcResult]:
        context = mpc_task_state.context
        results: List[MpcResult] = []
        for response in responses or []:
            details: List[MpcResultDetail] = []
            for control in response.horizon_controls or []:
                for device_opening in control.opening_list or []:
                    details.append(cls._device_opening_to_detail(device_opening, control.horizon_step))
                for target_node in control.target_node_list or []:
                    details.append(cls._target_node_to_detail(target_node, control.horizon_step))

            results.append(
                MpcResult(
                    biz_scene_instance_id=context.biz_scene_instance_id,
                    waterway_id=cls._context_waterway_id(context),
                    tenant_id=cls._context_tenant_id(context),
                    biz_scenario_id=cls._context_biz_scenario_id(context),
                    step=mpc_task_state.current_step,
                    plan_type=response.plan_type,
                    loss=response.loss,
                    gate_operations=response.gate_operations,
                    gate_amplitude=response.gate_amplitude,
                    details=details,
                )
            )
        return results

    @staticmethod
    def _device_opening_to_detail(
        device_opening: DeviceOpening,
        horizon_step: Optional[int],
    ) -> MpcResultDetail:
        return MpcResultDetail(
            horizon_step=horizon_step,
            command_type=MPC_OPERATION_OPENING,
            device_type=device_opening.device_type,
            node_id=device_opening.node_id,
            object_id=device_opening.object_id,
            value=device_opening.value,
        )

    @staticmethod
    def _target_node_to_detail(
        target_node: TargetNode,
        horizon_step: Optional[int],
    ) -> MpcResultDetail:
        attributes = {
            "water_level": target_node.water_level,
            "out_water_level": target_node.out_water_level,
            "target_water_level": target_node.target_water_level,
            "total_flow": target_node.total_flow,
        }
        return MpcResultDetail(
            horizon_step=horizon_step,
            command_type=MPC_OPERATION_WATER_LEVEL,
            device_type=target_node.device_type,
            node_id=target_node.node_id,
            value=target_node.water_level,
            target_value=target_node.target_water_level,
            attributes=json.dumps(attributes, ensure_ascii=False, separators=(",", ":")),
        )

    @staticmethod
    def _context_tenant_id(context: SimulationContext) -> Optional[str]:
        return context.tenant.tenant_id if context.tenant else None

    @staticmethod
    def _context_biz_scenario_id(context: SimulationContext) -> Optional[str]:
        return context.biz_scenario.biz_scenario_id if context.biz_scenario else None

    @staticmethod
    def _context_waterway_id(context: SimulationContext) -> Optional[str]:
        return context.waterway.waterway_id if context.waterway else None

    @classmethod
    def _format_report_for_log(cls, report: MpcResultReport) -> str:
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        cls._truncate_report_payload_for_log(payload)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _truncate_report_payload_for_log(cls, payload: dict) -> None:
        for result in payload.get("mpc_results") or []:
            details = result.get("details")
            if not isinstance(details, list):
                continue

            total_count = len(details)
            kept_steps = cls._first_horizon_steps(details, DEFAULT_REPORT_HORIZON_STEP_LOG_LIMIT)
            kept_step_set = set(kept_steps)
            result["details"] = [
                detail
                for detail in details
                if detail.get("horizon_step") in kept_step_set
            ]
            result["details_total_count"] = total_count
            result["details_logged_count"] = len(result["details"])
            result["horizon_steps_logged"] = kept_steps
            result["horizon_steps_log_limit"] = DEFAULT_REPORT_HORIZON_STEP_LOG_LIMIT
            result["details_truncated"] = len(result["details"]) < total_count

    @staticmethod
    def _first_horizon_steps(details: List[dict], limit: int) -> List[int]:
        steps: List[int] = []
        for detail in details:
            step = detail.get("horizon_step")
            if step is None or step in steps:
                continue
            steps.append(step)
            if len(steps) >= limit:
                break
        return steps
