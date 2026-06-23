"""
用于在无 MQTT 环境下测试智能体回调的小型本地运行时。
"""

from __future__ import annotations

import time
from queue import Queue
from typing import List, Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.protocol.commands import SimCommand
from hydros_agent_sdk.state_manager import AgentStateManager


class FakeRuntime:
    """
    围绕 SimCoordinationClient 分派行为的进程内测试工具。

    该运行时不会启动网络循环。测试可以把指令对象传给 ``send``，
    并检查从出站队列捕获的响应。
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
        """分派指令并返回该指令产生的响应。"""
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
        """通过 fake MQTT 客户端同步发布队列中的响应。"""
        self.client.connected.set()
        while not self.client.out_message_queue.empty():
            command = self.client.out_message_queue.get_nowait()
            if self.client.outbox_publisher.should_send(command):
                self.client.outbox_publisher.send_with_retry(command)
                time.sleep(0)
