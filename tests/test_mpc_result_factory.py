import unittest

from hydros_agent_sdk.mpc.models import ControlDeviceResult, PredictedResult
from hydros_agent_sdk.mpc.mpc_result_factory import MpcResultFactory


class MpcResultFactoryTest(unittest.TestCase):
    def test_build_control_device_result(self):
        result = MpcResultFactory.build_control_device_result(
            device_id=501,
            value=0.45,
            device_type="Gate",
        )

        self.assertIsInstance(result, ControlDeviceResult)
        self.assertEqual(result.device_id, 501)
        self.assertEqual(result.value, 0.45)
        self.assertEqual(result.device_type, "Gate")

    def test_build_predicted_result(self):
        result = MpcResultFactory.build_predicted_result(
            object_id=102,
            object_type="Canal",
            front_water_level=2.1,
            target_water_level=2.3,
            back_water_level=1.9,
            total_flow=33.0,
        )

        self.assertIsInstance(result, PredictedResult)
        self.assertEqual(result.object_id, 102)
        self.assertEqual(result.object_type, "Canal")
        self.assertEqual(result.front_water_level, 2.1)
        self.assertEqual(result.target_water_level, 2.3)
        self.assertEqual(result.back_water_level, 1.9)
        self.assertEqual(result.total_flow, 33.0)


if __name__ == "__main__":
    unittest.main()
