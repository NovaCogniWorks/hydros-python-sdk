from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional, TYPE_CHECKING

from hydros_agent_sdk.protocol.commands import MpcPredictionResultReport
from hydros_agent_sdk.protocol.mpc_prediction_results import MpcPredictionResult, MpcPredictionResultDetail
from hydros_agent_sdk.protocol.models import HydroAgentInstance, SimulationContext
from hydros_agent_sdk.utils import generate_coordination_command_id

from .models import (
    ControlObjectResult,
    HorizonStep,
    MpcOptimizeResponse,
    PredictedResult,
)

if TYPE_CHECKING:
    from hydros_agent_sdk.scheduling_task_state import SchedulingTaskState

logger = logging.getLogger("hydros_agent_sdk.mpc.reporter")

MPC_DEVICE_CONTROL = "OPENING"
MPC_OPERATION_WATER_FLOW = "WATER_FLOW"
MPC_OPERATION_WATER_LEVEL = "WATER_LEVEL"
MPC_PLAN_DISPATCH_PENDING = "PENDING"


class MpcPredictionResultReporter:
    """通过协调通道构建并发布 MPC 预测结果报告。"""

    def __init__(self, sim_coordination_client=None):
        self.sim_coordination_client = sim_coordination_client

    def build_report(
        self,
        source_agent_instance: HydroAgentInstance,
        mpc_task_state: "SchedulingTaskState",
        responses: Iterable[MpcOptimizeResponse],
    ) -> Optional[MpcPredictionResultReport]:
        results = self.build_prediction_results(mpc_task_state, responses)
        if not results:
            return None
        return MpcPredictionResultReport(
            command_id=generate_coordination_command_id(),
            context=source_agent_instance.context,
            source_agent_instance=source_agent_instance,
            mpc_prediction_results=results,
            broadcast=True,
        )

    def build_customize_report(
        self,
        source_agent_instance: Optional[HydroAgentInstance],
        mpc_task_state: Optional["SchedulingTaskState"],
        horizon_step: Optional[List[HorizonStep]] = None,
        plan_type: Optional[str] = None,
    ) -> Optional[MpcPredictionResultReport]:
        result = self.build_customize_prediction_result(
            mpc_task_state=mpc_task_state,
            horizon_step=horizon_step,
            plan_type=plan_type,
        )
        if result is None:
            return None
        return MpcPredictionResultReport(
            command_id=generate_coordination_command_id(),
            context=source_agent_instance.context if source_agent_instance else None,
            source_agent_instance=source_agent_instance,
            mpc_prediction_results=[result],
            broadcast=True,
        )

    def publish(
        self,
        source_agent_instance: HydroAgentInstance,
        mpc_task_state: "SchedulingTaskState",
        responses: Iterable[MpcOptimizeResponse],
    ) -> Optional[MpcPredictionResultReport]:
        report = self.build_report(source_agent_instance, mpc_task_state, responses)
        if report is None:
            return None

        client = self.sim_coordination_client or getattr(source_agent_instance, "sim_coordination_client", None)
        if client is None:
            logger.warning(
                "MPC prediction result report built but no coordination client is available: "
                "command_id=%s, result_count=%s, detail_count=%s",
                report.command_id,
                len(report.mpc_prediction_results),
                self._count_details(report),
            )
            return report
        logger.info(
            "MPC prediction result report prepared for coordinator: "
            "command_id=%s, biz_scene_instance_id=%s, result_count=%s, detail_count=%s",
            report.command_id,
            report.context.biz_scene_instance_id if report.context else None,
            len(report.mpc_prediction_results),
            self._count_details(report),
        )
        client.enqueue(report)
        logger.info(
            "MPC prediction result report enqueued to coordinator: command_id=%s, result_count=%s, detail_count=%s",
            report.command_id,
            len(report.mpc_prediction_results),
            self._count_details(report),
        )
        return report

    def publish_customize_report(
        self,
        source_agent_instance: Optional[HydroAgentInstance],
        mpc_task_state: Optional["SchedulingTaskState"],
        horizon_step: Optional[List[HorizonStep]] = None,
        plan_type: Optional[str] = None,
    ) -> Optional[MpcPredictionResultReport]:
        report = self.build_customize_report(
            source_agent_instance=source_agent_instance,
            mpc_task_state=mpc_task_state,
            horizon_step=horizon_step,
            plan_type=plan_type,
        )
        if report is None:
            return None

        client = self.sim_coordination_client or getattr(source_agent_instance, "sim_coordination_client", None)
        if client is None:
            logger.warning(
                "MPC customize prediction result report built but no coordination client is available: "
                "command_id=%s, result_count=%s, detail_count=%s",
                report.command_id,
                len(report.mpc_prediction_results),
                self._count_details(report),
            )
            return report
        logger.info(
            "MPC customize prediction result report prepared for coordinator: "
            "command_id=%s, biz_scene_instance_id=%s, result_count=%s, detail_count=%s",
            report.command_id,
            report.context.biz_scene_instance_id if report.context else None,
            len(report.mpc_prediction_results),
            self._count_details(report),
        )
        client.enqueue(report)
        logger.info(
            "MPC customize prediction result report enqueued to coordinator: command_id=%s, result_count=%s, detail_count=%s",
            report.command_id,
            len(report.mpc_prediction_results),
            self._count_details(report),
        )
        return report

    @classmethod
    def build_prediction_results(
        cls,
        mpc_task_state: "SchedulingTaskState",
        responses: Iterable[MpcOptimizeResponse],
    ) -> List[MpcPredictionResult]:
        context = mpc_task_state.context
        results: List[MpcPredictionResult] = []
        for response in responses or []:
            results.append(
                cls.build_customize_prediction_result(
                    mpc_task_state=mpc_task_state,
                    horizon_step=response.horizon_controls,
                    plan_type=response.plan_type,
                    loss=response.loss,
                    gate_operations=response.gate_operations,
                    gate_amplitude=response.gate_amplitude,
                )
            )
        return results

    @classmethod
    def build_customize_prediction_result(
        cls,
        mpc_task_state: Optional["SchedulingTaskState"],
        horizon_step: Optional[List[HorizonStep]] = None,
        plan_type: Optional[str] = None,
        loss: Optional[float] = None,
        gate_operations: Optional[int] = None,
        gate_amplitude: Optional[float] = None,
    ) -> MpcPredictionResult:
        context = mpc_task_state.context if mpc_task_state else None
        details: List[MpcPredictionResultDetail] = []
        for control in horizon_step or []:
            for control_object_result in control.control_object_list or []:
                details.append(cls._control_object_to_detail(control_object_result, control.horizon_step))
            for predicted_result in control.predicted_result_list or []:
                details.append(cls._predicted_result_to_detail(predicted_result, control.horizon_step))

        return MpcPredictionResult(
            biz_scene_instance_id=context.biz_scene_instance_id if context else "",
            waterway_id=cls._context_waterway_id(context) if context else None,
            tenant_id=cls._context_tenant_id(context) if context else None,
            biz_scenario_id=cls._context_biz_scenario_id(context) if context else None,
            step=mpc_task_state.current_step if mpc_task_state else 0,
            total_step=mpc_task_state.total_steps if mpc_task_state else None,
            execution_status=MPC_PLAN_DISPATCH_PENDING,
            plan_type=plan_type,
            loss=loss,
            gate_operations=gate_operations,
            gate_amplitude=gate_amplitude,
            details=details,
        )

    @classmethod
    def build_prediction_result(
        cls,
        mpc_task_state: Optional["SchedulingTaskState"],
        horizon_step: Optional[List[HorizonStep]] = None,
        plan_type: Optional[str] = None,
        loss: Optional[float] = None,
        gate_operations: Optional[int] = None,
        gate_amplitude: Optional[float] = None,
    ) -> MpcPredictionResult:
        return cls.build_customize_prediction_result(
            mpc_task_state=mpc_task_state,
            horizon_step=horizon_step,
            plan_type=plan_type,
            loss=loss,
            gate_operations=gate_operations,
            gate_amplitude=gate_amplitude,
        )

    @staticmethod
    def _control_object_to_detail(
        control_object_result: ControlObjectResult,
        horizon_step: Optional[int],
    ) -> MpcPredictionResultDetail:
        return MpcPredictionResultDetail(
            horizon_step=horizon_step,
            command_type=control_object_result.target_value_type or MPC_DEVICE_CONTROL,
            node_id=control_object_result.node_id,
            object_type=control_object_result.object_type,
            object_id=control_object_result.object_id,
            target_value=control_object_result.target_value,
            value=control_object_result.target_value,
        )

    @staticmethod
    def _predicted_result_to_detail(
        predicted_result: PredictedResult,
        horizon_step: Optional[int],
    ) -> MpcPredictionResultDetail:
        attributes = {
            "front_water_level": predicted_result.front_water_level,
            "back_water_level": predicted_result.back_water_level,
            "out_flow": predicted_result.out_flow,
            "efficiency": predicted_result.efficiency,
        }
        target_value_type = predicted_result.final_target_value_type
        if target_value_type and target_value_type.upper() == MPC_OPERATION_WATER_LEVEL:
            attributes["final_target_water_level"] = predicted_result.final_target_value
        if target_value_type and target_value_type.upper() == MPC_OPERATION_WATER_FLOW:
            attributes["final_target_water_flow"] = predicted_result.final_target_value
        return MpcPredictionResultDetail(
            horizon_step=horizon_step,
            command_type=target_value_type,
            object_type=predicted_result.object_type,
            node_id=predicted_result.object_id,
            object_id=predicted_result.object_id,
            value=predicted_result.front_water_level,
            target_value=predicted_result.final_target_value,
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
    def _count_details(report: MpcPredictionResultReport) -> int:
        return sum(len(result.details or []) for result in report.mpc_prediction_results or [])
