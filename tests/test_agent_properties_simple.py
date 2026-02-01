"""
Simple test script for AgentProperties without pytest dependency.

This script tests the AgentProperties class functionality.
"""

from hydros_agent_sdk.agent_properties import AgentProperties


def test_basic_operations():
    """Test basic dictionary operations."""
    print("Testing basic operations...")
    props = AgentProperties()
    props['key1'] = 'value1'
    props['key2'] = 123
    props['key3'] = 3.14

    assert props['key1'] == 'value1'
    assert props['key2'] == 123
    assert props['key3'] == 3.14
    assert len(props) == 3
    print("✓ Basic operations passed")


def test_get_property_as_integer():
    """Test getting property as integer."""
    print("Testing get_property_as_integer...")
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

    print("✓ get_property_as_integer passed")


def test_get_property_as_string():
    """Test getting property as string."""
    print("Testing get_property_as_string...")
    props = AgentProperties()

    # Test with string value
    props['str_val'] = 'hello'
    assert props.get_property_as_string('str_val') == 'hello'

    # Test with integer value
    props['int_val'] = 42
    assert props.get_property_as_string('int_val') == '42'

    print("✓ get_property_as_string passed")


def test_get_property_as_float():
    """Test getting property as float."""
    print("Testing get_property_as_float...")
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

    print("✓ get_property_as_float passed")


def test_get_property_as_bool():
    """Test getting property as boolean."""
    print("Testing get_property_as_bool...")
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

    print("✓ get_property_as_bool passed")


def test_get_property_with_default():
    """Test getting property with default value."""
    print("Testing get_property with default...")
    props = AgentProperties()
    props['existing'] = 'value'

    # Test with existing property
    assert props.get_property('existing', 'default') == 'value'

    # Test with missing property
    assert props.get_property('missing', 'default') == 'default'
    assert props.get_property('missing') is None

    print("✓ get_property with default passed")


def test_error_handling():
    """Test error handling for invalid operations."""
    print("Testing error handling...")
    props = AgentProperties()

    # Test missing property
    try:
        props.get_property_as_integer('missing')
        assert False, "Should have raised KeyError"
    except KeyError:
        pass

    # Test invalid conversion
    props['invalid'] = 'not_a_number'
    try:
        props.get_property_as_integer('invalid')
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    print("✓ Error handling passed")


def test_update_from_dict():
    """Test updating properties from dictionary."""
    print("Testing update from dict...")
    props = AgentProperties()
    props.update({
        'key1': 'value1',
        'key2': 123,
        'key3': 3.14,
        'key4': True
    })

    assert len(props) == 4
    assert props['key1'] == 'value1'
    assert props['key2'] == 123
    assert props['key3'] == 3.14
    assert props['key4'] is True

    print("✓ Update from dict passed")


def main():
    """Run all tests."""
    print("=" * 70)
    print("Testing AgentProperties")
    print("=" * 70)

    try:
        test_basic_operations()
        test_get_property_as_integer()
        test_get_property_as_string()
        test_get_property_as_float()
        test_get_property_as_bool()
        test_get_property_with_default()
        test_error_handling()
        test_update_from_dict()

        print("=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        return 0

    except AssertionError as e:
        print(f"✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
