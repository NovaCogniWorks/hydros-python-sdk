"""把 MPC 控制结果转换成智能体指令。"""

from __future__ import annotations

import logging
from typing import List, Optional

from hydros_agent_sdk.agent_commands.models import (
    AgentCommand,
    HydroStationTargetValueRequest,
)
from hydros_agent_sdk.agent_commands.target_value_builder import StationTargetValueCommandBuilder
from hydros_agent_sdk.mpc.models import ControlObjectResult, MpcOptimizeResponse
from hydros_agent_sdk.utils import generate_agent_command_id

logger = logging.getLogger(__name__)


class MpcControlCommandBuilder(StationTargetValueCommandBuilder):
    """把 MPC 结果和内部控制意图转换成智能体指令。"""

    def build_from_mpc_responses(
        self,
        responses: List[MpcOptimizeResponse],
    ) -> List[AgentCommand]:
        control_commands: List[AgentCommand] = []
        for response in responses:
            if (response.plan_type or "").upper() != "OPTIMAL":
                logger.debug(
                    "Skip MPC response for control command build: plan_type=%s",
                    response.plan_type,
                )
                continue
            if not response.horizon_controls:
                logger.debug(
                    "Skip MPC response for control command build: empty horizon_controls, plan_type=%s",
                    response.plan_type,
                )
                continue

            first_control = response.horizon_controls[0]
            for control_object_result in first_control.control_object_list or []:
                if self._is_incomplete_control_object(control_object_result):
                    logger.debug(
                        "Skip incomplete MPC object control: objectId=%s, objectType=%s, targetValueType=%s",
                        control_object_result.object_id,
                        control_object_result.object_type,
                        control_object_result.target_value_type,
                    )
                    continue

                target_agent = self.resolve_target_agent_for_object(
                    control_object_result.object_id,
                    control_object_result.object_type,
                )
                if target_agent is None:
                    logger.warning(
                        "Cannot resolve target agent for MPC control: objectId=%s, objectType=%s",
                        control_object_result.object_id,
                        control_object_result.object_type,
                    )
                    continue

                control_commands.append(
                    HydroStationTargetValueRequest(
                        command_id=generate_agent_command_id(),
                        context=self.source_agent.context,
                        source=self.source_agent,
                        target=target_agent,
                        object_id=control_object_result.object_id,
                        object_type=control_object_result.object_type,
                        target_value=control_object_result.target_value,
                        target_value_type=control_object_result.target_value_type,
                        need_ack_reply=True,
                    )
                )

        logger.info(
            "Built %s control commands from %s MPC responses",
            len(control_commands),
            len(responses or []),
        )
        return control_commands

    @staticmethod
    def _is_incomplete_control_object(control_object_result: ControlObjectResult) -> bool:
        return (
            control_object_result.object_id is None
            or not MpcControlCommandBuilder._has_text(control_object_result.object_type)
            or control_object_result.target_value is None
            or not MpcControlCommandBuilder._has_text(control_object_result.target_value_type)
        )

    @staticmethod
    def _has_text(value: Optional[str]) -> bool:
        return value is not None and bool(value.strip())
