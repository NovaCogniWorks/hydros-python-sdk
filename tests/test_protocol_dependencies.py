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

    def assert_import_does_not_load_mpc(self, import_statement):
        script = (
            "import sys; "
            f"{import_statement}; "
            "print(any(name == 'hydros_agent_sdk.mpc' or name.startswith('hydros_agent_sdk.mpc.') "
            "for name in sys.modules))"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual("False", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
