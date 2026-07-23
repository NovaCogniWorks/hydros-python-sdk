"""面向自定义控制算法实现者的最小接口。"""

from __future__ import annotations

from typing import Protocol

from .models import ControlAlgorithmInput, ControlAlgorithmOutput


class ControlAlgorithm(Protocol):
    """可注册到 SDK runtime 的控制算法。"""

    @property
    def algorithm_type(self) -> str:
        """返回算法类型，例如 ``odd_dmpc``。"""

    @property
    def algorithm_version(self) -> str:
        """返回算法实现版本。"""

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        """根据标准输入计算一次控制决策。"""
