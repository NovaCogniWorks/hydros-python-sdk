from __future__ import annotations

from .models import ControlObjectResult, PredictedResult


class MpcResultFactory:
    """Factory for MPC optimizer result models."""

    @staticmethod
    def build_control_object_result(
        object_id: int,
        target_value: float,
        object_type: str,
        node_id: int | None = None,
        node_name: str | None = None,
        object_name: str | None = None,
        target_value_type: str | None = None,
    ) -> ControlObjectResult:
        return ControlObjectResult(
            object_type=object_type,
            node_id=node_id,
            node_name=node_name,
            object_id=object_id,
            object_name=object_name,
            target_value=target_value,
            target_value_type=target_value_type,
        )

    @staticmethod
    def build_predicted_result(
        object_id: int,
        object_type: str,
        front_water_level: float | None,
        final_target_water_level: float | None,
        back_water_level: float | None,
        out_flow: float | None,
        diversion_flow: float | None = None,
        efficiency: float | None = None,
        object_name: str | None = None,
        command_type: str | None = None,
    ) -> PredictedResult:
        return PredictedResult(
            command_type=command_type,
            object_id=object_id,
            object_type=object_type,
            object_name=object_name,
            front_water_level=front_water_level,
            final_target_water_level=final_target_water_level,
            back_water_level=back_water_level,
            out_flow=out_flow,
            diversion_flow=diversion_flow,
            efficiency=efficiency,
        )
