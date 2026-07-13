"""泵站流量 DMPC 的确定性领域错误。"""

from __future__ import annotations


class PumpFlowDmpcError(ValueError):
    """携带稳定错误码的预期算法失败。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
