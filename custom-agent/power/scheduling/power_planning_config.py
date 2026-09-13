"""Validated task-level planning parameters for Power scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PowerPlanningConfig:
    """Outer rolling cadence and prediction horizon from the Central profile."""

    rolling_step: int
    prediction_horizon: int

    @classmethod
    def from_profile(cls, profile: Mapping[str, Any]) -> "PowerPlanningConfig":
        if not isinstance(profile, Mapping):
            raise ValueError("central Power runtime profile must be an object")
        planning = profile.get("planning")
        if not isinstance(planning, Mapping):
            raise ValueError("central Power runtime profile requires planning")

        unsupported = sorted(set(planning) - {"rolling_step", "prediction_horizon"})
        if unsupported:
            raise ValueError(
                "central Power planning contains unsupported keys: "
                + ", ".join(unsupported)
            )

        rolling_step = cls._positive_int(planning.get("rolling_step"), "planning.rolling_step")
        prediction_horizon = cls._positive_int(
            planning.get("prediction_horizon"),
            "planning.prediction_horizon",
        )
        if prediction_horizon < rolling_step:
            raise ValueError(
                "planning.prediction_horizon must be greater than or equal to planning.rolling_step"
            )
        return cls(
            rolling_step=rolling_step,
            prediction_horizon=prediction_horizon,
        )

    @staticmethod
    def _positive_int(value: Any, path: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{path} must be a positive integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{path} must be a positive integer") from None
        if parsed <= 0 or str(value).strip() not in {str(parsed), f"{parsed}.0"}:
            raise ValueError(f"{path} must be a positive integer")
        return parsed
