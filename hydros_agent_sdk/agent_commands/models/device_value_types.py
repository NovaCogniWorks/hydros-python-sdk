"""
设备目标值类型枚举。
"""

from __future__ import annotations

from enum import Enum


class DeviceValueTypeEnum(Enum):
    """贴近 Java 的设备值类型定义。"""

    WATER_LEVEL = ("water_level", "水位", float)
    WATER_FLOW = ("water_flow", "水流", float)
    GATE_OPENING = ("gate_opening", "闸门开度", float)
    BLADE_ANGLE = ("blade_angle", "叶片角度", float)
    OUTPUT_POWER = ("output_power", "输出功率", float)
    UNIT_STATUS = ("unit_status", "机组启停状态", int)
    UNIT_OPENING = ("unit_opening", "机组开度", float)

    def __init__(self, code: str, label: str, value_type: type):
        self.code = code
        self.label = label
        self.value_type = value_type

    @classmethod
    def from_code(cls, code: str) -> "DeviceValueTypeEnum":
        for item in cls:
            if item.code == code:
                return item
        raise ValueError(f"不支持的 DeviceValueTypeEnum code: {code}")
