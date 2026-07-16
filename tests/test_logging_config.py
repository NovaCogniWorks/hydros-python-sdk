import logging

from hydros_agent_sdk.logging_config import (
    HydrosFormatter,
    set_hydros_cluster_id,
    set_hydros_node_id,
)


def test_full_formatter_uses_empty_markers_when_deployment_identity_is_unavailable():
    set_hydros_cluster_id(None)
    set_hydros_node_id(None)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="message",
        args=(),
        exc_info=None,
    )

    formatted = HydrosFormatter().format(record)

    assert formatted.split("|", maxsplit=2)[:2] == ["-", "-"]
