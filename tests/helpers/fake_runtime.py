"""
用于在无 MQTT 环境下测试智能体回调的小型本地运行时。
"""

from __future__ import annotations

import json
import time
from typing import List, Optional

from hydros_agent_sdk.coordination_callback import SimCoordinationCallback
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.protocol.commands import SimCommand, SimCommandEnvelope
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.transport.in_memory import InMemoryTransport


class FakeRuntime:
    """
    围绕 SimCoordinationClient 分派行为的进程内测试工具。

    该运行时使用 ``InMemoryTransport`` 走完整的 raw payload 装配路径，
    不连接 MQTT broker。
    """

    def __init__(
        self,
        callback: SimCoordinationCallback,
        state_manager: Optional[AgentStateManager] = None,
        topic: str = "/hydros/commands/coordination/test",
    ):
        self.state_manager = state_manager or AgentStateManager()
        self.callback = callback
        self.transport = InMemoryTransport()
        self.client = SimCoordinationClient(
            broker_url="tcp://localhost",
            broker_port=1883,
            topic=topic,
            sim_coordination_callback=callback,
            state_manager=self.state_manager,
            transport=self.transport,
        )
        if hasattr(callback, "set_client"):
            callback.set_client(self.client)
        self.responses: List[SimCommand] = []
        self.client.start()

    def send(self, command: SimCommand) -> List[SimCommand]:
        """分派指令并返回该指令产生的响应。"""
        published_before = len(self.transport.published)
        self.transport.deliver(
            self.client.topic,
            command.model_dump_json(by_alias=True),
        )
        records = self._wait_for_published(published_before)
        produced = [
            SimCommandEnvelope(command=json.loads(record.payload)).command
            for record in records
        ]
        self.responses.extend(produced)
        return produced

    def _wait_for_published(self, start_index: int, timeout: float = 1.0):
        deadline = time.monotonic() + timeout
        last_count = start_index
        stable_since = None

        while time.monotonic() < deadline:
            records = self.transport.published
            current_count = len(records)
            if current_count > start_index:
                if current_count != last_count:
                    last_count = current_count
                    stable_since = time.monotonic()
                elif stable_since is not None and time.monotonic() - stable_since >= 0.02:
                    return records[start_index:]
            time.sleep(0.005)

        return self.transport.published[start_index:]

    def close(self) -> None:
        self.client.stop()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.close()
