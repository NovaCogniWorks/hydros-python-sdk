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
from hydrosim.config import FLOW_CONFIGS
from hydrosim.runtime import (
    HydroReservoir,
    HydroResStairs,
    _apply_yaml_basic_parameters,
    _upstream_inflow_series,
)


class TestPowerHydroSimInflowPlanning(unittest.TestCase):
    def test_operating_stage_limits_do_not_rewrite_physical_capacity_curve(self):
        narrow_constraints = {
            "control_targets": [{
                "node_id": 20100,
                "min_water_level": 830.0,
                "max_water_level": 845.0,
            }]
        }
        wide_constraints = {
            "control_targets": [{
                "node_id": 20100,
                "min_water_level": 800.0,
                "max_water_level": 852.0,
            }]
        }

        narrow_configs, narrow_targets = _apply_yaml_basic_parameters(
            FLOW_CONFIGS,
            narrow_constraints,
            {},
            {},
        )
        wide_configs, _ = _apply_yaml_basic_parameters(
            FLOW_CONFIGS,
            wide_constraints,
            {},
            {},
        )
        narrow = HydroReservoir(1, "narrow", narrow_configs[0])
        wide = HydroReservoir(1, "wide", wide_configs[0])

        self.assertAlmostEqual(narrow.stage_to_capacity(840.0), wide.stage_to_capacity(840.0))
        self.assertEqual(FLOW_CONFIGS[0]["min_stage"], narrow.min_stage)
        self.assertEqual(FLOW_CONFIGS[0]["max_stage"], narrow.max_stage)
        self.assertEqual(830.0, narrow.operating_min_stage)
        self.assertEqual(845.0, narrow.operating_max_stage)
        self.assertGreaterEqual(narrow_targets[20100], narrow.operating_min_stage)
        self.assertLessEqual(narrow_targets[20100], narrow.operating_max_stage)

    def test_internal_stage_hint_uses_operating_target_and_boundaries(self):
        reservoir = HydroReservoir(1, "reservoir", {
            **FLOW_CONFIGS[0],
            "operating_min_stage": 830.0,
            "operating_max_stage": 845.0,
        })
        reservoir.current_stage = 829.0
        reservoir.target_stage = 840.0
        stairs = HydroResStairs.__new__(HydroResStairs)
        stairs.Capacity_Stairs = [reservoir]
        stairs.stage_zone_bands = [{"green": 1.0, "yellow": 3.0}]

        hint = stairs.stage_state(0)

        self.assertEqual(840.0, hint["target_stage"])
        self.assertEqual(830.0, hint["operating_min_stage"])
        self.assertEqual(845.0, hint["operating_max_stage"])
        self.assertEqual(-11.0, hint["delta"])
        self.assertEqual("red", hint["zone"])

    def test_weather_forecast_unified_canal_overrides_station_inflow(self):
        base_event = {
            "object_time_series": [
                {
                    "object_id": 20100,
                    "object_type": "Station",
                    "metrics_code": "water_flow",
                    "time_series": [
                        {"step": 0, "value": 1200.0},
                        {"step": 1, "value": 1210.0},
                    ],
                }
            ]
        }
        weather_event = {
            "object_time_series": [
                {
                    "object_id": 20000,
                    "object_type": "UnifiedCanal",
                    "metrics_code": "water_flow",
                    "time_series": [
                        {"step": 0, "value": 2534.0},
                        {"step": 1, "value": 2451.0},
                    ],
                },
            ]
        }
        merged_event = HydroSimulationApi()._merge_event_with_updates(base_event, weather_event)

        inflow = _upstream_inflow_series(merged_event, steps=[0, 1], initial_states={})

        self.assertEqual(inflow.tolist(), [2534.0, 2451.0])
        self.assertFalse(
            any(item.get("object_type") == "UnifiedCanal" for item in merged_event["object_time_series"])
        )

    def test_current_station_measurement_overrides_weather_value_for_current_step(self):
        api = HydroSimulationApi()
        base_event = {
            "object_time_series": [
                {
                    "object_id": 20100,
                    "object_type": "Station",
                    "metrics_code": "water_flow",
                    "time_series": [{"step": 0, "value": 1200.0}, {"step": 1, "value": 1210.0}],
                }
            ]
        }
        weather_event = {
            "object_time_series": [
                {
                    "object_id": 20000,
                    "object_type": "UnifiedCanal",
                    "metrics_code": "water_flow",
                    "time_series": [{"step": 0, "value": 2534.0}, {"step": 1, "value": 2451.0}],
                }
            ]
        }
        merged_event = api._merge_event_with_updates(base_event, weather_event)
        merged_event = api._overlay_current_step_metrics(
            merged_event,
            current_step=0,
            current_step_metrics=[
                {
                    "object_id": 20100,
                    "object_type": "Station",
                    "metrics_code": "water_flow",
                    "value": 1300.0,
                }
            ],
        )

        inflow = _upstream_inflow_series(merged_event, steps=[0, 1], initial_states={})

        self.assertEqual(inflow.tolist(), [1300.0, 2451.0])

    def test_station_inflow_remains_supported_without_weather_forecast(self):
        event = {
            "object_time_series": [
                {
                    "object_id": 20100,
                    "object_type": "Station",
                    "metrics_code": "water_flow",
                    "time_series": [
                        {"step": 0, "value": 1200.0},
                        {"step": 1, "value": 1210.0},
                    ],
                }
            ]
        }

        inflow = _upstream_inflow_series(event, steps=[0, 1], initial_states={})

        self.assertEqual(inflow.tolist(), [1200.0, 1210.0])

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
