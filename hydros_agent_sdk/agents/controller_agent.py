"""
Hydros 仿真控制器 Agent。

ControllerAgent 为泵站、闸站等现地控制器提供通用基类：
1. 接收中央调度 Agent 下发的控制指令
2. 维护泵组、闸门等设备的本地状态
3. 执行启停、开度调节等本地控制逻辑
4. 通过 MQTT 上报设备运行状态
"""

from abc import abstractmethod
import logging
from typing import Any, Dict, List, Optional

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
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

from .tickable_agent import TickableAgent

logger = logging.getLogger(__name__)


class ControllerAgent(TickableAgent):
    """泵站、闸站等现地控制器的通用基类。

    该基类负责维护本地设备状态、缓存并执行控制指令，以及上报运行状态。

    子类必须实现 ``on_init`` 和 ``on_terminate``，可以按需覆盖
    ``_apply_control_action`` 和 ``_build_metrics_report``。
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

    # -- 设备状态 --
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

    # -- 控制指令 --
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

    # -- 生命周期 --
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
