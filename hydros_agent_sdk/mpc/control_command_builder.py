"""把 MPC 控制结果转换成智能体指令。"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from hydros_agent_sdk.agent_commands.models import (
    AgentCommand,
    DeviceValueTypeEnum,
    DisturbanceNodeWaterFlowRequest,
    HydroDirectGateOpeningRequest,
    HydroStationTargetValueRequest,
)
from hydros_agent_sdk.mpc.models import MpcOptimizeResponse
from hydros_agent_sdk.protocol.models import HydroAgentInstance
from hydros_agent_sdk.utils import generate_agent_command_id

logger = logging.getLogger(__name__)


class MpcControlCommandBuilder:
    """把 MPC 结果和内部控制意图转换成智能体指令。"""

    def __init__(
        self,
        source_agent,
        get_sibling_agent_instance: Callable[[str], Optional[HydroAgentInstance]],
        resolve_target_agent_for_object: Callable[[Optional[int], Optional[str]], Optional[HydroAgentInstance]],
    ):
        self.source_agent = source_agent
        self.get_sibling_agent_instance = get_sibling_agent_instance
        self.resolve_target_agent_for_object = resolve_target_agent_for_object

    def build_station_target_value_request(
        self,
        target_agent_code: str,
        target_command_type: str,
        target_value: Any,
        object_id: int,
        object_type: str,
    ) -> Optional[HydroStationTargetValueRequest]:
        target_agent = self.get_sibling_agent_instance(target_agent_code)
        if target_agent is None:
            logger.warning("未找到兄弟智能体: %s", target_agent_code)
            return None

        try:
            value_type = DeviceValueTypeEnum.from_code(target_command_type)
        except ValueError:
            logger.warning("不支持的目标值类型: %s", target_command_type)
            return None

        if target_value is None:
            logger.warning(
                "控制指令缺少有效目标值: target=%s, type=%s",
                target_agent_code,
                target_command_type,
            )
            return None

        try:
            typed_target_value = value_type.value_type(target_value)
        except (TypeError, ValueError):
            logger.warning(
                "控制指令目标值类型转换失败: target=%s, type=%s, value=%s",
                target_agent_code,
                target_command_type,
                target_value,
            )
            return None

        return HydroStationTargetValueRequest(
            command_id=generate_agent_command_id(),
            context=self.source_agent.context,
            source=self.source_agent,
            target=target_agent,
            object_id=object_id,
            object_type=object_type,
            target_value_type=value_type.code,
            target_value=typed_target_value,
            need_ack_reply=True,
        )

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
                if control_object_result.target_value is None:
                    logger.debug(
                        "Skip MPC object control without target value: objectId=%s, objectType=%s",
                        control_object_result.object_id,
                        control_object_result.object_type,
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

                if control_object_result.object_type == "Gate":
                    control_commands.append(
                        HydroDirectGateOpeningRequest(
                            command_id=generate_agent_command_id(),
                            source=self.source_agent,
                            target=target_agent,
                            object_id=control_object_result.object_id,
                            object_name=control_object_result.object_name,
                            object_type=control_object_result.object_type,
                            gate_opening=control_object_result.target_value,
                            need_ack_reply=True,
                        )
                    )
                else:
                    control_commands.append(
                        DisturbanceNodeWaterFlowRequest(
                            command_id=generate_agent_command_id(),
                            source=self.source_agent,
                            target=target_agent,
                            object_id=control_object_result.node_id,
                            object_name=control_object_result.node_name,
                            object_type=control_object_result.object_type,
                            value=control_object_result.target_value,
                            need_ack_reply=True,
                        )
                    )

        logger.info(
            "Built %s control commands from %s MPC responses",
            len(control_commands),
            len(responses or []),
        )
        return control_commands
