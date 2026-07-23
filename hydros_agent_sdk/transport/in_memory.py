"""
内存传输实现。

用于测试和本地 harness，在没有 broker 的情况下提供发布/订阅语义。
"""

from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import DefaultDict, List, Tuple

from hydros_agent_sdk.transport.base import MessageHandler, PublishRecord


class InMemoryTransport:
    """用于测试和本地仿真的同步进程内传输。"""

    def __init__(self):
        self._handlers: DefaultDict[str, List[Tuple[MessageHandler, int]]] = defaultdict(list)
        self._published: List[PublishRecord] = []
        self._running = False
        self._lock = RLock()

    def start(self) -> None:
        with self._lock:
            self._running = True

    def stop(self) -> None:
        with self._lock:
            self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def published(self) -> List[PublishRecord]:
        with self._lock:
            return list(self._published)

    def subscribe(self, topic: str, handler: MessageHandler, qos: int = 1) -> None:
        with self._lock:
            self._handlers[topic].append((handler, qos))

    def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        with self._lock:
            if not self._running:
                raise RuntimeError("Transport is not running")
            self._published.append(PublishRecord(topic=topic, payload=payload, qos=qos))
            handlers = list(self._handlers.get(topic, []))

        for handler, _handler_qos in handlers:
            handler(topic, payload)

    def deliver(self, topic: str, payload: str) -> None:
        """投递一条入站 payload，但不记录为出站发布。"""
        with self._lock:
            if not self._running:
                raise RuntimeError("Transport is not running")
            handlers = list(self._handlers.get(topic, []))

        for handler, _handler_qos in handlers:
            handler(topic, payload)
