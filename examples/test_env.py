#!/usr/bin/env python3
"""
Environment configuration validation script.

This script validates the env.properties file for MQTT broker settings.
"""

import sys
import os
from configparser import ConfigParser


def test_env_config():
    """Test environment configuration file."""
    print("=" * 70)
    print("Environment Configuration Validation")
    print("=" * 70)

    env_file = "examples/env.properties"

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

        print("Configuration Values:")
        print("-" * 70)

        all_present = True
        for prop in required_props:
            value = config.get('DEFAULT', prop, fallback=None)
            if value:
                print(f"✓ {prop:25s} = {value}")
            else:
                print(f"❌ {prop:25s} = MISSING")
                all_present = False

        print("-" * 70)

        if all_present:
            print("\n✓ All required MQTT configuration properties are present")

            # Validate values
            print("\nValidation:")
            print("-" * 70)

            broker_url = config.get('DEFAULT', 'mqtt_broker_url')
            if broker_url.startswith('tcp://') or broker_url.startswith('ssl://'):
                print(f"✓ Broker URL format is valid: {broker_url}")
            else:
                print(f"⚠️  Broker URL should start with tcp:// or ssl://: {broker_url}")

            try:
                port = int(config.get('DEFAULT', 'mqtt_broker_port'))
                if 1 <= port <= 65535:
                    print(f"✓ Broker port is valid: {port}")
                else:
                    print(f"❌ Broker port out of range (1-65535): {port}")
            except ValueError:
                print(f"❌ Broker port is not a valid integer")

            topic = config.get('DEFAULT', 'mqtt_topic')
            if topic.startswith('/'):
                print(f"✓ Topic format is valid: {topic}")
            else:
                print(f"⚠️  Topic should start with /: {topic}")

            print("-" * 70)
            return True
        else:
            print("\n❌ Some required properties are missing")
            return False

    except Exception as e:
        print(f"\n❌ Error loading config file: {e}")
        return False


def main():
    """Main entry point."""
    print()
    success = test_env_config()
    print()

    if success:
        print("=" * 70)
        print("✓ Environment configuration is valid")
        print("=" * 70)
        print("\nYou can now run:")
        print("  python3 examples/agent_example.py")
        print()
        return 0
    else:
        print("=" * 70)
        print("❌ Environment configuration has errors")
        print("=" * 70)
        print("\nPlease fix the errors in examples/env.properties")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
