import pytest

from hydros_agent_sdk.transport import InMemoryTransport, PublishRecord


def test_in_memory_transport_delivers_messages_to_subscribers():
    transport = InMemoryTransport()
    received = []
    transport.subscribe("topic/a", lambda topic, payload: received.append((topic, payload)))

    transport.start()
    transport.publish("topic/a", "payload", qos=0)

    assert received == [("topic/a", "payload")]
    assert transport.published == [PublishRecord(topic="topic/a", payload="payload", qos=0)]


def test_in_memory_transport_requires_start_before_publish():
    transport = InMemoryTransport()

    with pytest.raises(RuntimeError, match="not running"):
        transport.publish("topic/a", "payload")
