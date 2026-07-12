"""Task-scoped coordination command runtime."""

from __future__ import annotations

import logging
from threading import Event
from typing import Callable, Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.logging_config import (
    set_biz_component,
    set_biz_scene_instance_id,
    set_hydros_cluster_id,
    set_hydros_node_id,
)
from hydros_agent_sdk.protocol.commands import HydroEventCommand, SimCommand
from hydros_agent_sdk.state_manager import AgentStateManager

from .coordination_error_response_factory import CoordinationErrorResponseFactory
from .coordination_inbound import CoordinationInboundRuntime
from .coordination_router import CoordinationCommandRouter


logger = logging.getLogger(__name__)


class TaskRuntime:
    """Own callback execution, task mailboxes and failure-to-response conversion.

    Transport injects parsed coordination commands through :meth:`enqueue` and
    receives callback responses through ``outbound_submitter``. It does not own
    an MQTT connection or serialize protocol DTOs.
    """

    def __init__(
        self,
        callback: SimCoordinationCallback,
        state_manager: AgentStateManager,
        outbound_submitter: Callable[[SimCommand], None],
        control_queue_size: int = 1000,
        business_queue_size: int = 1000,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.callback = callback
        self.state_manager = state_manager
        self.outbound_submitter = outbound_submitter
        self.logger = log or logger
        self.running = Event()
        self.router = CoordinationCommandRouter(
            callback=self.callback,
            context_id_getter=self.command_context_id,
            event_type_getter=self.command_event_type,
            log=self.logger,
        )
        self.error_response_factory = CoordinationErrorResponseFactory(
            state_manager=self.state_manager,
            callback=self.callback,
            log=self.logger,
        )
        self.inbound = CoordinationInboundRuntime(
            running=self.running,
            handler=self.handle,
            context_id_getter=self.command_context_id,
            control_queue_size=control_queue_size,
            business_queue_size=business_queue_size,
            log=self.logger,
        )

    def start(self) -> None:
        if self.running.is_set():
            return
        self.running.set()
        self.inbound.start_workers()

    def stop(self) -> None:
        if not self.running.is_set():
            return
        self.running.clear()
        self.inbound.stop_workers()

    def enqueue(self, command: SimCommand) -> None:
        """Accept a parsed inbound command from the coordination transport."""
        self.inbound.enqueue(command)

    def handle(self, command: SimCommand) -> None:
        """Run callback routing and return protocol-compatible failures to transport."""
        self._set_logging_context(command)
        try:
            self._submit_result(self.router.dispatch(command))
        except Exception as error:
            self.logger.error(
                "Error handling command %s: %s", command.command_type, error, exc_info=True
            )
            error_response = self.error_response_factory.create(command, error)
            if error_response is not None:
                self.outbound_submitter(error_response)

    def _submit_result(self, result) -> None:
        if result is None:
            return
        if isinstance(result, SimCommand):
            self.outbound_submitter(result)
            return
        if isinstance(result, (list, tuple)):
            for item in result:
                self._submit_result(item)
            return
        self.logger.debug("Ignoring unsupported callback result type: %s", type(result).__name__)

    def _set_logging_context(self, command: SimCommand) -> None:
        cluster_id = self.state_manager.get_cluster_id()
        if cluster_id:
            set_hydros_cluster_id(cluster_id)
        node_id = self.state_manager.get_node_id()
        if node_id:
            set_hydros_node_id(node_id)
        context_id = self.command_context_id(command)
        if context_id:
            set_biz_scene_instance_id(context_id)
        component = self.callback.get_component()
        if component:
            set_biz_component(component)

    @staticmethod
    def command_context_id(command: SimCommand) -> Optional[str]:
        context = getattr(command, "context", None)
        return getattr(context, "biz_scene_instance_id", None)

    @staticmethod
    def command_event_type(command: SimCommand) -> Optional[str]:
        if isinstance(command, HydroEventCommand):
            return getattr(command.payload, "hydro_event_type", None)
        for attribute in (
            "time_series_data_changed_event",
            "outflow_time_series_data_changed_event",
            "hydro_event",
        ):
            event = getattr(command, attribute, None)
            if event is not None:
                return getattr(event, "hydro_event_type", None)
        return None
