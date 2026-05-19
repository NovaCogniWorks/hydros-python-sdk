"""
Transport abstractions for Hydros coordination messages.

The existing SimCoordinationClient still owns the production MQTT path. These
interfaces provide a small extension point for tests and future transports
without rewiring the current client yet.
"""

from hydros_agent_sdk.transport.base import MessageHandler, PublishRecord, Transport
from hydros_agent_sdk.transport.in_memory import InMemoryTransport

__all__ = [
    "MessageHandler",
    "PublishRecord",
    "Transport",
    "InMemoryTransport",
]
