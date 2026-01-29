"""
Test Agent Configuration Loading

This test file demonstrates and validates the agent configuration loading functionality.
"""

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    # Mock pytest.raises for standalone execution
    class MockPytest:
        @staticmethod
        def raises(exception, match=None):
            class RaisesContext:
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    if exc_type is None:
                        raise AssertionError(f"Expected {exception} but no exception was raised")
                    if not issubclass(exc_type, exception):
                        return False
                    return True
            return RaisesContext()
    pytest = MockPytest()

import tempfile
import os
from hydros_agent_sdk.agent_config import (
    AgentConfigLoader,
    AgentConfiguration,
    AgentProperties,
    Author,
    Waterway,
    MqttBroker,
    OutputConfig,
)


# Sample YAML configuration for testing
SAMPLE_YAML = """agent_code: TEST_AGENT
agent_type: TEST_AGENT_TYPE
agent_name: Test Agent
agent_configuration_url: http://example.com/config.yaml
version: v1.0.0
release_at: 2026/01/01
author:
  user_name: Test User
description: Test agent for unit testing
waterway:
  waterway_id: 1
  waterway_name: Test Waterway
properties:
  biz_start_time: 2025/01/01 00:00:00
  step_resolution: 60
  total_steps: 100
  driven_by_coordinator: true
  hydro_environment_type: TEST
  hydros_objects_modeling_url: http://example.com/objects.yaml
  idz_config_url: http://example.com/idz.yaml
  time_series_config_url: http://example.com/timeseries.yaml
  output_config:
    output_mode: MQTT
    mqtt_broker:
      mqtt_host: localhost
      mqtt_port: 1883
      server_uri: tcp://localhost:1883
    mqtt_topic: test/topic
"""


def test_load_from_yaml_string():
    """Test loading configuration from YAML string."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)

    assert config.agent_code == "TEST_AGENT"
    assert config.agent_type == "TEST_AGENT_TYPE"
    assert config.agent_name == "Test Agent"
    assert config.version == "v1.0.0"
    assert config.author.user_name == "Test User"
    assert config.description == "Test agent for unit testing"


def test_load_from_file():
    """Test loading configuration from file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write(SAMPLE_YAML)
        temp_file = f.name

    try:
        config = AgentConfigLoader.from_file(temp_file)

        assert config.agent_code == "TEST_AGENT"
        assert config.waterway.waterway_id == 1
        assert config.waterway.waterway_name == "Test Waterway"
    finally:
        os.unlink(temp_file)


def test_get_agent_code():
    """Test get_agent_code convenience method."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)
    assert config.get_agent_code() == "TEST_AGENT"


def test_get_hydros_objects_modeling_url():
    """Test get_hydros_objects_modeling_url convenience method."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)
    assert config.get_hydros_objects_modeling_url() == "http://example.com/objects.yaml"


def test_get_idz_config_url():
    """Test get_idz_config_url convenience method."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)
    assert config.get_idz_config_url() == "http://example.com/idz.yaml"


def test_get_time_series_config_url():
    """Test get_time_series_config_url convenience method."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)
    assert config.get_time_series_config_url() == "http://example.com/timeseries.yaml"


def test_get_mqtt_broker_config():
    """Test get_mqtt_broker_config convenience method."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)
    mqtt_broker = config.get_mqtt_broker_config()

    assert mqtt_broker is not None
    assert mqtt_broker.mqtt_host == "localhost"
    assert mqtt_broker.mqtt_port == 1883
    assert mqtt_broker.server_uri == "tcp://localhost:1883"


def test_get_property():
    """Test get_property generic accessor."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)

    assert config.get_property('step_resolution') == 60
    assert config.get_property('total_steps') == 100
    assert config.get_property('hydro_environment_type') == "TEST"
    assert config.get_property('nonexistent_key', 'default') == 'default'


def test_properties_access():
    """Test direct property access."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)

    assert config.properties.biz_start_time == "2025/01/01 00:00:00"
    assert config.properties.step_resolution == 60
    assert config.properties.total_steps == 100
    assert config.properties.driven_by_coordinator is True
    assert config.properties.hydro_environment_type == "TEST"


def test_output_config_access():
    """Test output configuration access."""
    config = AgentConfigLoader.from_yaml_string(SAMPLE_YAML)

    assert config.properties.output_config is not None
    assert config.properties.output_config.output_mode == "MQTT"
    assert config.properties.output_config.mqtt_topic == "test/topic"


def test_minimal_config():
    """Test loading minimal configuration without optional fields."""
    minimal_yaml = """agent_code: MINIMAL_AGENT
agent_type: MINIMAL_TYPE
agent_name: Minimal Agent
version: v1.0.0
release_at: 2026/01/01
author:
  user_name: Test User
description: Minimal test agent
waterway:
  waterway_id: 1
  waterway_name: Test Waterway
properties:
  hydros_objects_modeling_url: http://example.com/objects.yaml
"""

    config = AgentConfigLoader.from_yaml_string(minimal_yaml)

    assert config.agent_code == "MINIMAL_AGENT"
    assert config.get_hydros_objects_modeling_url() == "http://example.com/objects.yaml"
    assert config.properties.step_resolution is None
    assert config.properties.output_config is None
    assert config.get_mqtt_broker_config() is None


def test_invalid_yaml():
    """Test handling of invalid YAML."""
    invalid_yaml = "invalid: yaml: content: ["

    with pytest.raises(ValueError, match="Invalid YAML content"):
        AgentConfigLoader.from_yaml_string(invalid_yaml)


def test_missing_required_fields():
    """Test handling of missing required fields."""
    incomplete_yaml = """agent_code: TEST_AGENT
agent_type: TEST_TYPE
"""

    with pytest.raises(ValueError):
        AgentConfigLoader.from_yaml_string(incomplete_yaml)


def test_file_not_found():
    """Test handling of non-existent file."""
    with pytest.raises(FileNotFoundError):
        AgentConfigLoader.from_file("/nonexistent/path/config.yaml")


def test_from_dict():
    """Test creating configuration from dictionary."""
    data = {
        "agent_code": "DICT_AGENT",
        "agent_type": "DICT_TYPE",
        "agent_name": "Dict Agent",
        "version": "v1.0.0",
        "release_at": "2026/01/01",
        "author": {"user_name": "Test User"},
        "description": "Agent from dict",
        "waterway": {"waterway_id": 1, "waterway_name": "Test"},
        "properties": {
            "hydros_objects_modeling_url": "http://example.com/objects.yaml"
        }
    }

    config = AgentConfigLoader.from_dict(data)

    assert config.agent_code == "DICT_AGENT"
    assert config.get_hydros_objects_modeling_url() == "http://example.com/objects.yaml"


if __name__ == "__main__":
    # Run tests manually without pytest
    print("Running agent configuration tests...\n")

    tests = [
        ("Load from YAML string", test_load_from_yaml_string),
        ("Load from file", test_load_from_file),
        ("Get agent code", test_get_agent_code),
        ("Get hydros objects modeling URL", test_get_hydros_objects_modeling_url),
        ("Get IDZ config URL", test_get_idz_config_url),
        ("Get time series config URL", test_get_time_series_config_url),
        ("Get MQTT broker config", test_get_mqtt_broker_config),
        ("Get property", test_get_property),
        ("Properties access", test_properties_access),
        ("Output config access", test_output_config_access),
        ("Minimal config", test_minimal_config),
        ("From dict", test_from_dict),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            test_func()
            print(f"✓ {test_name}")
            passed += 1
        except Exception as e:
            print(f"✗ {test_name}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")

    # Test error cases
    print("\nTesting error cases...")

    error_tests = [
        ("Invalid YAML handling", test_invalid_yaml, ValueError),
        ("Missing required fields handling", test_missing_required_fields, ValueError),
        ("File not found handling", test_file_not_found, FileNotFoundError),
    ]

    for test_name, test_func, expected_exception in error_tests:
        try:
            test_func()
            print(f"✗ {test_name}: should have raised {expected_exception.__name__}")
        except expected_exception:
            print(f"✓ {test_name}")
        except Exception as e:
            print(f"✗ {test_name}: raised {type(e).__name__} instead of {expected_exception.__name__}")
