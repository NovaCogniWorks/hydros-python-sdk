import unittest

from hydros_agent_sdk.mpc.models import ControlObjectResult, PredictedResult, ValueItem
from hydros_agent_sdk.mpc.mpc_result_factory import MpcResultFactory


class MpcResultFactoryTest(unittest.TestCase):
    def test_build_control_object_result(self):
        result = MpcResultFactory.build_control_object_result(
            object_id=501,
            object_type="Gate",
            object_name="Gate 501",
            target_value_list=[ValueItem(value_type="OPENING", value=0.45)],
        )

        self.assertIsInstance(result, ControlObjectResult)
        self.assertEqual(result.object_id, 501)
        self.assertEqual(result.object_name, "Gate 501")
        self.assertEqual(result.object_type, "Gate")
        self.assertEqual(len(result.target_value_list), 1)
        self.assertEqual(result.target_value_list[0].value, 0.45)
        self.assertEqual(result.target_value_list[0].value_type, "OPENING")

    def test_build_predicted_result(self):
        result = MpcResultFactory.build_predicted_result(
            object_id=102,
            object_type="Canal",
            target_value=ValueItem(value_type="WATER_LEVEL", value=2.3),
            predicted_value_list=[
                ValueItem(value_type="front_water_level", value=2.1),
                ValueItem(value_type="back_water_level", value=1.9),
                ValueItem(value_type="out_flow", value=33.0),
            ],
        )

        self.assertIsInstance(result, PredictedResult)
        self.assertEqual(result.object_id, 102)
        self.assertEqual(result.object_type, "Canal")
        self.assertEqual(result.target_value.value, 2.3)
        self.assertEqual(result.target_value.value_type, "WATER_LEVEL")
        values = {item.value_type: item.value for item in result.predicted_value_list}
        self.assertEqual(values["front_water_level"], 2.1)
        self.assertEqual(values["back_water_level"], 1.9)
        self.assertEqual(values["out_flow"], 33.0)


if __name__ == "__main__":
    unittest.main()
