"""
Pump Station Local Controller Agent.

Concrete implementation of ControllerAgent for pump stations.
Receives control commands (blade angle, on/off) from the central
scheduling agent and maintains per-unit operational state.
"""

import logging
import sys
import os
from typing import Optional, List, Dict, Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    load_env_config, ErrorCodes, handle_agent_errors,
    HydroObjectType
)
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.agents.controller_agent import ControllerAgent
from hydros_agent_sdk.protocol.commands import *
from hydros_agent_sdk.protocol.models import *

logger = logging.getLogger(__name__)


class PumpControllerAgent(ControllerAgent):
    """Pump station local controller.

    Responsibilities:
    1. Initialise per-pump-unit device states on task init
    2. Receive and apply blade-angle / on-off commands each tick
    3. Compute approximate flow and power from blade angle
    4. Report unit status via MQTT metrics
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
        # Per-unit rated parameters read from config during on_init
        self._unit_rated_flow: Dict[str, float] = {}
        self._unit_rated_power: Dict[str, float] = {}

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        logger.info("Initialising PumpControllerAgent: %s", self.agent_id)
        self.load_agent_configuration(request)

        # Read managed pump-unit list from config
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
        """Apply control action and also update derived flow/power."""
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
        """Build metrics report including pump-specific fields."""
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
