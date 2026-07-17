import json
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path


POWER_MPC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../custom-agent/power/mpc")
)
if POWER_MPC_DIR not in sys.path:
    sys.path.insert(0, POWER_MPC_DIR)

from hydrosim_api import HydroSimulationApi
from hydrosim.input_resolver import HydroSimulationInputResolver


class TestPowerHydroSimInflowPlanning(unittest.TestCase):
    def test_inflow_planning_generates_station_power_and_device_outputs(self):
        api = HydroSimulationApi()
        resolver = HydroSimulationInputResolver()
        api.initialize(
            resolver.resolve_bundle(
            time_series_file="custom-agent/power/data/time_series_power_planning.json",
            mpc_config_file="custom-agent/power/data/mpc_config.yaml",
            initial_states_file="custom-agent/power/data/initial_states.yaml",
            constraints_file="custom-agent/power/data/constrains_targets.yaml",
            )
        )

        payload = {
            "object_time_series": [
                {
                    "object_id": 20100,
                    "object_type": "Station",
                    "object_name": "Station-20100",
                    "metrics_code": "water_flow",
                    "time_series": [
                        {"step": 0, "value": 334.0},
                        {"step": 1, "value": 340.0},
                        {"step": 2, "value": 320.0},
                    ],
                }
            ]
        }
        inflow_file = Path(tempfile.gettempdir()) / "hydrosim_inflow_unittest.json"
        inflow_file.write_text(json.dumps(payload), encoding="utf-8")

        planning_result = api.get_station_power_planning_series_from_inflow(
            resolver.load_event_data_from_file(str(inflow_file))
        )

        station_series = planning_result["station_power_series"]
        self.assertEqual(len(station_series), 4)
        self.assertTrue(all(item["time_series"] for item in station_series))
        self.assertGreater(sum(item["time_series"][0]["value"] for item in station_series), 0.0)

        step_result = api.execute_step(0)
        device_metrics = {
            (item["object_type"], item["metrics_code"])
            for item in step_result["device_step_outputs"]
        }
        self.assertIn(("Turbine", "output_power"), device_metrics)
        self.assertIn(("Turbine", "water_flow"), device_metrics)
        self.assertIn(("Gate", "water_flow"), device_metrics)
        self.assertIn(("Gate", "gate_opening"), device_metrics)

    def test_inflow_planning_accepts_file_path_argument(self):
        api = HydroSimulationApi()
        resolver = HydroSimulationInputResolver()
        api.initialize(
            resolver.resolve_bundle(
                time_series_file="custom-agent/power/data/time_series_power_planning.json",
                mpc_config_file="custom-agent/power/data/mpc_config.yaml",
                initial_states_file="custom-agent/power/data/initial_states.yaml",
                constraints_file="custom-agent/power/data/constrains_targets.yaml",
            )
        )

        payload = {
            "object_time_series": [
                {
                    "object_id": 20100,
                    "object_type": "Station",
                    "object_name": "Station-20100",
                    "metrics_code": "water_flow",
                    "time_series": [
                        {"step": 0, "value": 334.0},
                        {"step": 1, "value": 340.0},
                    ],
                }
            ]
        }
        inflow_file = Path(tempfile.gettempdir()) / "hydrosim_inflow_path_unittest.json"
        inflow_file.write_text(json.dumps(payload), encoding="utf-8")

        planning_result = api.get_station_power_planning_series_from_inflow(str(inflow_file))

        self.assertTrue(planning_result["station_power_series"])


if __name__ == "__main__":
    unittest.main()
