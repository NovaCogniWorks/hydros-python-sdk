"""V45 站间、站内分配算法的最小回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MPC_DIR = REPO_ROOT / "custom-agent" / "power" / "mpc"
if str(MPC_DIR) not in sys.path:
    sys.path.insert(0, str(MPC_DIR))

from hydrosim.config import POWER_CONFIGS, UNIT_CONFIGS
from hydrosim.runtime import HydroStair, HydroStation


class V45AllocationTest(unittest.TestCase):
    def test_intra_station_allocation_closes_station_power_target(self) -> None:
        station_config = POWER_CONFIGS[0]
        station = HydroStation(
            station_id=station_config["ID"],
            name=station_config["Name"],
            design_head=station_config["design_head"],
            design_power=station_config["design_power"],
            min_power=station_config["min_power"],
            max_power=station_config["max_power"],
            unit_cfgs=UNIT_CONFIGS[0],
            unit_dispatch_min_p=station_config["unit_min_step_p"],
            station_target_ramp_rate=station_config["station_target_ramp_rate"],
        )

        target = 1_800.0
        station.step_execute(target)

        self.assertAlmostEqual(station.current_p, target, places=6)
        self.assertAlmostEqual(sum(unit.current_power for unit in station.multi_station), target, places=6)
        self.assertTrue(all(0.0 <= unit.current_power <= unit.max_power for unit in station.multi_station))

    def test_inter_station_allocation_closes_total_power_target(self) -> None:
        stair = HydroStair(
            stair_id=1,
            name="allocation-test",
            current_power=sum(config["design_power"] for config in POWER_CONFIGS),
            station_cfgs=POWER_CONFIGS,
            unit_cfgs_by_station=UNIT_CONFIGS,
        )

        target = 2_400.0
        stair.step_execute(target)

        self.assertAlmostEqual(stair.total_p_current, target, places=6)
        self.assertAlmostEqual(sum(station.current_p for station in stair.multi_stair), target, places=6)
        self.assertTrue(
            all(station.current_p <= station.max_power + 1e-6 for station in stair.multi_stair)
        )


if __name__ == "__main__":
    unittest.main()
