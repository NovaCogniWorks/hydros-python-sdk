import json
import unittest
from types import SimpleNamespace

from hydros_agent_sdk.mpc.models import (
    DeviceResult,
    HorizonStep,
    PredictedResult,
    ValueItem,
)
from hydros_agent_sdk.mpc.mpc_prediction_result_reporter import (
    MpcPredictionResultReporter,
)
from hydros_agent_sdk.protocol.models import SimulationContext


class MpcPredictionResultReporterTest(unittest.TestCase):
    def test_projects_structured_station_and_device_predictions(self):
        state = SimpleNamespace(
            context=SimulationContext(biz_scene_instance_id="scene-structured-report"),
            current_step=4,
            total_steps=12,
            rolling_interval_steps=3,
        )
        horizon = HorizonStep(
            horizon_step=1,
            predicted_result_list=[
                PredictedResult(
                    object_type="GateStation",
                    object_id=101,
                    target_value=ValueItem(
                        value_type="WATER_LEVEL",
                        value=3.5,
                    ),
                    predicted_value_list=[
                        ValueItem(value_type="front_water_level", value=3.4),
                        ValueItem(value_type="back_water_level", value=3.1),
                        ValueItem(value_type="out_flow", value=18.5),
                    ],
                    device_result_list=[
                        DeviceResult(
                            object_type="Gate",
                            object_id=501,
                            value_list=[
                                ValueItem(value_type="gate_opening", value=0.45),
                                ValueItem(value_type="enabled", value=True),
                            ],
                        )
                    ],
                )
            ],
        )

        result = MpcPredictionResultReporter.build_prediction_result(
            mpc_task_state=state,
            horizon_step=[horizon],
            plan_type="OPTIMAL",
        )

        self.assertEqual(len(result.details), 2)
        station_detail, device_detail = result.details
        self.assertEqual(station_detail.object_id, 101)
        self.assertEqual(station_detail.target_value, 3.5)
        self.assertEqual(station_detail.front_water_level, 3.4)
        self.assertEqual(station_detail.back_water_level, 3.1)
        self.assertEqual(station_detail.out_flow, 18.5)
        self.assertEqual(device_detail.node_id, 101)
        self.assertEqual(device_detail.object_id, 501)
        self.assertEqual(device_detail.command_type, "gate_opening")
        self.assertEqual(device_detail.value, 0.45)
        self.assertEqual(json.loads(device_detail.attributes)["value_role"], "forecast")


if __name__ == "__main__":
    unittest.main()
