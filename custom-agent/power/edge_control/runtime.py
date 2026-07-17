from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Protocol

from .models import (
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
)


class ControlAlgorithm(Protocol):
    algorithm_type: str
    algorithm_version: str

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        ...


@dataclass(frozen=True)
class RuntimeErrorResponse:
    error_code: str
    error_message: str


class ControlAlgorithmRuntime:
    def __init__(self) -> None:
        self._algorithms: Dict[str, ControlAlgorithm] = {}

    def register(self, algorithm: ControlAlgorithm) -> None:
        if algorithm.algorithm_type in self._algorithms:
            raise ValueError(f"Duplicate algorithm_type: {algorithm.algorithm_type}")
        self._algorithms[algorithm.algorithm_type] = algorithm

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        algorithm = self._algorithms.get(input_data.algorithm_type)
        if algorithm is None:
            return self._failed(
                input_data,
                error_code="UNSUPPORTED_ALGORITHM",
                error_message=f"Unsupported algorithm_type: {input_data.algorithm_type}",
            )
        try:
            output = algorithm.solve(input_data)
        except Exception as exc:
            return self._failed(
                input_data,
                error_code="ALGORITHM_EXECUTION_FAILED",
                error_message=str(exc),
            )
        if output.request_id != input_data.context.request_id:
            return self._failed(
                input_data,
                error_code="INVALID_ALGORITHM_OUTPUT",
                error_message="Output request_id must match input request_id.",
            )
        return output

    @staticmethod
    def _failed(
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
