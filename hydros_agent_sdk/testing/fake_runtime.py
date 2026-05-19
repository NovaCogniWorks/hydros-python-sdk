"""
Small local runtime for testing agent callbacks without MQTT.
"""

from __future__ import annotations

import time
from queue import Queue
from typing import List, Optional

from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.protocol.commands import SimCommand
from hydros_agent_sdk.state_manager import AgentStateManager


class FakeRuntime:
    """
    In-process harness around SimCoordinationClient dispatch behavior.

    The runtime does not start network loops. Tests can feed command objects into
    ``send`` and inspect responses captured from the outgoing queue.
    """

    def __init__(
        self,
        callback: SimCoordinationCallback,
        state_manager: Optional[AgentStateManager] = None,
        topic: str = "/hydros/commands/coordination/test",
    ):
        self.state_manager = state_manager or AgentStateManager()
        self.callback = callback
        self.client = SimCoordinationClient(
            broker_url="tcp://localhost",
            broker_port=1883,
            topic=topic,
            sim_coordination_callback=callback,
            state_manager=self.state_manager,
        )
        if hasattr(callback, "set_client"):
            callback.set_client(self.client)
        self.responses: List[SimCommand] = []

    def send(self, command: SimCommand) -> List[SimCommand]:
        """Dispatch a command and return responses produced by this command."""
        before = self.client.out_message_queue.qsize()
        self.client._handle_incoming_message(command)
        produced = self._drain_new_responses(before)
        self.responses.extend(produced)
        return produced

    def _drain_new_responses(self, previous_size: int) -> List[SimCommand]:
        produced = []
        total_size = self.client.out_message_queue.qsize()
        new_count = max(total_size - previous_size, 0)
        kept = []

        while not self.client.out_message_queue.empty():
            item = self.client.out_message_queue.get_nowait()
            if len(kept) < previous_size:
                kept.append(item)
            else:
                produced.append(item)

        restored = Queue()
        for item in kept:
            restored.put(item)
        for item in produced:
            restored.put(item)
        self.client.out_message_queue = restored

        return produced[:new_count]

    def publish_all(self) -> None:
        """Synchronously publish queued responses through the fake MQTT client."""
        self.client.connected.set()
        while not self.client.out_message_queue.empty():
            command = self.client.out_message_queue.get_nowait()
            if self.client._should_send(command):
                self.client._send_with_retry(command)
                time.sleep(0)
