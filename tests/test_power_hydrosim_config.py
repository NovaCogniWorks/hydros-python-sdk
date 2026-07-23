from __future__ import annotations

import importlib
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


if __name__ == "__main__":
    unittest.main()
