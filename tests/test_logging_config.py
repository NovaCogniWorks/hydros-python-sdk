"""
Tests for the Hydros logging configuration.

This module tests the custom logging formatter and context management.
"""

import logging
import io
from hydros_agent_sdk.logging_config import (
    HydrosFormatter,
    LogContext,
    set_task_id,
    set_biz_component,
    set_node_id,
    get_task_id,
    get_biz_component,
    get_node_id,
)


def test_hydros_formatter_basic():
    """Test basic formatting without context."""
    formatter = HydrosFormatter(default_node_id="TEST_NODE")

    # Create a log record
    logger = logging.getLogger("test.logger")
    record = logger.makeRecord(
        name="test.logger",
        level=logging.INFO,
        fn="test.py",
        lno=10,
        msg="Test message",
        args=(),
        exc_info=None
    )

    # Format the record
    formatted = formatter.format(record)

    # Check format: NODE_ID|TIMESTAMP|LEVEL|TASK_ID|BIZ_COMPONENT|TYPE|CONTENT|LOGGER|MESSAGE
    parts = formatted.split('|')
    assert len(parts) == 9
    assert parts[0] == "TEST_NODE"  # node_id
    assert parts[2] == "INFO "  # level (5 chars, left-aligned)
    assert parts[3] == "System"  # task_id (default)
    assert parts[4] == "Common"  # biz_component (default)
    assert parts[5] == ""  # type (empty)
    assert parts[6] == ""  # content (empty)
    assert parts[7] == "test.logger"  # logger name
    assert parts[8] == "Test message"  # message


def test_hydros_formatter_with_context():
    """Test formatting with context set."""
    formatter = HydrosFormatter(default_node_id="TEST_NODE")

    # Set context
    set_node_id("AGENT_NODE_01")
    set_task_id("TASK123456")
    set_biz_component("MyAgent")

    # Create a log record
    logger = logging.getLogger("test.logger")
    record = logger.makeRecord(
        name="test.logger",
        level=logging.WARNING,
        fn="test.py",
        lno=10,
        msg="Warning message",
        args=(),
        exc_info=None
    )

    # Format the record
    formatted = formatter.format(record)

    # Check format
    parts = formatted.split('|')
    assert parts[0] == "AGENT_NODE_01"  # node_id from context
    assert parts[2] == "WARNING"  # level (5 chars, left-aligned - WARNING is exactly 7 chars, so it's "WARNING")
    assert parts[3] == "TASK123456"  # task_id from context
    assert parts[4] == "MyAgent"  # biz_component from context

    # Clean up context
    set_node_id(None)
    set_task_id(None)
    set_biz_component(None)


def test_log_context_manager():
    """Test LogContext context manager."""
    # Initial state
    assert get_task_id() is None
    assert get_biz_component() is None

    # Use context manager
    with LogContext(task_id="TASK_CTX", biz_component="CtxAgent"):
        assert get_task_id() == "TASK_CTX"
        assert get_biz_component() == "CtxAgent"

    # Context should be cleared after exiting
    assert get_task_id() is None
    assert get_biz_component() is None


def test_nested_log_context():
    """Test nested LogContext context managers."""
    with LogContext(task_id="OUTER", biz_component="OuterAgent"):
        assert get_task_id() == "OUTER"
        assert get_biz_component() == "OuterAgent"

        with LogContext(task_id="INNER", biz_component="InnerAgent"):
            assert get_task_id() == "INNER"
            assert get_biz_component() == "InnerAgent"

        # Should restore outer context
        assert get_task_id() == "OUTER"
        assert get_biz_component() == "OuterAgent"

    # Should be cleared
    assert get_task_id() is None
    assert get_biz_component() is None


def test_logger_name_abbreviation():
    """Test logger name abbreviation."""
    formatter = HydrosFormatter(logger_max_length=20)

    # Test short name (no abbreviation needed)
    assert formatter._abbreviate_logger_name("short") == "short"

    # Test long name (should abbreviate)
    long_name = "com.hydros.coordination.service.BaseCoordinatorMqttService"
    abbreviated = formatter._abbreviate_logger_name(long_name)
    assert len(abbreviated) <= 20
    assert abbreviated == "c.h.c.s.BaseCoordina"  # Truncated to 20 chars

    # Test Python-style name (will be truncated to 20 chars)
    python_name = "hydros_agent_sdk.coordination_client"
    abbreviated = formatter._abbreviate_logger_name(python_name)
    # h.a.coordination_client is 24 chars, so it gets truncated to 20
    assert abbreviated == "h.coordination_clien"


def test_format_with_exception():
    """Test formatting with exception info."""
    formatter = HydrosFormatter(default_node_id="TEST_NODE")

    # Create a log record with exception
    logger = logging.getLogger("test.logger")
    try:
        raise ValueError("Test error")
    except ValueError:
        import sys
        exc_info = sys.exc_info()
        record = logger.makeRecord(
            name="test.logger",
            level=logging.ERROR,
            fn="test.py",
            lno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info
        )

    # Format the record
    formatted = formatter.format(record)

    # Check that exception is included
    assert "Error occurred" in formatted
    assert "ValueError: Test error" in formatted
    assert "Traceback" in formatted


def test_integration_with_logger():
    """Test integration with actual logger."""
    # Create a string stream to capture log output
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    formatter = HydrosFormatter(default_node_id="TEST_NODE")
    handler.setFormatter(formatter)

    # Create logger
    logger = logging.getLogger("test.integration")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)

    # Log with context
    with LogContext(task_id="TASK_INT", biz_component="IntAgent", node_id="INT_NODE"):
        logger.info("Integration test message")

    # Get output
    output = stream.getvalue()

    # Verify format
    assert "INT_NODE" in output
    assert "TASK_INT" in output
    assert "IntAgent" in output
    assert "Integration test message" in output

    # Clean up
    logger.handlers.clear()


if __name__ == "__main__":
    print("Running logging configuration tests...")

    test_hydros_formatter_basic()
    print("✓ test_hydros_formatter_basic")

    test_hydros_formatter_with_context()
    print("✓ test_hydros_formatter_with_context")

    test_log_context_manager()
    print("✓ test_log_context_manager")

    test_nested_log_context()
    print("✓ test_nested_log_context")

    test_logger_name_abbreviation()
    print("✓ test_logger_name_abbreviation")

    test_format_with_exception()
    print("✓ test_format_with_exception")

    test_integration_with_logger()
    print("✓ test_integration_with_logger")

    print("\nAll tests passed!")
