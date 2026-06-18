import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MPC_DIR = REPO_ROOT / "custom-agent" / "power" / "mpc"
if str(MPC_DIR) not in sys.path:
    sys.path.insert(0, str(MPC_DIR))

import hydrosim_demo
from hydrosim_api import (
    CurrentStepPowerPlanningValue,
    HydroSimulationApi,
    HydroSimulationSession,
    HydroSimulationService,
    describe_simulation_capabilities,
    run_random_simulation,
)
from hydrosim.types import HydroRandomSimulationRequest


class HydroSimDemoTest(unittest.TestCase):
    def _write_configured_case_files(self, root_dir: str) -> dict:
        base_event = {
            "valid": True,
            "object_time_series": [
                {
                    "object_ids": [20100],
                    "object_type": "Station",
                    "object_name": "瀑布沟",
                    "metrics_code": "water_flow",
                    "time_series": [{"step": 0, "value": 2200.0}, {"step": 1, "value": 2250.0}],
                },
                {
                    "object_ids": [20100],
                    "object_type": "Station",
                    "object_name": "瀑布沟",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 1000.0}, {"step": 1, "value": 1100.0}],
                },
                {
                    "object_ids": [20300],
                    "object_type": "Station",
                    "object_name": "深溪沟",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 200.0}, {"step": 1, "value": 220.0}],
                },
                {
                    "object_ids": [20500],
                    "object_type": "Station",
                    "object_name": "枕头坝I期",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 250.0}, {"step": 1, "value": 260.0}],
                },
                {
                    "object_ids": [20700],
                    "object_type": "Station",
                    "object_name": "沙坪II期",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 120.0}, {"step": 1, "value": 130.0}],
                },
            ],
        }
        power_plan_event = {
            "object_time_series": [
                {
                    "object_ids": [20100],
                    "object_type": "Station",
                    "object_name": "瀑布沟",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 1300.0}, {"step": 1, "value": 1400.0}],
                },
                {
                    "object_ids": [20300],
                    "object_type": "Station",
                    "object_name": "深溪沟",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 180.0}, {"step": 1, "value": 190.0}],
                },
                {
                    "object_ids": [20500],
                    "object_type": "Station",
                    "object_name": "枕头坝I期",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 210.0}, {"step": 1, "value": 220.0}],
                },
                {
                    "object_ids": [20700],
                    "object_type": "Station",
                    "object_name": "沙坪II期",
                    "metrics_code": "power",
                    "time_series": [{"step": 0, "value": 90.0}, {"step": 1, "value": 100.0}],
                },
            ]
        }
        mpc_config = {"name": "test"}
        initial_states = {"initial_states": {}}
        constraints = {"control_targets": [], "control_domains": []}

        files = {
            "time_series_file": os.path.join(root_dir, "time_series_base.json"),
            "power_planning_file": os.path.join(root_dir, "time_series_power_planning.json"),
            "mpc_config_file": os.path.join(root_dir, "mpc_config.yaml"),
            "initial_states_file": os.path.join(root_dir, "initial_states.yaml"),
            "constraints_file": os.path.join(root_dir, "constrains_targets.yaml"),
        }
        with open(files["time_series_file"], "w", encoding="utf-8") as handle:
            json.dump(base_event, handle, ensure_ascii=False, indent=2)
        with open(files["power_planning_file"], "w", encoding="utf-8") as handle:
            json.dump(power_plan_event, handle, ensure_ascii=False, indent=2)
        with open(files["mpc_config_file"], "w", encoding="utf-8") as handle:
            yaml.safe_dump(mpc_config, handle, allow_unicode=True, sort_keys=False)
        with open(files["initial_states_file"], "w", encoding="utf-8") as handle:
            yaml.safe_dump(initial_states, handle, allow_unicode=True, sort_keys=False)
        with open(files["constraints_file"], "w", encoding="utf-8") as handle:
            yaml.safe_dump(constraints, handle, allow_unicode=True, sort_keys=False)
        return files

    def test_demo_describes_capabilities(self):
        demo = hydrosim_demo.HydroSimulationDemo()
        capabilities = describe_simulation_capabilities()

        summary = demo.describe_capabilities()

        self.assertEqual(summary, capabilities)
        self.assertIn("random_signal_simulation", summary["modes"])
        self.assertIn("configured_simulation", summary["modes"])
        self.assertIn("run_summary_json", summary["outputs"])

    def test_service_random_smoke_run_exports_files_and_json(self):
        service = HydroSimulationService()
        request = HydroRandomSimulationRequest(
            sim_steps=2,
            warm_steps=2,
            output_dir=tempfile.mkdtemp(prefix="hydrosim_demo_"),
            make_plots=False,
            progress_interval=0,
        )

        with contextlib.redirect_stdout(io.StringIO()):
            artifacts = service.run_random(request, output_mode="mixed")

        self.assertIn("files", artifacts)
        self.assertIn("json", artifacts)
        self.assertTrue(os.path.isdir(artifacts["files"]["output_dir"]))
        self.assertTrue(os.path.isfile(artifacts["files"]["formal_results_csv"]))
        self.assertTrue(os.path.isfile(artifacts["files"]["dispatch_min_p_json"]))
        self.assertTrue(os.path.isfile(artifacts["files"]["simulation_report_md"]))
        self.assertTrue(os.path.isfile(artifacts["files"]["run_summary_json"]))
        self.assertIsInstance(artifacts["json"]["run_summary"], dict)
        self.assertIsInstance(artifacts["json"]["dispatch_min_p"], list)
        self.assertIn("unit_outputs", artifacts["json"])
        self.assertTrue(artifacts["json"]["unit_outputs"]["stations"])
        first_unit = artifacts["json"]["unit_outputs"]["stations"][0]["units"][0]
        self.assertIn("current_power", first_unit)
        self.assertTrue(first_unit["current_power"])

    def test_service_supports_file_json_and_mixed_modes(self):
        service = HydroSimulationService()
        request = HydroRandomSimulationRequest(
            sim_steps=2,
            warm_steps=2,
            output_dir=tempfile.mkdtemp(prefix="hydrosim_demo_modes_"),
            make_plots=False,
            progress_interval=0,
        )

        with contextlib.redirect_stdout(io.StringIO()):
            file_result = service.run_random(request, output_mode="file")
            json_result = service.run_random(request, output_mode="json")
            mixed_result = service.run_random(request, output_mode="mixed")

        self.assertIn("formal_results_csv", file_result)
        self.assertNotIn("run_summary", file_result)
        self.assertIn("run_summary", json_result)
        self.assertNotIn("formal_results_csv", json_result)
        self.assertIn("files", mixed_result)
        self.assertIn("json", mixed_result)

    def test_json_mode_does_not_write_to_requested_output_dir(self):
        service = HydroSimulationService()
        output_dir = tempfile.mkdtemp(prefix="hydrosim_json_no_files_")
        self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))
        request = HydroRandomSimulationRequest(
            sim_steps=2,
            warm_steps=2,
            output_dir=output_dir,
            make_plots=False,
            progress_interval=0,
        )

        with contextlib.redirect_stdout(io.StringIO()):
            json_result = service.run_random(request, output_mode="json")

        self.assertEqual(sorted(os.listdir(output_dir)), [])
        self.assertIn("run_summary", json_result)
        self.assertIn("dispatch_min_p", json_result)
        self.assertIn("unit_outputs", json_result)
        self.assertNotIn("outputs", json_result["run_summary"])
        self.assertNotIn("output_dir", json_result["run_summary"])

    def test_smoke_demo_json_mode_returns_artifacts_only(self):
        demo = hydrosim_demo.HydroSimulationDemo()

        with contextlib.redirect_stdout(io.StringIO()):
            result = demo.run_smoke_demo(output_mode="json")

        self.assertIn("run_summary", result)
        self.assertIn("dispatch_min_p", result)
        self.assertNotIn("capabilities", result)
        self.assertNotIn("artifacts", result)

    def test_smoke_demo_passes_make_plots_flag(self):
        demo = hydrosim_demo.HydroSimulationDemo()

        with mock.patch.object(demo.api, "run_random", return_value={"ok": True}) as run_random:
            demo.run_smoke_demo(output_mode="file", make_plots=True)

        self.assertTrue(run_random.call_args.kwargs["make_plots"])

    def test_api_exposes_stable_random_entry(self):
        request = HydroRandomSimulationRequest(
            sim_steps=2,
            warm_steps=2,
            make_plots=False,
            progress_interval=0,
        )

        with contextlib.redirect_stdout(io.StringIO()):
            result = run_random_simulation(request=request, output_mode="json")

        self.assertIn("run_summary", result)
        self.assertIn("unit_outputs", result)

    def test_api_facade_describes_capabilities(self):
        api = HydroSimulationApi()

        summary = api.describe_capabilities()

        self.assertEqual(summary, describe_simulation_capabilities())

    def test_api_supports_initialize_plan_step_and_cancel(self):
        root_dir = tempfile.mkdtemp(prefix="hydrosim_api_case_")
        self.addCleanup(lambda: shutil.rmtree(root_dir, ignore_errors=True))
        files = self._write_configured_case_files(root_dir)
        api = HydroSimulationApi()

        init_result = api.initialize(
            time_series_file=files["time_series_file"],
            mpc_config_file=files["mpc_config_file"],
            initial_states_file=files["initial_states_file"],
            constraints_file=files["constraints_file"],
        )
        self.assertIn("session", init_result)
        self.assertEqual(init_result["time_axis_length"], 2)

        planning_result = api.get_station_power_planning_series(files["power_planning_file"])
        self.assertIn("station_power_series", planning_result)
        self.assertEqual(len(planning_result["station_power_series"]), 4)
        self.assertEqual(planning_result["station_power_series"][0]["time_series"][0]["step"], 0)

        first_step = api.execute_step(
            current_step_power_planning_values=[
                CurrentStepPowerPlanningValue(object_id=101, object_type="Station", metrics_code="power", value=88.0),
                CurrentStepPowerPlanningValue(object_id=102, object_type="Station", metrics_code="power", value=99.0),
                CurrentStepPowerPlanningValue(object_id=201, object_type="Station", metrics_code="power", value=77.0),
                CurrentStepPowerPlanningValue(object_id=202, object_type="Station", metrics_code="power", value=66.0),
            ]
        )
        self.assertEqual(first_step["current_step_index"], 0)
        self.assertEqual(len(first_step["station_step_outputs"]), 4)
        self.assertEqual(len(first_step["current_step_power_planning_values"]), 4)
        self.assertEqual(first_step["current_step_power_planning_values"][0]["value"], 88.0)
        self.assertEqual(first_step["current_step_power_planning_values"][0]["object_id"], 101)
        self.assertEqual(first_step["station_step_outputs"][0]["power"], 88.0)

        second_step = api.execute_step()
        self.assertEqual(second_step["current_step_index"], 1)
        self.assertFalse(second_step["has_next_step"])

        cancel_result = api.cancel()
        self.assertTrue(cancel_result["session"]["cancelled"])

    def test_api_supports_inject_operating_conditions(self):
        root_dir = tempfile.mkdtemp(prefix="hydrosim_api_inject_")
        self.addCleanup(lambda: shutil.rmtree(root_dir, ignore_errors=True))
        files = self._write_configured_case_files(root_dir)
        api = HydroSimulationApi()
        api.initialize(
            time_series_file=files["time_series_file"],
            mpc_config_file=files["mpc_config_file"],
            initial_states_file=files["initial_states_file"],
            constraints_file=files["constraints_file"],
        )
        api.get_station_power_planning_series(files["power_planning_file"])

        injected = api.inject_operating_conditions(initial_states_file=files["initial_states_file"])

        self.assertEqual(injected["session"]["current_step_index"], 0)
        self.assertIsNone(injected["session"]["latest_power_planning_file"])


if __name__ == "__main__":
    unittest.main()
