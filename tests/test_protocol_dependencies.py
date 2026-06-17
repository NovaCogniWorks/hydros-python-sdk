import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = PROJECT_ROOT / "hydros_agent_sdk" / "protocol"


class ProtocolDependencyTest(unittest.TestCase):
    def test_protocol_package_does_not_import_mpc_package(self):
        offenders = []
        for path in sorted(PROTOCOL_ROOT.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "hydros_agent_sdk.mpc" or alias.name.startswith("hydros_agent_sdk.mpc."):
                            offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "hydros_agent_sdk.mpc" or module.startswith("hydros_agent_sdk.mpc."):
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

        self.assertEqual([], offenders)

    def test_importing_protocol_commands_does_not_load_mpc_package(self):
        self.assert_import_does_not_load_mpc("import hydros_agent_sdk.protocol.commands")

    def test_importing_root_package_does_not_load_mpc_package(self):
        self.assert_import_does_not_load_mpc("import hydros_agent_sdk")

    def test_importing_agents_package_does_not_load_mpc_package(self):
        self.assert_import_does_not_load_mpc("import hydros_agent_sdk.agents")

    def test_field_metrics_cache_sensor_data_conversion_does_not_load_mpc_package(self):
        self.assert_import_does_not_load_mpc(
            "from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache; "
            "cache = FieldMetricsCache(max_steps=3); "
            "cache.update({'object_id': 1, 'metrics_code': 'water_level', 'position_code': 'none', 'value': 2.5}); "
            "cache.to_sensor_data()"
        )

    def test_mpc_models_does_not_export_sensor_data(self):
        script = "import hydros_agent_sdk.mpc.models as models; print(hasattr(models, 'SensorData'))"
        result = self.run_python(script)

        self.assertEqual("False", result.stdout.strip())

    def assert_import_does_not_load_mpc(self, import_statement):
        script = (
            "import sys; "
            f"{import_statement}; "
            "print(any(name == 'hydros_agent_sdk.mpc' or name.startswith('hydros_agent_sdk.mpc.') "
            "for name in sys.modules))"
        )
        result = self.run_python(script)

        self.assertEqual("False", result.stdout.strip())

    def run_python(self, script):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
