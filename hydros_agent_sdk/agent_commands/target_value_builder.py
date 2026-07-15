"""构造面向目标设备/站点的智能体指令。"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from hydros_agent_sdk.protocol.agent_commands import HydroStationTargetValueRequest
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.protocol.models import HydroAgentInstance
from hydros_agent_sdk.utils import generate_agent_command_id

logger = logging.getLogger(__name__)


class StationTargetValueCommandBuilder:
    """把中央调度内部控制意图转换成站点目标值指令。"""

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
        group_id: Optional[str] = None,
        group_size: Optional[int] = None,
        main_step_index: Optional[int] = None,
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
            group_id=group_id,
            group_size=group_size,
            main_step_index=main_step_index,
            need_ack_reply=True,
        )
