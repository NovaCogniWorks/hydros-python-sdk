"""
设备目标值类型枚举。
"""

from __future__ import annotations

from enum import Enum


class DeviceValueTypeEnum(Enum):
    """贴近 Java 的设备值类型定义。"""

    WATER_LEVEL = ("water_level", "水位", float)
    GATE_OPENING = ("gate_opening", "闸门开度", float)
    BLADE_ANGLE = ("blade_angle", "叶片角度", float)
    OUTPUT_POWER = ("output_power", "输出功率", float)

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
