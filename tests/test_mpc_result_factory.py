import unittest

from hydros_agent_sdk.mpc.models import ControlObjectResult, PredictedResult
from hydros_agent_sdk.mpc.mpc_result_factory import MpcResultFactory


class MpcResultFactoryTest(unittest.TestCase):
    def test_build_control_object_result(self):
        result = MpcResultFactory.build_control_object_result(
            object_id=501,
            target_value=0.45,
            object_type="Gate",
            node_id=101,
            node_name="Gate Station 101",
            object_name="Gate 501",
            target_value_type="OPENING",
        )

        self.assertIsInstance(result, ControlObjectResult)
        self.assertEqual(result.node_id, 101)
        self.assertEqual(result.node_name, "Gate Station 101")
        self.assertEqual(result.object_id, 501)
        self.assertEqual(result.object_name, "Gate 501")
        self.assertEqual(result.target_value, 0.45)
        self.assertEqual(result.target_value_type, "OPENING")
        self.assertEqual(result.object_type, "Gate")

    def test_build_predicted_result(self):
        result = MpcResultFactory.build_predicted_result(
            object_id=102,
            object_type="Canal",
            front_water_level=2.1,
            final_target_value=2.3,
            final_target_value_type="WATER_LEVEL",
            back_water_level=1.9,
            out_flow=33.0,
        )

        self.assertIsInstance(result, PredictedResult)
        self.assertEqual(result.object_id, 102)
        self.assertEqual(result.object_type, "Canal")
        self.assertEqual(result.front_water_level, 2.1)
        self.assertEqual(result.final_target_value, 2.3)
        self.assertEqual(result.final_target_value_type, "WATER_LEVEL")
        self.assertEqual(result.back_water_level, 1.9)
        self.assertEqual(result.out_flow, 33.0)


if __name__ == "__main__":
    unittest.main()
