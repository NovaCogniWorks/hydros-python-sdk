import unittest

from pydantic import ValidationError

from hydros_agent_sdk.mpc.models import MpcOptimizeResponse, ValueItem


class MpcModelsContractTest(unittest.TestCase):
    def test_parses_and_emits_central_horizon_step_shape(self):
        payload = {
            "plan_type": "OPTIMAL",
            "horizon_controls": [
                {
                    "horizon_step": 1,
                    "control_object_list": [
                        {
                            "object_type": "GateStation",
                            "object_id": 101,
                            "object_name": "Gate Station 101",
                            "target_value_list": [
                                {"value_type": "water_level", "value": 3.5},
                                {"value_type": "enabled", "value": True},
                            ],
                            "algo_required_inputs": [
                                {
                                    "type": "REFERENCE",
                                    "object_type": "GateStation",
                                    "object_id": 101,
                                    "value_type": "front_water_level",
                                    "value": 3.4,
                                    "series": [3.4, 3.6],
                                    "attributes": {"source": "mpc"},
                                }
                            ],
                        }
                    ],
                    "predicted_result_list": [
                        {
                            "object_type": "GateStation",
                            "object_id": 101,
                            "object_name": "Gate Station 101",
                            "target_value": {
                                "value_type": "water_level",
                                "value": 3.5,
                            },
                            "predicted_value_list": [
                                {"value_type": "front_water_level", "value": 3.4},
                                {"value_type": "back_water_level", "value": 3.1},
                                {"value_type": "out_flow", "value": 18.5},
                            ],
                            "device_result_list": [
                                {
                                    "object_type": "Gate",
                                    "object_id": 501,
                                    "object_name": "Gate 501",
                                    "value_list": [
                                        {"value_type": "gate_opening", "value": 0.45}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        response = MpcOptimizeResponse.model_validate(payload)
        horizon = response.horizon_controls[0]

        control_values = horizon.control_object_list[0].target_value_list
        algo_required_inputs = horizon.control_object_list[0].algo_required_inputs
        prediction = horizon.predicted_result_list[0]
        self.assertEqual(control_values[0].numeric_value(), 3.5)
        self.assertIsNone(control_values[1].numeric_value())
        self.assertEqual(algo_required_inputs[0].series, [3.4, 3.6])
        self.assertEqual(prediction.target_value.value_type, "water_level")
        self.assertEqual(prediction.device_result_list[0].object_id, 501)
        self.assertEqual(
            response.model_dump(mode="json", by_alias=True, exclude_none=True),
            payload,
        )

    def test_value_item_only_exposes_numeric_scalars_as_control_values(self):
        self.assertEqual(ValueItem(value_type="water_level", value=2).numeric_value(), 2.0)
        self.assertIsNone(ValueItem(value_type="enabled", value=True).numeric_value())
        self.assertIsNone(ValueItem(value_type="label", value="manual").numeric_value())

    def test_rejects_removed_flat_result_fields(self):
        with self.assertRaises(ValidationError):
            MpcOptimizeResponse.model_validate(
                {
                    "horizon_controls": [
                        {
                            "horizon_step": 1,
                            "control_object_list": [
                                {
                                    "object_type": "Gate",
                                    "object_id": 501,
                                    "target_value": 0.45,
                                    "target_value_type": "OPENING",
                                }
                            ],
                        }
                    ]
                }
            )
        with self.assertRaises(ValidationError):
            MpcOptimizeResponse.model_validate(
                {
                    "horizon_controls": [
                        {
                            "horizon_step": 1,
                            "predicted_result_list": [
                                {
                                    "object_type": "Canal",
                                    "object_id": 102,
                                    "front_water_level": 2.1,
                                    "final_target_value": 2.3,
                                    "final_target_value_type": "WATER_LEVEL",
                                }
                            ],
                        }
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
