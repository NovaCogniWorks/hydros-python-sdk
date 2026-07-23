"""MPC 预测明细和执行报告共享的稳定身份标识。"""

from typing import Optional


def build_mpc_detail_identity(
    optimize_step: Optional[int],
    horizon_step: Optional[int],
    node_id: Optional[int],
    object_id: Optional[int],
    target_value_type: Optional[str],
) -> str:
    def normalize(value: object) -> str:
        if value is None:
            return "none"
        return str(value).strip() or "none"

    return ":".join(
        (
            "MPC_DETAIL",
            normalize(optimize_step),
            normalize(horizon_step),
            normalize(node_id),
            normalize(object_id),
            normalize(target_value_type),
        )
    )
