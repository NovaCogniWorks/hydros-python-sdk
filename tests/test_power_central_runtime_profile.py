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
                "allocation": {
                    "inter_station": {
                        "parameters": {
                            "stage_mpc_horizon_steps": 12,
                            "stage_pid_enable": False,
                        },
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
                    }
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
            }
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
        self.assertEqual(1, evidence["station_constraint_count"])
        self.assertEqual(1, evidence["reservoir_release_count"])


    def test_rejects_edge_and_task_runtime_fields(self):
        build = _load_profile_builder()

        with self.assertRaisesRegex(ValueError, "roll_steps"):
            build(
                {
                    "allocation": {
                        "inter_station": {"parameters": {"roll_steps": 10}}
                    }
                }
            )

        with self.assertRaisesRegex(ValueError, "intra_station"):
            build({"allocation": {"intra_station": {}}})
