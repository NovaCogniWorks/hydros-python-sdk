import tempfile
import unittest
from pathlib import Path

from hydros_agent_sdk import AgentBehavior, CustomAgent
from hydros_agent_sdk.factory import BehaviorAgentFactory, CustomAgentFactory, HydroAgentFactory
from hydros_agent_sdk.runtime.behavior_agent_adapter import BehaviorAgentAdapter
from hydros_agent_sdk.runtime.custom_agent_runtime_adapter import CustomAgentRuntimeAdapter


class StubAgent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class StubBehavior:
    pass


class HydroAgentFactoryTest(unittest.TestCase):
    def test_create_agent_loads_configuration_from_base_factory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_file = Path(temporary_directory) / "agent.properties"
            config_file.write_text(
                "agent_code=TEST_AGENT\n"
                "agent_type=TEST_AGENT_TYPE\n"
                "agent_name=Test Agent\n",
                encoding="utf-8",
            )
            factory = HydroAgentFactory(
                StubAgent,
                config_file=str(config_file),
                env_config={
                    "hydros_cluster_id": "test-cluster",
                    "hydros_node_id": "test-node",
                },
            )

            agent = factory.create_agent(
                sim_coordination_client=object(),
                context=object(),
            )

        self.assertEqual("TEST_AGENT", agent.agent_code)
        self.assertEqual("TEST_AGENT_TYPE", agent.agent_type)
        self.assertEqual("Test Agent", agent.agent_name)
        self.assertEqual("test-cluster", agent.hydros_cluster_id)
        self.assertEqual("test-node", agent.hydros_node_id)
        self.assertTrue(agent.agent_id.endswith("_TEST_AGENT"))

    def test_custom_agent_factory_inherits_base_config_loader(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_file = Path(temporary_directory) / "agent.properties"
            config_file.write_text(
                "agent_code=TEST_AGENT\n"
                "agent_type=TEST_AGENT_TYPE\n"
                "agent_name=Test Agent\n",
                encoding="utf-8",
            )
            factory = CustomAgentFactory(
                StubBehavior,
                config_file=str(config_file),
            )

            config = factory._load_config(str(config_file))

        self.assertEqual("TEST_AGENT", config["agent_code"])

    def test_legacy_behavior_factory_alias_accepts_behavior_class_keyword(self):
        factory = BehaviorAgentFactory(behavior_class=StubBehavior)

        self.assertIsInstance(factory, CustomAgentFactory)
        self.assertIs(factory.custom_agent_class, StubBehavior)

    def test_legacy_custom_agent_aliases_remain_available(self):
        self.assertIs(AgentBehavior, CustomAgent)
        self.assertIs(BehaviorAgentAdapter, CustomAgentRuntimeAdapter)


if __name__ == "__main__":
    unittest.main()
