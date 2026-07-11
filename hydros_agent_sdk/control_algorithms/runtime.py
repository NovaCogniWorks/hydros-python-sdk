"""控制算法的最小注册与调用 runtime。"""

from __future__ import annotations

from .api import ControlAlgorithm
from .models import (
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
)


class ControlAlgorithmRuntime:
    """按 ``algorithm_type`` 注册、解析和调用控制算法。"""

    def __init__(self) -> None:
        self._algorithms: dict[str, ControlAlgorithm] = {}

    def register(self, algorithm: ControlAlgorithm) -> None:
        """注册一个算法；重复类型会立即失败，避免部署时静默覆盖。"""
        algorithm_type = algorithm.algorithm_type.strip()
        if not algorithm_type:
            raise ValueError("control algorithm_type is required")
        if algorithm_type in self._algorithms:
            raise ValueError(f"duplicate control algorithm_type: {algorithm_type}")
        self._algorithms[algorithm_type] = algorithm

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        """调用匹配算法，并把可预期运行时错误收敛为标准失败输出。"""
        algorithm = self._algorithms.get(input_data.algorithm_type)
        if algorithm is None:
            return self._failed_output(
                input_data,
                error_code="UNSUPPORTED_ALGORITHM",
                error_message=f"unsupported algorithm_type: {input_data.algorithm_type}",
            )

        try:
            output = algorithm.solve(input_data)
        except Exception as exc:
            return self._failed_output(
                input_data,
                error_code="ALGORITHM_EXECUTION_FAILED",
                error_message=str(exc),
            )

        if output.request_id != input_data.context.request_id:
            return self._failed_output(
                input_data,
                error_code="INVALID_ALGORITHM_OUTPUT",
                error_message="algorithm output request_id does not match input context",
            )
        return output

    @staticmethod
    def _failed_output(
        input_data: ControlAlgorithmInput,
        *,
        error_code: str,
        error_message: str,
    ) -> ControlAlgorithmOutput:
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )
