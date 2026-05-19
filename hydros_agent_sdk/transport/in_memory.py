"""
In-memory transport implementation.

This is useful for tests and local harnesses where we want publish/subscribe
semantics without a broker.
"""

from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import DefaultDict, List, Tuple

from hydros_agent_sdk.transport.base import MessageHandler, PublishRecord


class InMemoryTransport:
    """Synchronous in-process transport for tests and local simulations."""

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
