"""
Tests for AgentProperties class.

This module tests the AgentProperties dictionary with typed accessor methods.
"""

import pytest
from hydros_agent_sdk.agent_properties import AgentProperties


def test_agent_properties_creation():
    """Test creating an AgentProperties instance."""
    props = AgentProperties()
    assert isinstance(props, dict)
    assert len(props) == 0


def test_agent_properties_set_get():
    """Test setting and getting properties."""
    props = AgentProperties()
    props['key1'] = 'value1'
    props['key2'] = 123

    assert props['key1'] == 'value1'
    assert props['key2'] == 123
    assert props.get('key1') == 'value1'
    assert props.get('key3', 'default') == 'default'


def test_get_property_as_integer():
    """Test getting property as integer."""
    props = AgentProperties()

    # Test with integer value
    props['int_val'] = 42
    assert props.get_property_as_integer('int_val') == 42

    # Test with float value
    props['float_val'] = 3.14
    assert props.get_property_as_integer('float_val') == 3

    # Test with string value
    props['str_val'] = '100'
    assert props.get_property_as_integer('str_val') == 100

    # Test with missing property
    with pytest.raises(KeyError):
        props.get_property_as_integer('missing')

    # Test with invalid value
    props['invalid'] = 'not_a_number'
    with pytest.raises(ValueError):
        props.get_property_as_integer('invalid')


def test_get_property_as_string():
    """Test getting property as string."""
    props = AgentProperties()

    # Test with string value
    props['str_val'] = 'hello'
    assert props.get_property_as_string('str_val') == 'hello'

    # Test with integer value
    props['int_val'] = 42
    assert props.get_property_as_string('int_val') == '42'

    # Test with missing property
    with pytest.raises(KeyError):
        props.get_property_as_string('missing')


def test_get_property_as_float():
    """Test getting property as float."""
    props = AgentProperties()

    # Test with float value
    props['float_val'] = 3.14
    assert props.get_property_as_float('float_val') == 3.14

    # Test with integer value
    props['int_val'] = 42
    assert props.get_property_as_float('int_val') == 42.0

    # Test with string value
    props['str_val'] = '2.718'
    assert props.get_property_as_float('str_val') == 2.718

    # Test with missing property
    with pytest.raises(KeyError):
        props.get_property_as_float('missing')

    # Test with invalid value
    props['invalid'] = 'not_a_number'
    with pytest.raises(ValueError):
        props.get_property_as_float('invalid')


def test_get_property_as_bool():
    """Test getting property as boolean."""
    props = AgentProperties()

    # Test with boolean value
    props['bool_val'] = True
    assert props.get_property_as_bool('bool_val') is True

    # Test with string values
    props['true_str'] = 'true'
    assert props.get_property_as_bool('true_str') is True

    props['yes_str'] = 'yes'
    assert props.get_property_as_bool('yes_str') is True

    props['false_str'] = 'false'
    assert props.get_property_as_bool('false_str') is False

    # Test with integer values
    props['one'] = 1
    assert props.get_property_as_bool('one') is True

    props['zero'] = 0
    assert props.get_property_as_bool('zero') is False

    # Test with missing property
    with pytest.raises(KeyError):
        props.get_property_as_bool('missing')


def test_get_property_with_default():
    """Test getting property with default value."""
    props = AgentProperties()
    props['existing'] = 'value'

    # Test with existing property
    assert props.get_property('existing', 'default') == 'value'

    # Test with missing property
    assert props.get_property('missing', 'default') == 'default'
    assert props.get_property('missing') is None


def test_agent_properties_update():
    """Test updating properties from dict."""
    props = AgentProperties()
    props.update({
        'key1': 'value1',
        'key2': 123,
        'key3': 3.14
    })

    assert len(props) == 3
    assert props['key1'] == 'value1'
    assert props['key2'] == 123
    assert props['key3'] == 3.14


def test_agent_properties_iteration():
    """Test iterating over properties."""
    props = AgentProperties()
    props.update({
        'key1': 'value1',
        'key2': 'value2',
        'key3': 'value3'
    })

    keys = list(props.keys())
    assert len(keys) == 3
    assert 'key1' in keys
    assert 'key2' in keys
    assert 'key3' in keys


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
