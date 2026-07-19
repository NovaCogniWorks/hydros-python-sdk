from __future__ import annotations

from typing import List, Optional

from .models import ControlObjectResult, DeviceResult, PredictedResult, ValueItem


class MpcResultFactory:
    """MPC 优化结果模型工厂。"""

    @staticmethod
    def build_control_object_result(
        object_id: int,
        object_type: str,
        target_value_list: List[ValueItem],
        object_name: Optional[str] = None,
    ) -> ControlObjectResult:
        return ControlObjectResult(
            object_type=object_type,
            object_id=object_id,
            object_name=object_name,
            target_value_list=target_value_list,
        )

    @staticmethod
    def build_predicted_result(
        object_id: int,
        object_type: str,
        predicted_value_list: List[ValueItem],
        object_name: Optional[str] = None,
        target_value: Optional[ValueItem] = None,
        device_result_list: Optional[List[DeviceResult]] = None,
    ) -> PredictedResult:
        return PredictedResult(
            object_id=object_id,
            object_type=object_type,
            object_name=object_name,
            target_value=target_value,
            predicted_value_list=predicted_value_list,
            device_result_list=device_result_list or [],
        )
