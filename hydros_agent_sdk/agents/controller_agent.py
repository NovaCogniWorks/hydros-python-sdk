"""
Controller Agent for Hydros simulation.

ControllerAgent provides a generic base for pump/gate station local controllers:
1. Receive control commands from central scheduling agents
2. Maintain local device states (pump units, gates, etc.)
3. Execute local control logic (start/stop, opening adjustment, etc.)
4. Report device operational status via MQTT
"""

import logging
from typing import Optional, List, Dict, Any
from abc import abstractmethod

from hydros_agent_sdk.runtime.response_factory import ResponseFactory
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics
from .tickable_agent import TickableAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    AgentStatus,
    AgentDriveMode,
)

logger = logging.getLogger(__name__)


class ControllerAgent(TickableAgent):
    """Local controller base class for pump/gate stations.

    This base class provides common capabilities for local control agents:
    1. Maintain local device states (pumps/gates)
    2. Receive and buffer control commands from superior scheduling agents
    3. Execute local control logic on each tick
    4. Report device operational status via MQTT

    Subclasses should implement:
    - on_init(): Initialize device configuration and state tracking
    - on_tick_simulation(): Execute local control decision logic
    - on_terminate(): Clean up resources

    Optional overrides:
    - on_boundary_condition_update(): Respond to boundary condition changes
    - _apply_control_action(): Apply specific control actions
    - _build_metrics_report(): Customize metrics reporting
    """

    # Device state structures:
    #   self._device_states: Dict[str, Dict[str, Any]]
    #       Keyed by device object_id (str), value is state dict.
    #       Pump example: {"unit_id": str, "status": int, "blade_angle": float, "flow": float}
    #   self._pending_commands: List[Dict[str, Any]]
    #       Queue of pending control commands.

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
        agent_status: AgentStatus = AgentStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
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
            agent_status=agent_status,
            drive_mode=drive_mode,
            agent_configuration_url=agent_configuration_url,
            **kwargs
        )

        self._init_device_state()
        self._init_command_buffer()

        logger.info("ControllerAgent initialized: %s", self.agent_id)

class ControllerAgent(TickableAgent):
    """Local controller base class for pump/gate stations.

    This base class provides common capabilities for local control agents.
    Maintains local device states, buffers and applies control commands,
    and reports operational status.

    Subclasses must implement: on_init, on_terminate.
    Subclasses may override: _apply_control_action, _build_metrics_report.
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
        agent_status: AgentStatus = AgentStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
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
            agent_status=agent_status,
            drive_mode=drive_mode,
            agent_configuration_url=agent_configuration_url,
            **kwargs
        )
        self._init_device_state()
        self._init_command_buffer()
        logger.info("ControllerAgent initialized: %s", self.agent_id)

    def _init_device_state(self) -> None:
        self._device_states: Dict[str, Dict[str, Any]] = {}

    def _init_command_buffer(self) -> None:
        self._pending_commands: List[Dict[str, Any]] = []

    # -- device state --
    def get_device_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        return self._device_states.get(str(device_id))

    def set_device_state(self, device_id: str, state: Dict[str, Any]) -> None:
        self._device_states[str(device_id)] = state

    def update_device_attr(self, device_id: str, **attrs) -> bool:
        state = self._device_states.get(str(device_id))
        if state is None:
            return False
        state.update(attrs)
        return True

    def all_device_ids(self) -> List[str]:
        return list(self._device_states.keys())

    # -- commands --
    def receive_command(self, command: Dict[str, Any]) -> None:
        self._pending_commands.append(command)
        logger.info("Ctrl %s enqueued: obj=%s type=%s val=%s",
                     self.agent_id,
                     command.get("object_id"),
                     command.get("target_command_type"),
                     command.get("target_value"))

    def drain_pending_commands(self) -> List[Dict[str, Any]]:
        cmds = self._pending_commands[:]
        self._pending_commands.clear()
        return cmds

    def has_pending_commands(self) -> bool:
        return len(self._pending_commands) > 0

    # -- lifecycle --
    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        pass

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        logger.debug("ControllerAgent %s tick step %s", self.agent_id, request.step)
        commands = self.drain_pending_commands()
        if not commands:
            return None
        for cmd in commands:
            try:
                self._apply_control_action(cmd)
            except Exception as e:
                logger.error("Ctrl %s cmd failed obj=%s err=%s",
                             self.agent_id, cmd.get("object_id"), e, exc_info=True)
        return self._build_metrics_report(request.step)

    def _apply_control_action(self, command: Dict[str, Any]) -> None:
        object_id = str(command.get("object_id", ""))
        command_type = command.get("target_command_type", "")
        target_value = command.get("target_value", "0")
        if not object_id:
            return
        if object_id not in self._device_states:
            self._device_states[object_id] = {}
        try:
            v = float(target_value)
        except (ValueError, TypeError):
            v = 0.0
        st = self._device_states[object_id]
        if command_type in ("BLADE_ANGLE", "OPENING"):
            st["blade_angle"] = v
        elif command_type in ("ON_OFF", "STATUS"):
            st["status"] = int(v)
        elif command_type == "FLOW_SETPOINT":
            st["flow_setpoint"] = v
        else:
            st["target_value"] = v

    def _build_metrics_report(self, step: int) -> Optional[List[MqttMetrics]]:
        metrics_list: List[MqttMetrics] = []
        for did, state in self._device_states.items():
            m = MqttMetrics(
                object_id=did,
                object_type=state.get("object_type", "PUMP"),
                agent_id=self.agent_id,
                agent_code=self.agent_code,
            )
            for k in ("blade_angle", "status", "flow", "power", "efficiency", "head"):
                if k in state:
                    setattr(m, k, state[k])
            metrics_list.append(m)
        return metrics_list if metrics_list else None

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        pass

    @property
    def device_count(self) -> int:
        return len(self._device_states)
