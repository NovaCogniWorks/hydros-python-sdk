from __future__ import annotations

from typing import Dict, List

__version__ = "16.0"

CAPA_LOC = [30, 90, 150, 230, 300]

FLOW_CONFIGS = [
    {
        "ID": 1,
        "Name": "瀑布沟",
        "design_stage": 850.0,
        "design_capacity": 433400,
        "min_stage": 790.0,
        "min_capacity": 45200,
        "max_stage": 853.78,
        "max_capacity": 533700,
        "Kp": 5000.0,
        "Ki": 50.0,
        "Kd": 2000.0,
        "use_integral": False,
        "spill_ff_enable": True,
        "spill_ff_gain": 1.00,
        "spill_ff_deadband": 20.0,
        "spill_ff_gain_yellow_high": 1.03,
        "spill_ff_gain_red_high": 1.08,
        "spill_ff_high_deadband": 0.0,
        "spill_ff_high_green_band": 1.0,
        "spill_ff_high_yellow_band": 3.0,
        "spill_ramp_rate": 300.0,
        "distance": 17000,
    },
    {
        "ID": 2,
        "Name": "深溪沟",
        "design_stage": 660.0,
        "design_capacity": 3200,
        "min_stage": 655.0,
        "min_capacity": 2350,
        "max_stage": 665.0,
        "max_capacity": 4050,
        "Kp": 1500.0,
        "Ki": 30.0,
        "Kd": 600.0,
        "use_integral": False,
        "spill_ff_enable": True,
        "spill_ff_gain": 0.95,
        "spill_ff_deadband": 20.0,
        "spill_ff_gain_yellow_high": 1.08,
        "spill_ff_gain_red_high": 1.18,
        "spill_ff_high_deadband": 0.0,
        "spill_ff_high_green_band": 0.5,
        "spill_ff_high_yellow_band": 1.0,
        "spill_ramp_rate": 250.0,
        "distance": 17000,
    },
    {
        "ID": 3,
        "Name": "枕头坝I期",
        "design_stage": 624.0,
        "design_capacity": 4690,
        "min_stage": 618.0,
        "min_capacity": 3300,
        "max_stage": 630.0,
        "max_capacity": 6100,
        "Kp": 1500.0,
        "Ki": 30.0,
        "Kd": 600.0,
        "use_integral": False,
        "spill_ff_enable": True,
        "spill_ff_gain": 0.95,
        "spill_ff_deadband": 20.0,
        "spill_ff_gain_yellow_high": 1.08,
        "spill_ff_gain_red_high": 1.18,
        "spill_ff_high_deadband": 0.0,
        "spill_ff_high_green_band": 0.5,
        "spill_ff_high_yellow_band": 1.0,
        "spill_ramp_rate": 250.0,
        "distance": 21600,
    },
    {
        "ID": 4,
        "Name": "沙坪II期",
        "design_stage": 554.0,
        "design_capacity": 2084,
        "min_stage": 550.0,
        "min_capacity": 1500,
        "max_stage": 558.0,
        "max_capacity": 2670,
        "Kp": 900.0,
        "Ki": 0.0,
        "Kd": 360.0,
        "use_integral": False,
        "spill_ff_enable": True,
        "spill_ff_gain": 0.95,
        "spill_ff_deadband": 12.0,
        "spill_ff_gain_yellow_high": 1.05,
        "spill_ff_gain_red_high": 1.12,
        "spill_ff_high_deadband": 0.0,
        "spill_ff_high_green_band": 0.5,
        "spill_ff_high_yellow_band": 1.0,
        "spill_ff_stage_guard_band": 0.08,
        "spill_ramp_rate": 250.0,
        "distance": 37000,
        "tail_stage": 540.0,
    },
]

FLOW_STATION_CFGS = [
    {"ID": 1, "Name": "瀑布沟", "design_head": 154.6, "min_head": 114.3, "max_head": 181.7, "tail_design_stage": 660.0},
    {"ID": 2, "Name": "深溪沟", "design_head": 30.0, "min_head": 20.1, "max_head": 40.0, "tail_design_stage": 624.0},
    {"ID": 3, "Name": "枕头坝I期", "design_head": 29.5, "min_head": 25.5, "max_head": 34.5, "tail_design_stage": 594.0},
    {"ID": 4, "Name": "沙坪II期", "design_head": 14.3, "min_head": 10.3, "max_head": 24.6, "tail_design_stage": 540.0},
]

POWER_CONFIGS = [
    {"ID": 1, "Name": "瀑布沟", "Num": 6, "design_head": 154.6, "design_power": 3600, "min_power": 200, "max_power": 3900, "stair_min_step_p": 50.0, "unit_min_step_p": 25.0, "station_target_ramp_rate": 180.0},
    {"ID": 2, "Name": "深溪沟", "Num": 4, "design_head": 30.0, "design_power": 660, "min_power": 60, "max_power": 726, "stair_min_step_p": 10.0, "unit_min_step_p": 2.0, "station_target_ramp_rate": 50.0},
    {"ID": 3, "Name": "枕头坝I期", "Num": 4, "design_head": 29.5, "design_power": 720, "min_power": 60, "max_power": 800, "stair_min_step_p": 10.0, "unit_min_step_p": 2.0, "station_target_ramp_rate": 50.0},
    {"ID": 4, "Name": "沙坪II期", "Num": 6, "design_head": 14.3, "design_power": 348, "min_power": 30, "max_power": 360, "stair_min_step_p": 10.0, "unit_min_step_p": 2.0, "station_target_ramp_rate": 30.0},
]

UNIT_CONFIGS = [
    [
        {"ID": k, "Name": f"瀑布沟{k}#机组", "State": 1, "head": 154.6, "min_head": 114.3, "design_head": 154.6, "max_head": 181.7, "min_power": 200.0, "design_power": 600.0, "max_power": 650.0, "power_ramp_rate": 80.0, "design_efficiency": 0.92, "eta_head_coeff": 0.25, "eta_power_coeff": 0.40}
        for k in range(1, 7)
    ],
    [
        {"ID": k, "Name": f"深溪沟{k}#机组", "State": 1, "head": 30.0, "min_head": 20.1, "design_head": 30.0, "max_head": 40.0, "min_power": 20.0, "design_power": 165.0, "max_power": 182.0, "power_ramp_rate": 20.0, "design_efficiency": 0.92, "eta_head_coeff": 0.15, "eta_power_coeff": 0.20}
        for k in range(1, 5)
    ],
    [
        {"ID": k, "Name": f"枕头坝I期{k}#机组", "State": 1, "head": 29.5, "min_head": 25.5, "design_head": 29.5, "max_head": 34.5, "min_power": 60.0, "design_power": 180.0, "max_power": 200.0, "power_ramp_rate": 20.0, "design_efficiency": 0.92, "eta_head_coeff": 0.15, "eta_power_coeff": 0.20}
        for k in range(1, 5)
    ],
    [
        {"ID": k, "Name": f"沙坪II期{k}#机组", "State": 1, "head": 14.3, "min_head": 10.3, "design_head": 14.3, "max_head": 24.6, "min_power": 20.0, "design_power": 58.0, "max_power": 68.0, "power_ramp_rate": 8.0, "design_efficiency": 0.90, "eta_head_coeff": 0.12, "eta_power_coeff": 0.20}
        for k in range(1, 7)
    ],
]

STATION_NODE_IDS = [20100, 20300, 20500, 20700]
STATION_CANAL_IDS = [20000, 20200, 20400, 20600]
NODE_TO_INDEX = {node_id: idx for idx, node_id in enumerate(STATION_NODE_IDS)}
CANAL_TO_NODE = dict(zip(STATION_CANAL_IDS, STATION_NODE_IDS))


def validate_hydrosim_config() -> None:
    n = len(FLOW_CONFIGS)
    if not (n == len(FLOW_STATION_CFGS) == len(POWER_CONFIGS) == len(UNIT_CONFIGS)):
        raise ValueError("FLOW/FLOW_STATION/POWER/UNIT 配置长度不一致。")
    if len(CAPA_LOC) != n + 1:
        raise ValueError("CAPA_LOC 长度应等于电站数 + 1。")


def build_station_name_map() -> Dict[int, str]:
    return {node_id: POWER_CONFIGS[i]["Name"] for i, node_id in enumerate(STATION_NODE_IDS)}


def list_station_names() -> List[str]:
    return [cfg["Name"] for cfg in POWER_CONFIGS]
