"""
Transport interfaces for coordination message delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


MessageHandler = Callable[[str, str], None]


@dataclass(frozen=True)
class PublishRecord:
    """A message published through a transport."""

    topic: str
    payload: str
    qos: int = 1


class Transport(Protocol):
    """Minimal transport protocol for publish/subscribe style messaging."""

    def start(self) -> None:
        """Start transport resources."""
        ...

    def stop(self) -> None:
        """Stop transport resources."""
        ...

    def subscribe(self, topic: str, handler: MessageHandler, qos: int = 1) -> None:
        """Subscribe a handler to a topic."""
        ...

    def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        """Publish a payload to a topic."""
        ...
