import os
import sys
import unittest


def _load_profile_builder():
    hydrosim_dir = os.path.abspath("custom-agent/power/mpc")
    if hydrosim_dir not in sys.path:
        sys.path.insert(0, hydrosim_dir)
    from hydrosim.central_profile import build_central_power_runtime_core

    return build_central_power_runtime_core


class PowerCentralRuntimeProfileTest(unittest.TestCase):
    def test_projects_only_central_v47_and_reservoir_parameters(self):
        build = _load_profile_builder()

        core, evidence = build(
            {
                "planning": {
                    "prediction_horizon": 12,
                    "rolling_step": 1,
                },
                "allocation": {
                    "stage_mpc_horizon_steps": 12,
                    "stage_pid_enable": False,
                    "station_constraints": [
                        {
                            "station_object_id": 20300,
                            "station_target_ramp_rate": 73.0,
                            "max_power": 740.0,
                            "flow_rebalance_max_delta_p": 11.0,
                            "slow_rebalance_max_delta_p": 4.0,
                            "slow_rebalance_max_delta_q_m3s": 5.0,
                        }
                    ],
                },
                "reservoir_release": {
                    "stations": [
                        {
                            "station_object_id": 20100,
                            "target_stage": 845.0,
                            "pid_kp": 4321.0,
                            "spill_ramp_rate": 123.0,
                        }
                    ]
                },
            },
            reservoir_step_seconds=7200,
        )

        self.assertTrue(all(item["stage_mpc_horizon_steps"] == 12 for item in core.power_configs))
        self.assertTrue(all(item["stage_pid_enable"] is False for item in core.power_configs))
        self.assertEqual(73.0, core.power_configs[1]["station_target_ramp_rate"])
        self.assertEqual(740.0, core.power_configs[1]["max_power"])
        self.assertEqual(11.0, core.power_configs[1]["flow_rebalance_max_delta_p"])
        self.assertEqual(4.0, core.power_configs[1]["slow_rebalance_max_delta_p"])
        self.assertEqual(5.0, core.power_configs[1]["slow_rebalance_max_delta_q_m3s"])
        self.assertEqual(845.0, core.flow_configs[0]["design_stage"])
        self.assertEqual(4321.0, core.flow_configs[0]["Kp"])
        self.assertEqual(123.0, core.flow_configs[0]["spill_ramp_rate"])
        self.assertTrue(all(item["time_steps"] == 7200 for item in core.flow_configs))
        self.assertEqual(1, evidence["station_constraint_count"])
        self.assertEqual(1, evidence["reservoir_release_count"])
        self.assertEqual(7200, evidence["reservoir_step_seconds"])
        self.assertEqual(
            "simulation_runtime_options.output_step_seconds",
            evidence["reservoir_step_source"],
        )


    def test_rejects_edge_and_task_runtime_fields(self):
        build = _load_profile_builder()

        with self.assertRaisesRegex(ValueError, "roll_steps"):
            build(
                {
                    "allocation": {
                        "roll_steps": 10,
                    }
                },
                reservoir_step_seconds=7200,
            )

        with self.assertRaisesRegex(ValueError, "intra_station"):
            build(
                {"allocation": {"intra_station": {}}},
                reservoir_step_seconds=7200,
            )

    def test_ignores_legacy_profile_time_steps_in_favor_of_task_output_step(self):
        build = _load_profile_builder()

        core, evidence = build(
            {
                "reservoir_release": {
                    "stations": [
                        {
                            "station_object_id": 20100,
                            "time_steps": 60,
                        }
                    ]
                }
            },
            reservoir_step_seconds=7200,
        )

        self.assertTrue(all(item["time_steps"] == 7200 for item in core.flow_configs))
        self.assertEqual(1, evidence["ignored_legacy_time_steps_count"])
        self.assertEqual(
            [
                {
                    "station_object_id": 20100,
                    "configured_time_steps": 60,
                    "effective": False,
                }
            ],
            evidence["ignored_legacy_time_steps"],
        )

    def test_reservoir_capacity_delta_uses_task_output_step_seconds(self):
        build = _load_profile_builder()
        from hydrosim.runtime import HydroReservoir

        for output_step_seconds in (3600, 7200):
            with self.subTest(output_step_seconds=output_step_seconds):
                core, _ = build(
                    {
                        "reservoir_release": {
                            "stations": [
                                {
                                    "station_object_id": 20100,
                                    "time_steps": 60,
                                }
                            ]
                        }
                    },
                    reservoir_step_seconds=output_step_seconds,
                )
                reservoir = HydroReservoir(1, "test", core.flow_configs[0])
                initial_capacity = reservoir.current_capacity

                reservoir.step(inflow=0.0, outflow_power=10.0, record=False)

                self.assertEqual(output_step_seconds, reservoir.time_steps)
                self.assertAlmostEqual(
                    initial_capacity - (10.0 * output_step_seconds / 10000.0),
                    reservoir.current_capacity,
                )
