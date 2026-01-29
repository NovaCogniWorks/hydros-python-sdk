#!/usr/bin/env python3
"""
Complete validation script for the refactored agent system.

This script validates:
1. Configuration file loading
2. Agent creation with config
3. Callback initialization
4. Circular dependency resolution
5. All components working together
"""

import sys
import os
from pathlib import Path

# Add parent directory and examples directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

def test_config_loading():
    """Test configuration file loading."""
    print("=" * 70)
    print("Test 1: Configuration Loading")
    print("=" * 70)

    from configparser import ConfigParser

    config_file = "examples/agent.properties"

    if not os.path.exists(config_file):
        print(f"❌ Config file not found: {config_file}")
        return False

    try:
        config = ConfigParser()
        with open(config_file, 'r') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        required = ['agent_code', 'agent_type', 'agent_name', 'agent_configuration_url']
        for key in required:
            value = config.get('DEFAULT', key)
            print(f"  ✓ {key}: {value}")

        print("✓ Configuration loading: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ Configuration loading: FAILED - {e}\n")
        return False


def test_factory_creation():
    """Test agent factory creation."""
    print("=" * 70)
    print("Test 2: Agent Factory Creation")
    print("=" * 70)

    try:
        from agent_example import MySampleAgentFactory

        factory = MySampleAgentFactory(config_file="examples/agent.properties")
        print(f"  ✓ Factory created: {factory}")
        print(f"  ✓ Config file: {factory.config_file}")

        print("✓ Factory creation: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ Factory creation: FAILED - {e}\n")
        return False


def test_callback_creation():
    """Test callback creation without client."""
    print("=" * 70)
    print("Test 3: Callback Creation (No Circular Dependency)")
    print("=" * 70)

    try:
        from agent_example import (
            MySampleAgentFactory,
            MultiAgentCoordinationCallback
        )

        factory = MySampleAgentFactory(config_file="examples/agent.properties")
        callback = MultiAgentCoordinationCallback(
            agent_factory=factory,
            config_file="examples/agent.properties"
        )

        print(f"  ✓ Callback created: {callback}")
        print(f"  ✓ Component name: {callback.get_component()}")
        print(f"  ✓ Client reference: {callback._client}")

        if callback._client is None:
            print("  ✓ No circular dependency in constructor")

        print("✓ Callback creation: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ Callback creation: FAILED - {e}\n")
        return False


def test_client_creation():
    """Test client creation with callback."""
    print("=" * 70)
    print("Test 4: Client Creation with Callback")
    print("=" * 70)

    try:
        from hydros_agent_sdk.coordination_client import SimCoordinationClient
        from agent_example import (
            MySampleAgentFactory,
            MultiAgentCoordinationCallback
        )

        factory = MySampleAgentFactory(config_file="examples/agent.properties")
        callback = MultiAgentCoordinationCallback(
            agent_factory=factory,
            config_file="examples/agent.properties"
        )

        # Create client (this should work without circular dependency)
        client = SimCoordinationClient(
            broker_url="tcp://localhost",
            broker_port=1883,
            topic="/test/topic",
            callback=callback
        )

        print(f"  ✓ Client created: {client}")
        print(f"  ✓ Client ID: {client.client_id}")
        print(f"  ✓ Callback reference in client: {client.callback}")

        print("✓ Client creation: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ Client creation: FAILED - {e}\n")
        return False


def test_set_client():
    """Test setting client reference in callback."""
    print("=" * 70)
    print("Test 5: Set Client Reference (Breaking Circular Dependency)")
    print("=" * 70)

    try:
        from hydros_agent_sdk.coordination_client import SimCoordinationClient
        from agent_example import (
            MySampleAgentFactory,
            MultiAgentCoordinationCallback
        )

        factory = MySampleAgentFactory(config_file="examples/agent.properties")
        callback = MultiAgentCoordinationCallback(
            agent_factory=factory,
            config_file="examples/agent.properties"
        )

        client = SimCoordinationClient(
            broker_url="tcp://localhost",
            broker_port=1883,
            topic="/test/topic",
            callback=callback
        )

        print(f"  ✓ Before set_client: callback._client = {callback._client}")

        # Set client reference
        callback.set_client(client)

        print(f"  ✓ After set_client: callback._client = {callback._client}")
        print(f"  ✓ Client reference established")

        # Verify bidirectional reference
        assert callback._client is client
        assert client.callback is callback
        print(f"  ✓ Bidirectional reference verified")

        print("✓ Set client reference: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ Set client reference: FAILED - {e}\n")
        return False


def test_agent_creation():
    """Test agent creation with all components."""
    print("=" * 70)
    print("Test 6: Agent Creation with Configuration")
    print("=" * 70)

    try:
        from hydros_agent_sdk.coordination_client import SimCoordinationClient
        from hydros_agent_sdk.protocol.models import SimulationContext
        from agent_example import (
            MySampleAgentFactory,
            MultiAgentCoordinationCallback,
            MySampleHydroAgent
        )

        # Setup
        factory = MySampleAgentFactory(config_file="examples/agent.properties")
        callback = MultiAgentCoordinationCallback(
            agent_factory=factory,
            config_file="examples/agent.properties"
        )
        client = SimCoordinationClient(
            broker_url="tcp://localhost",
            broker_port=1883,
            topic="/test/topic",
            callback=callback
        )
        callback.set_client(client)

        # Create test context
        context = SimulationContext(
            biz_scene_instance_id="test_context_001"
        )

        # Create agent
        agent = factory.create_agent(
            sim_coordination_client=client,
            context=context
        )

        print(f"  ✓ Agent created: {agent}")
        print(f"  ✓ Agent type: {type(agent).__name__}")
        print(f"  ✓ Agent config loaded: {agent.config}")
        print(f"  ✓ Agent code: {agent.config['agent_code']}")
        print(f"  ✓ Agent name: {agent.config['agent_name']}")
        print(f"  ✓ Context ID: {agent.biz_scene_instance_id}")

        print("✓ Agent creation: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ Agent creation: FAILED - {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_alternative_config():
    """Test with alternative configuration file."""
    print("=" * 70)
    print("Test 7: Alternative Configuration File")
    print("=" * 70)

    try:
        from agent_example import MySampleAgentFactory

        factory = MySampleAgentFactory(
            config_file="examples/agent_alternative.properties"
        )

        print(f"  ✓ Factory created with alternative config")
        print(f"  ✓ Config file: {factory.config_file}")

        print("✓ Alternative config: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ Alternative config: FAILED - {e}\n")
        return False


def test_missing_config():
    """Test error handling for missing config file."""
    print("=" * 70)
    print("Test 8: Missing Configuration File (Error Handling)")
    print("=" * 70)

    try:
        from hydros_agent_sdk.coordination_client import SimCoordinationClient
        from hydros_agent_sdk.protocol.models import SimulationContext
        from agent_example import MySampleAgentFactory

        factory = MySampleAgentFactory(config_file="examples/nonexistent.properties")

        # Try to create agent - should fail
        context = SimulationContext(biz_scene_instance_id="test")

        # Create a dummy client
        from agent_example import MultiAgentCoordinationCallback
        callback = MultiAgentCoordinationCallback(
            agent_factory=factory,
            config_file="examples/agent.properties"
        )
        client = SimCoordinationClient(
            broker_url="tcp://localhost",
            broker_port=1883,
            topic="/test",
            callback=callback
        )

        try:
            agent = factory.create_agent(client, context)
            print(f"  ❌ Should have raised FileNotFoundError")
            return False
        except FileNotFoundError as e:
            print(f"  ✓ Correctly raised FileNotFoundError: {e}")
            print("✓ Error handling: PASSED\n")
            return True

    except Exception as e:
        print(f"❌ Error handling test: FAILED - {e}\n")
        return False


def main():
    """Run all validation tests."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "HYDROS AGENT SYSTEM VALIDATION" + " " * 23 + "║")
    print("╚" + "=" * 68 + "╝")
    print("\n")

    tests = [
        ("Configuration Loading", test_config_loading),
        ("Factory Creation", test_factory_creation),
        ("Callback Creation", test_callback_creation),
        ("Client Creation", test_client_creation),
        ("Set Client Reference", test_set_client),
        ("Agent Creation", test_agent_creation),
        ("Alternative Config", test_alternative_config),
        ("Error Handling", test_missing_config),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Test '{name}' crashed: {e}\n")
            results.append((name, False))

    # Summary
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASSED" if result else "❌ FAILED"
        print(f"  {status:12s} - {name}")

    print("-" * 70)
    print(f"  Total: {passed}/{total} tests passed")
    print("=" * 70)

    if passed == total:
        print("\n🎉 All validation tests PASSED! System is ready to use.\n")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) FAILED. Please review the errors above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
