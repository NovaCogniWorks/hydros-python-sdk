import os
import sys

import pytest


def _planning_config_type():
    scheduling_dir = os.path.abspath("custom-agent/power/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)
    from power_planning_config import PowerPlanningConfig

    return PowerPlanningConfig


def test_power_planning_config_reads_outer_central_profile_only():
    config_type = _planning_config_type()

    config = config_type.from_profile(
        {
            "planning": {"rolling_step": 2, "prediction_horizon": 12},
            "allocation": {
                "inter_station": {
                    "parameters": {"stage_mpc_horizon_steps": 8}
                }
            },
        }
    )

    assert config.rolling_step == 2
    assert config.prediction_horizon == 12


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ({}, "requires planning"),
        ({"planning": {"prediction_horizon": 12}}, "rolling_step"),
        (
            {"planning": {"rolling_step": 3, "prediction_horizon": 2}},
            "greater than or equal",
        ),
        (
            {
                "planning": {
                    "rolling_step": 1,
                    "prediction_horizon": 12,
                    "stage_mpc_horizon_steps": 8,
                }
            },
            "unsupported keys",
        ),
    ],
)
def test_power_planning_config_rejects_missing_or_mixed_semantics(profile, message):
    config_type = _planning_config_type()

    with pytest.raises(ValueError, match=message):
        config_type.from_profile(profile)
