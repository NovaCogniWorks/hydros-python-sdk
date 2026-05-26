"""Cache for field metrics used by MPC optimization."""

from typing import Any, Dict, List, Optional

from hydros_agent_sdk.mpc.models import SensorData


class MetricsDataCache:
    """Store latest field metrics and a bounded per-step history."""

    def __init__(self, max_steps: int):
        self.max_steps = max_steps
        self.latest_metrics: Dict[str, Dict[str, Any]] = {}
        self.metrics_by_step: Dict[int, Dict[str, Dict[str, Any]]] = {}

    def update(self, payload: Dict[str, Any]) -> Optional[str]:
        object_id = payload.get("object_id")
        metrics_code = payload.get("metrics_code")
        value = payload.get("value")
        step_index = payload.get("step_index")
        object_type = payload.get("object_type")
        position_code = payload.get("position_code")
        if position_code != "none":
            return None
        if object_id is None or not metrics_code:
            return None

        cache_key = f"{object_id}_{metrics_code}"
        metrics_data = {
            "object_id": object_id,
            "object_type": object_type,
            "metrics_code": metrics_code,
            "position_code": position_code,
            "value": value,
            "step_index": step_index,
        }
        self.latest_metrics[cache_key] = metrics_data

        if step_index is not None:
            step = int(step_index)
            self.metrics_by_step.setdefault(step, {})
            self.metrics_by_step[step][cache_key] = {
                **metrics_data,
                "step_index": step,
            }
            self.trim()

        return cache_key

    def get_value(self, object_id: int, metrics_code: str) -> Optional[float]:
        metrics_data = self.latest_metrics.get(f"{object_id}_{metrics_code}")
        if metrics_data:
            return metrics_data.get("value")
        return None

    def by_step(self, step_index: int) -> Dict[str, Dict[str, Any]]:
        return dict(self.metrics_by_step.get(int(step_index), {}))

    def history(self) -> Dict[int, Dict[str, Dict[str, Any]]]:
        return {step: dict(metrics) for step, metrics in self.metrics_by_step.items()}

    def to_sensor_data(self) -> List[SensorData]:
        return [
            SensorData.model_validate(value)
            for value in self.latest_metrics.values()
        ]

    def trim(self) -> None:
        if self.max_steps <= 0:
            self.metrics_by_step.clear()
            return

        step_indexes = sorted(self.metrics_by_step.keys())
        excess_count = len(step_indexes) - self.max_steps
        if excess_count <= 0:
            return

        for step_index in step_indexes[:excess_count]:
            self.metrics_by_step.pop(step_index, None)
