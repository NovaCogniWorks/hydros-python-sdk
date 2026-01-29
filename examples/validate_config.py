#!/usr/bin/env python3
"""
Complete configuration validation script.

This script validates both agent.properties and env.properties files.
"""

import sys
import os
from configparser import ConfigParser


def validate_agent_config(config_file="examples/agent.properties"):
    """Validate agent configuration file."""
    print("=" * 70)
    print("Agent Configuration Validation")
    print("=" * 70)

    if not os.path.exists(config_file):
        print(f"❌ Agent config file not found: {config_file}")
        return False

    print(f"✓ Config file found: {config_file}")

    try:
        config = ConfigParser()
        with open(config_file, 'r') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        print("✓ Config file parsed successfully\n")

        # Required properties
        required_props = ['agent_code', 'agent_type', 'agent_name', 'agent_configuration_url']

        print("Required Properties:")
        print("-" * 70)

        all_present = True
        for prop in required_props:
            value = config.get('DEFAULT', prop, fallback=None)
            if value:
                print(f"✓ {prop:30s} = {value}")
            else:
                print(f"❌ {prop:30s} = MISSING")
                all_present = False

        # Optional properties
        optional_props = ['drive_mode', 'hydros_cluster_id', 'hydros_node_id']
        print("\nOptional Properties:")
        print("-" * 70)
        for prop in optional_props:
            value = config.get('DEFAULT', prop, fallback='(not set)')
            print(f"  {prop:30s} = {value}")

        print("-" * 70)

        if all_present:
            print("\n✓ Agent configuration is valid\n")
            return True
        else:
            print("\n❌ Agent configuration has missing required properties\n")
            return False

    except Exception as e:
        print(f"\n❌ Error loading agent config: {e}\n")
        return False


def validate_env_config(env_file="examples/env.properties"):
    """Validate environment configuration file."""
    print("=" * 70)
    print("Environment Configuration Validation")
    print("=" * 70)

    if not os.path.exists(env_file):
        print(f"❌ Environment config file not found: {env_file}")
        return False

    print(f"✓ Config file found: {env_file}")

    try:
        config = ConfigParser()
        with open(env_file, 'r') as f:
            config_string = '[DEFAULT]\n' + f.read()
        config.read_string(config_string)

        print("✓ Config file parsed successfully\n")

        # Required properties
        required_props = ['mqtt_broker_url', 'mqtt_broker_port', 'mqtt_topic']

        print("Required Properties:")
        print("-" * 70)

        all_present = True
        for prop in required_props:
            value = config.get('DEFAULT', prop, fallback=None)
            if value:
                print(f"✓ {prop:30s} = {value}")
            else:
                print(f"❌ {prop:30s} = MISSING")
                all_present = False

        print("-" * 70)

        if all_present:
            # Validate values
            print("\nValidation:")
            print("-" * 70)

            broker_url = config.get('DEFAULT', 'mqtt_broker_url')
            if broker_url.startswith('tcp://') or broker_url.startswith('ssl://'):
                print(f"✓ Broker URL format is valid")
            else:
                print(f"⚠️  Broker URL should start with tcp:// or ssl://")

            try:
                port = int(config.get('DEFAULT', 'mqtt_broker_port'))
                if 1 <= port <= 65535:
                    print(f"✓ Broker port is valid: {port}")
                else:
                    print(f"❌ Broker port out of range (1-65535): {port}")
                    all_present = False
            except ValueError:
                print(f"❌ Broker port is not a valid integer")
                all_present = False

            topic = config.get('DEFAULT', 'mqtt_topic')
            if topic.startswith('/'):
                print(f"✓ Topic format is valid")
            else:
                print(f"⚠️  Topic should start with /")

            print("-" * 70)

        if all_present:
            print("\n✓ Environment configuration is valid\n")
            return True
        else:
            print("\n❌ Environment configuration has errors\n")
            return False

    except Exception as e:
        print(f"\n❌ Error loading environment config: {e}\n")
        return False


def main():
    """Main entry point."""
    print()
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 20 + "CONFIGURATION VALIDATION" + " " * 24 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    # Validate both configurations
    agent_valid = validate_agent_config()
    env_valid = validate_env_config()

    # Summary
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    if agent_valid:
        print("✓ Agent Configuration (agent.properties) - VALID")
    else:
        print("❌ Agent Configuration (agent.properties) - INVALID")

    if env_valid:
        print("✓ Environment Configuration (env.properties) - VALID")
    else:
        print("❌ Environment Configuration (env.properties) - INVALID")

    print("=" * 70)

    if agent_valid and env_valid:
        print("\n🎉 All configurations are valid!")
        print("\nYou can now run:")
        print("  python3 examples/agent_example.py")
        print()
        return 0
    else:
        print("\n⚠️  Some configurations have errors.")
        print("\nPlease fix the errors above before running the agent.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
