"""把 MPC 控制结果转换成智能体指令。"""

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Tuple

from hydros_agent_sdk.protocol.agent_commands import (
    HydroStationTargetValueRequest,
)
from hydros_agent_sdk.protocol.agent_commands.base import AgentCommand
from hydros_agent_sdk.agent_commands.target_value_builder import StationTargetValueCommandBuilder
from hydros_agent_sdk.mpc.control_execution_plan import (
    MpcControlExecutionPlan,
    MpcControlExecutionTarget,
)
from hydros_agent_sdk.protocol.models import HydroAgentInstance
from hydros_agent_sdk.utils import generate_agent_command_id

logger = logging.getLogger(__name__)


class MpcControlCommandBuilder(StationTargetValueCommandBuilder):
    """把 MPC 结果和内部控制意图转换成智能体指令。"""

    def build_from_control_plan(
        self,
        plan: MpcControlExecutionPlan,
        horizon_step: int,
        current_step: int,
    ) -> List[AgentCommand]:
        control_commands: List[AgentCommand] = []
        control_targets = plan.get_control_targets(horizon_step)
        resolved_targets: List[Tuple[MpcControlExecutionTarget, HydroAgentInstance]] = []
        for control_target in control_targets:
            target_agent = self.resolve_target_agent_for_object(
                control_target.object_id,
                control_target.object_type,
            )
            if target_agent is None:
                logger.warning(
                    "Cannot resolve target agent for MPC control: objectId=%s, objectType=%s",
                    control_target.object_id,
                    control_target.object_type,
                )
                continue
            resolved_targets.append((control_target, target_agent))

        targets_by_value_type: Dict[str, List[Tuple[MpcControlExecutionTarget, HydroAgentInstance]]] = {}
        for resolved_target in resolved_targets:
            target_value_type = self._group_key(resolved_target[0])
            targets_by_value_type.setdefault(target_value_type, []).append(resolved_target)

        for target_value_type, grouped_targets in targets_by_value_type.items():
            group_id = (
                "MPC_CTRL_GROUP:"
                f"{self.source_agent.context.biz_scene_instance_id}:"
                f"{current_step}:{plan.optimize_step}:{horizon_step}:{target_value_type}:{uuid.uuid4()}"
            )
            for control_target, target_agent in grouped_targets:
                control_commands.append(
                    HydroStationTargetValueRequest(
                        command_id=generate_agent_command_id(),
                        context=self.source_agent.context,
                        source=self.source_agent,
                        target=target_agent,
                        object_id=control_target.object_id,
                        object_type=control_target.object_type,
                        target_value=control_target.target_value,
                        target_value_type=control_target.target_value_type,
                        group_id=group_id,
                        group_size=len(grouped_targets),
                        main_step_index=current_step,
                        algo_required_inputs=control_target.algo_required_inputs,
                        need_ack_reply=True,
                    )
                )

        logger.info(
            "Built %s control commands from MPC execution plan at horizon %s",
            len(control_commands),
            horizon_step,
        )
        return control_commands

    @staticmethod
    def _group_key(control_target: MpcControlExecutionTarget) -> str:
        return control_target.target_value_type.strip().lower()
