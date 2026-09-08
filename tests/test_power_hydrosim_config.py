from __future__ import annotations

import importlib
import math
import os
import sys
import unittest


def _load_config_module():
    hydrosim_dir = os.path.abspath("custom-agent/power/mpc")
    if hydrosim_dir not in sys.path:
        sys.path.insert(0, hydrosim_dir)
    return importlib.import_module("hydrosim.config")


class PowerHydrosimConfigTest(unittest.TestCase):
    def test_pubilugou_unit_limit_matches_station_limit(self) -> None:
        config = _load_config_module()
        station = config.POWER_CONFIGS[0]
        units = config.UNIT_CONFIGS[0]

        self.assertEqual(station["Num"], len(units))
        self.assertAlmostEqual(
            float(station["max_power"]),
            sum(float(unit["max_power"]) for unit in units),
        )
        self.assertTrue(all(float(unit["max_power"]) == 650.0 for unit in units))
        self.assertEqual([20104, 20105, 20106, 20107, 20108, 20109], config.UNIT_OBJECT_IDS[0])

    def test_unit_object_ids_match_every_station_unit_config(self) -> None:
        config = _load_config_module()

        config.validate_hydrosim_config()

        self.assertEqual(len(config.STATION_NODE_IDS), len(config.UNIT_OBJECT_IDS))
        for unit_configs, object_ids in zip(config.UNIT_CONFIGS, config.UNIT_OBJECT_IDS):
            self.assertEqual(len(unit_configs), len(object_ids))
            self.assertEqual(len(object_ids), len(set(object_ids)))

    def test_runtime_stage_hints_include_v47_flow_context(self) -> None:
        config = _load_config_module()
        runtime = importlib.import_module("hydrosim.runtime")
        reservoirs = runtime.HydroResStairs(
            stairs_id=1,
            name="test",
            flow_configs=config.FLOW_CONFIGS,
            flow_station_cfgs=config.FLOW_STATION_CFGS,
            capa_loc=config.CAPA_LOC,
        )
        upstream = reservoirs.Capacity_Stairs[0]
        downstream = reservoirs.Capacity_Stairs[1]
        upstream.current_inflow = 101.0
        upstream.current_outflow_power = 70.0
        upstream.current_outflow_discharge = 12.0
        upstream.current_outflow = 82.0
        downstream.current_inflow = 82.0
        downstream.current_outflow_power = 65.0

        hints = reservoirs.stage_hints()

        self.assertEqual(101.0, hints[0]["inflow_m3s"])
        self.assertEqual(70.0, hints[0]["power_outflow_m3s"])
        self.assertTrue(math.isinf(hints[0]["upstream_release_m3s"]))
        self.assertEqual(82.0, hints[1]["inflow_m3s"])
        self.assertEqual(82.0, hints[1]["upstream_release_m3s"])
        self.assertEqual(70.0, hints[1]["upstream_power_outflow_m3s"])
        self.assertEqual(12.0, hints[1]["upstream_spill_outflow_m3s"])


if __name__ == "__main__":
    unittest.main()
