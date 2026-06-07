from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional, TYPE_CHECKING

from hydros_agent_sdk.protocol.commands import MpcResultReport
from hydros_agent_sdk.protocol.models import HydroAgentInstance, SimulationContext
from hydros_agent_sdk.utils import generate_coordination_command_id

from .models import (
    ControlDeviceResult,
    MpcOptimizeResponse,
    MpcResult,
    MpcResultDetail,
    PredictedResult,
)

if TYPE_CHECKING:
    from hydros_agent_sdk.mpc.task_state import MpcTaskState

logger = logging.getLogger(__name__)

MPC_OPERATION_OPENING = "OPENING"
MPC_OPERATION_WATER_LEVEL = "WATER_LEVEL"


class MpcResultReporter:
    """通过协调通道构建并发布 MPC 结果报告。"""

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
        logger.info(
            "MPC result report prepared for coordinator: biz_scene_instance_id=%s, "
            "step=%s, command_id=%s, result_count=%s, detail_count=%s",
            mpc_task_state.context.biz_scene_instance_id,
            mpc_task_state.current_step,
            report.command_id,
            len(report.mpc_results),
            self._count_details(report),
        )
        client = self.sim_coordination_client or getattr(source_agent_instance, "sim_coordination_client", None)
        if client is None:
            logger.warning(
                "MPC result report built but no coordination client is available: "
                "command_id=%s, result_count=%s, detail_count=%s",
                report.command_id,
                len(report.mpc_results),
                self._count_details(report),
            )
            return report
        client.enqueue(report)
        logger.info(
            "MPC result report enqueued to coordinator: command_id=%s, result_count=%s, detail_count=%s",
            report.command_id,
            len(report.mpc_results),
            self._count_details(report),
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
                for control_device_result in control.control_device_list or []:
                    details.append(cls._control_device_to_detail(control_device_result, control.horizon_step))
                for predicted_result in control.predicted_result_list or []:
                    details.append(cls._predicted_result_to_detail(predicted_result, control.horizon_step))

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
    def _control_device_to_detail(
        control_device_result: ControlDeviceResult,
        horizon_step: Optional[int],
    ) -> MpcResultDetail:
        return MpcResultDetail(
            horizon_step=horizon_step,
            command_type=MPC_OPERATION_OPENING,
            device_type=control_device_result.device_type,
            object_id=control_device_result.object_id,
            device_id=control_device_result.device_id,
            value=control_device_result.value,
        )

    @staticmethod
    def _predicted_result_to_detail(
        predicted_result: PredictedResult,
        horizon_step: Optional[int],
    ) -> MpcResultDetail:
        attributes = {
            "front_water_level": predicted_result.front_water_level,
            "back_water_level": predicted_result.back_water_level,
            "target_water_level": predicted_result.target_water_level,
            "total_flow": predicted_result.total_flow,
        }
        return MpcResultDetail(
            horizon_step=horizon_step,
            command_type=MPC_OPERATION_WATER_LEVEL,
            device_type=predicted_result.object_type,
            object_id=predicted_result.object_id,
            value=predicted_result.front_water_level,
            target_value=predicted_result.target_water_level,
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

    @staticmethod
    def _count_details(report: MpcResultReport) -> int:
        return sum(len(result.details or []) for result in report.mpc_results or [])
