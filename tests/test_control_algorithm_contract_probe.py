import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("custom-agent/pump"))

from control_algorithm_contract_probe import ControlAlgorithmContractProbe  # noqa: E402
from hydros_agent_sdk import (  # noqa: E402
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    ControlTaskType,
)


class ControlAlgorithmContractProbeTest(unittest.TestCase):
    def test_returns_hold_without_computing_or_proposing_actuator_targets(self):
        runtime = ControlAlgorithmRuntime()
        runtime.register(ControlAlgorithmContractProbe())

        output = runtime.solve(
            ControlAlgorithmInput(
                schema_version="1.0",
                algorithm_type="control_contract_probe",
                control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
                context=ControlAlgorithmContext(
                    request_id="scene-001:12:2001:control_contract_probe",
                    context_id="scene-001",
                    step_index=12,
                    target_object_type="PumpStation",
                    target_object_id=2001,
                ),
            )
        )

        self.assertEqual(ControlAlgorithmStatus.HOLD, output.status)
        self.assertEqual("CONTRACT_PROBE_ONLY", output.reason)
        self.assertEqual([], output.actuator_targets)
        self.assertEqual([], output.results)
        self.assertEqual({}, output.next_state)
        self.assertEqual("dry_run", output.evidence["mode"])


if __name__ == "__main__":
    unittest.main()
