import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("custom-agent/pump/scheduling"))

from hydros_agent_sdk import (  # noqa: E402
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    ControlTaskType,
)
from odd_dmpc.control_algorithm import (  # noqa: E402
    OddDmpcControlAlgorithm,
    OddDmpcSolveArguments,
)
from odd_dmpc.types import ControlAction  # noqa: E402


class _StationContext:
    station_id = 2001


class _Resolver:
    def __init__(self, mode="ODD2"):
        self.mode = mode

    def resolve(self, input_data):
        return OddDmpcSolveArguments(
            mode=self.mode,
            station_ctx=_StationContext(),
            upstream_prediction={1001: 32.5},
            disturbance_forecast={1: {"rain": 0.0}},
            transfer_bundle=object(),
            station_memory=object(),
        )


class _LocalController:
    def __init__(self, action):
        self.action = action
        self.calls = []

    def solve(self, **kwargs):
        self.calls.append(kwargs)
        return self.action


class OddDmpcControlAlgorithmTest(unittest.TestCase):
    def test_projects_local_action_to_standard_output(self):
        local_controller = _LocalController(self._action(mode="ODD2"))
        algorithm = OddDmpcControlAlgorithm(local_controller, _Resolver())
        runtime = ControlAlgorithmRuntime()
        runtime.register(algorithm)

        output = runtime.solve(self._input())

        self.assertEqual(output.status, ControlAlgorithmStatus.CONTINUE)
        self.assertEqual(output.request_id, "scene-001:12:2001:odd_dmpc")
        self.assertEqual(output.actuator_targets[0].object_id, 2101)
        self.assertEqual(output.actuator_targets[0].target_values["blade_angle"], 42.5)
        self.assertEqual(output.actuator_targets[1].target_values["unit_status"], 0.0)
        self.assertEqual(output.results[0].value_type, "water_flow")
        self.assertEqual(output.results[0].value, 35.0)
        self.assertEqual(output.next_state["unit_status"], {"2101": 1, "2102": 0})
        self.assertEqual(output.evidence["candidate_plan_count"], 1)
        self.assertEqual(local_controller.calls[0]["mode"], "ODD2")

    def test_odd1_is_exposed_as_hold(self):
        algorithm = OddDmpcControlAlgorithm(
            _LocalController(self._action(mode="ODD1")),
            _Resolver(mode="ODD1"),
        )

        output = algorithm.solve(self._input())

        self.assertEqual(output.status, ControlAlgorithmStatus.HOLD)
        self.assertEqual(output.reason, "ODD_DMPC_ODD1")

    def test_rejects_other_control_task_types_and_station_mismatch(self):
        algorithm = OddDmpcControlAlgorithm(
            _LocalController(self._action(mode="ODD2")),
            _Resolver(),
        )
        unsupported = algorithm.solve(
            self._input(control_task_type=ControlTaskType.DIRECT_ACTUATOR_CONTROL)
        )
        mismatch = algorithm.solve(self._input(target_object_id=2002))

        self.assertEqual(unsupported.error_code, "UNSUPPORTED_CONTROL_TASK")
        self.assertEqual(mismatch.error_code, "TARGET_STATION_MISMATCH")

    @staticmethod
    def _input(
        control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
        target_object_id=2001,
    ):
        return ControlAlgorithmInput(
            schema_version="1.0",
            algorithm_type="odd_dmpc",
            algorithm_version="1.0.0",
            control_task_type=control_task_type,
            context=ControlAlgorithmContext(
                request_id="scene-001:12:2001:odd_dmpc",
                context_id="scene-001",
                step_index=12,
                target_object_type="PumpStation",
                target_object_id=target_object_id,
            ),
        )

    @staticmethod
    def _action(mode):
        return ControlAction(
            station_id=2001,
            mode=mode,
            selected_flow=35.0,
            unit_status={2101: 1, 2102: 0},
            unit_openings={2101: 42.5, 2102: 0.0},
            unit_flows={2101: 35.0, 2102: 0.0},
            fit_score=0.86,
            objective=0.14,
            predicted_flow_error=0.4,
            predicted_level_error=0.08,
            predicted_back_level=12.6,
            predicted_front_level=11.3,
            predicted_head=1.3,
            candidate_plans=[{"success": True}],
        )


if __name__ == "__main__":
    unittest.main()
