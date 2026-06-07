from __future__ import annotations

from .models import ControlDeviceResult, PredictedResult


class MpcResultFactory:
    """Factory for MPC optimizer result models."""

    @staticmethod
    def build_control_device_result(
        device_id: int,
        value: float,
        device_type: str,
    ) -> ControlDeviceResult:
        return ControlDeviceResult(
            device_id=device_id,
            value=value,
            device_type=device_type,
        )

    @staticmethod
    def build_predicted_result(
        object_id: int,
        object_type: str,
        front_water_level: float,
        target_water_level: float,
        back_water_level: float,
        total_flow: float,
    ) -> PredictedResult:
        return PredictedResult(
            object_id=object_id,
            object_type=object_type,
            front_water_level=front_water_level,
            target_water_level=target_water_level,
            back_water_level=back_water_level,
            total_flow=total_flow,
        )
