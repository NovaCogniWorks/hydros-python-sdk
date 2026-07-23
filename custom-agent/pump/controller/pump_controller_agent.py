"""
泵站现地控制器 Agent。

面向泵站的 ControllerAgent 具体实现。接收中央调度 Agent 下发的叶片角、
启停等控制指令，并维护各泵组的运行状态。
"""

import logging
import sys
import os
from typing import Optional, List, Dict, Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    ErrorCodes,
    handle_agent_errors,
)
from hydros_agent_sdk.config_loader import load_env_config
from hydros_agent_sdk.utils import HydroObjectType
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.agents.controller_agent import ControllerAgent
from hydros_agent_sdk.protocol.commands import *
from hydros_agent_sdk.protocol.models import *

logger = logging.getLogger(__name__)


class PumpControllerAgent(ControllerAgent):
    """泵站现地控制器。

    主要职责：
    1. 任务初始化时建立各泵组的设备状态
    2. 每个 tick 接收并执行叶片角和启停指令
    3. 根据叶片角估算流量和功率
    4. 通过 MQTT metrics 上报泵组状态
    """

    def __init__(
        self,
        sim_coordination_client,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        **kwargs
    ):
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            **kwargs
        )
        # 各泵组额定参数在 on_init 阶段从配置读取
        self._unit_rated_flow: Dict[str, float] = {}
        self._unit_rated_power: Dict[str, float] = {}

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initialising PumpControllerAgent: %s", self.agent_id)
        self.load_agent_configuration(request)

        # 从配置读取当前 Agent 管理的泵组列表
        unit_list = self.properties.get_property("pump_units", [])
        if isinstance(unit_list, str):
            import json
            try:
                unit_list = json.loads(unit_list)
            except Exception:
                unit_list = [uid.strip() for uid in unit_list.split(",") if uid.strip()]

        for unit_id in unit_list:
            uid = str(unit_id)
            rated_flow = float(self.properties.get_property(f"unit.{uid}.rated_flow", 1.0))
            rated_power = float(self.properties.get_property(f"unit.{uid}.rated_power", 1.0))
            self._unit_rated_flow[uid] = rated_flow
            self._unit_rated_power[uid] = rated_power
            self.set_device_state(uid, {
                "object_type": str(HydroObjectType.PUMP),
                "status": 0,
                "blade_angle": 0.0,
                "flow": 0.0,
                "power": 0.0,
                "efficiency": 0.0,
                "head": 0.0,
            })
            logger.info("Registered pump unit %s: rated_flow=%s rated_power=%s",
                         uid, rated_flow, rated_power)

        self.state_manager.register_agent(self)
        logger.info("PumpControllerAgent %s initialised with %d units",
                     self.agent_id, self.device_count)

        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )

    def _apply_control_action(self, command: Dict[str, Any]) -> None:
        """执行控制动作，并同步更新派生的流量和功率。"""
        super()._apply_control_action(command)

        object_id = str(command.get("object_id", ""))
        state = self._device_states.get(object_id)
        if state is None:
            return

        blade = state.get("blade_angle", 0.0)
        status = state.get("status", 0)
        rated_flow = self._unit_rated_flow.get(object_id, 1.0)
        rated_power = self._unit_rated_power.get(object_id, 1.0)

        if status == 0 or blade <= 0:
            state["flow"] = 0.0
            state["power"] = 0.0
            state["efficiency"] = 0.0
        else:
            ratio = min(blade / 100.0, 1.0)
            state["flow"] = round(rated_flow * ratio, 4)
            state["power"] = round(rated_power * ratio, 4)
            state["efficiency"] = round(0.75 + 0.15 * ratio, 4)

        logger.debug("PumpController unit=%s blade=%s on=%s flow=%s",
                      object_id, blade, status, state["flow"])

    def _build_metrics_report(self, step: int) -> Optional[List]:
        """构造包含泵组专有字段的 metrics report。"""
        from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

        metrics_list = []
        for did, state in self._device_states.items():
            m = MqttMetrics(
                object_id=did,
                object_type=state.get("object_type", "PUMP"),
                agent_id=self.agent_id,
                agent_code=self.agent_code,
            )
            m.blade_angle = state.get("blade_angle", 0.0)
            m.status = state.get("status", 0)
            m.flow = state.get("flow", 0.0)
            m.power = state.get("power", 0.0)
            m.efficiency = state.get("efficiency", 0.0)
            m.head = state.get("head", 0.0)
            metrics_list.append(m)
        return metrics_list if metrics_list else None

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info("Terminating PumpControllerAgent: %s", self.agent_id)

        for uid in self.all_device_ids():
            self.update_device_attr(uid, status=0, blade_angle=0.0, flow=0.0, power=0.0)

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False,
        )
