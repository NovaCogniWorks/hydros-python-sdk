import unittest

from pydantic import ValidationError

from hydros_agent_sdk import ControlAlgorithmRuntime as PublicControlAlgorithmRuntime
from hydros_agent_sdk.control_algorithms import (
    ControlActuator,
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    ControlValueRange,
    SignalType,
)


class _HoldAlgorithm:
    algorithm_type = "hold_algorithm"
    algorithm_version = "1.0.0"

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.HOLD,
            reason="NO_CHANGE_REQUIRED",
        )


class _BrokenAlgorithm:
    algorithm_type = "broken_algorithm"
    algorithm_version = "1.0.0"

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        raise RuntimeError("solver unavailable")


class ControlAlgorithmsTest(unittest.TestCase):
    def test_models_keep_java_field_names_and_round_trip_locally(self):
        input_data = self._input()

        payload = input_data.model_dump(mode="json")
        decoded = ControlAlgorithmInput.model_validate(payload)

        self.assertIn("control_task_type", payload)
        self.assertIn("signals", payload)
        self.assertIn("actuators", payload)
        self.assertNotIn("controlTaskType", payload)
        self.assertEqual(decoded, input_data)
        self.assertEqual(decoded.signals[0].type, SignalType.TARGET)
        self.assertEqual(decoded.actuators[0].ranges["blade_angle"].max_value, 100.0)
        self.assertIs(PublicControlAlgorithmRuntime, ControlAlgorithmRuntime)

    def test_models_reject_unknown_fields_and_unknown_enum_values(self):
        payload = self._input().model_dump(mode="json")
        payload["unknown_field"] = True

        with self.assertRaises(ValidationError):
            ControlAlgorithmInput.model_validate(payload)

        payload = self._input().model_dump(mode="json")
        payload["control_task_type"] = "UNKNOWN_TASK"
        with self.assertRaises(ValidationError):
            ControlAlgorithmInput.model_validate(payload)

    def test_runtime_returns_hold_and_standard_failures(self):
        runtime = ControlAlgorithmRuntime()
        runtime.register(_HoldAlgorithm())
        runtime.register(_BrokenAlgorithm())

        hold_input = self._input(algorithm_type="hold_algorithm")
        self.assertEqual(runtime.solve(hold_input).status, ControlAlgorithmStatus.HOLD)

        unsupported = runtime.solve(self._input(algorithm_type="missing"))
        self.assertEqual(unsupported.status, ControlAlgorithmStatus.FAILED)
        self.assertEqual(unsupported.error_code, "UNSUPPORTED_ALGORITHM")

        broken = runtime.solve(self._input(algorithm_type="broken_algorithm"))
        self.assertEqual(broken.status, ControlAlgorithmStatus.FAILED)
        self.assertEqual(broken.error_code, "ALGORITHM_EXECUTION_FAILED")

    def test_runtime_rejects_duplicate_algorithm_type(self):
        runtime = ControlAlgorithmRuntime()
        runtime.register(_HoldAlgorithm())

        with self.assertRaises(ValueError):
            runtime.register(_HoldAlgorithm())

    @staticmethod
    def _input(algorithm_type: str = "odd_dmpc") -> ControlAlgorithmInput:
        return ControlAlgorithmInput(
            schema_version="1.0",
            algorithm_type=algorithm_type,
            algorithm_version="1.0.0",
            control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
            context=ControlAlgorithmContext(
                request_id="scene-001:12:2001:odd_dmpc",
                context_id="scene-001",
                step_index=12,
                elapsed_seconds=10.0,
                target_object_type="PumpStation",
                target_object_id=2001,
                attributes={"compute_step": 120},
            ),
            signals=[
                ControlSignal(
                    type=SignalType.TARGET,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="water_flow",
                    value=35.0,
                    series=[35.0, 36.0, 34.5],
                )
            ],
            actuators=[
                ControlActuator(
                    object_type="Pump",
                    object_id=2101,
                    available=True,
                    values={"unit_status": 1.0, "blade_angle": 40.0},
                    ranges={"blade_angle": ControlValueRange(min_value=0.0, max_value=100.0)},
                )
            ],
            state={"last_selected_flow": 32.8},
            parameters={"mode": "ODD2"},
        )


if __name__ == "__main__":
    unittest.main()
