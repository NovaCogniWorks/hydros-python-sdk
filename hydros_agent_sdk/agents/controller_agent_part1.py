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
