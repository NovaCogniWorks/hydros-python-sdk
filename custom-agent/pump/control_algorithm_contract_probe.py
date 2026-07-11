"""仅用于 edge 与 custom-agent 联调的无计算控制算法探针。"""

from __future__ import annotations

from hydros_agent_sdk import (
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
)


class ControlAlgorithmContractProbe:
    """返回 ``HOLD`` 的确定性探针，不执行实际控制算法。"""

    algorithm_type = "control_contract_probe"
    algorithm_version = "1.0.0"

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        """确认标准输入可被接收，但不生成任何候选执行器目标。"""
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.HOLD,
            reason="CONTRACT_PROBE_ONLY",
            evidence={
                "mode": "dry_run",
                "algorithm_type": self.algorithm_type,
                "algorithm_version": self.algorithm_version,
            },
        )
