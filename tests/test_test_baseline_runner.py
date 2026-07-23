import importlib.util
import unittest
from pathlib import Path


def load_runner_module():
    project_root = Path(__file__).resolve().parents[1]
    runner_path = project_root / "scripts" / "run_test_baseline.py"
    spec = importlib.util.spec_from_file_location("run_test_baseline", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBaselineRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner_module()

    def test_central_baseline_includes_event_injection_and_direct_mpc_guards(self):
        names = self.runner.names_for_mode("central")

        self.assertIn("tests.test_central_scheduling_event_injection", names)
        self.assertIn(
            "tests.test_agent_commands_refactor.AgentCommandsRefactorTest."
            "test_central_scheduling_agent_activates_mpc_on_time_series_update",
            names,
        )
        self.assertIn(
            "tests.test_agent_commands_refactor.AgentCommandsRefactorTest."
            "test_central_scheduling_agent_fails_without_rolling_config",
            names,
        )

    def test_sdk_baseline_excludes_optional_dependency_tests(self):
        names = self.runner.names_for_mode("sdk")

        self.assertIn("tests.test_central_scheduling_event_injection", names)
        for module_name in self.runner.OPTIONAL_DEPENDENCY_TEST_MODULES:
            self.assertNotIn(f"tests.{module_name}", names)

    def test_full_baseline_keeps_optional_dependency_tests_visible(self):
        names = self.runner.names_for_mode("full")

        for module_name in self.runner.OPTIONAL_DEPENDENCY_TEST_MODULES:
            self.assertIn(f"tests.{module_name}", names)

    def test_central_router_suite_collects_router_function_tests(self):
        suite = self.runner.load_unittest_suite(
            self.runner.names_for_mode("central-router"),
            function_test_modules=self.runner.RELATED_ROUTER_TESTS,
        )
        central_suite = self.runner.load_unittest_suite(
            self.runner.names_for_mode("central")
        )

        self.assertGreater(suite.countTestCases(), central_suite.countTestCases())

    def test_compile_baseline_passes_current_sources(self):
        self.assertEqual(self.runner.run_compile_baseline(), 0)


if __name__ == "__main__":
    unittest.main()
