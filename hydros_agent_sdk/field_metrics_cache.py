"""现地指标缓存，供中央调度和默认 MPC 优化复用。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from hydros_agent_sdk.sensor_data import SensorData


SUPPORTED_METRICS_CODES = {
    "water_level",
    "water_flow",
    "gate_opening",
    "gate_opening_percentage",
    "water_depth",
}
POSITION_NONE = "none"
KNOWN_POSITION_CODES = {POSITION_NONE, "up_stream", "down_stream"}
METRICS_VALUE_RANGES = {
    "water_level": (0.0, 1000.0),
    "water_flow": (0.0, 100000.0),
    "gate_opening_percentage": (0.0, 100.0),
}


class FieldMetricsCache:
    """存储最新现地指标和有界的逐步历史数据。"""

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
        position_code = self._normalize_position_code(payload.get("position_code"))
        attributes = payload.get("attributes")
        if object_id is None or not metrics_code:
            return None
        metrics_code = str(metrics_code).lower()
        if not self._is_supported_metrics_code(metrics_code):
            return None
        if position_code != POSITION_NONE:
            return None
        if not self._is_value_in_range(metrics_code, value):
            return None

        cache_key = f"{object_id}_{metrics_code}"
        metrics_data = {
            "object_id": object_id,
            "object_type": object_type,
            "metrics_code": metrics_code,
            "position_code": position_code,
            "value": value,
            "step_index": step_index,
            "attributes": attributes,
        }
        self.latest_metrics[cache_key] = metrics_data

        if step_index is not None:
            try:
                step = int(step_index)
            except (TypeError, ValueError):
                raise
            self.metrics_by_step.setdefault(step, {})
            self.metrics_by_step[step][cache_key] = {
                **metrics_data,
                "step_index": step,
            }
            self.trim()

        return cache_key

    @staticmethod
    def _normalize_position_code(position_code: Any) -> str:
        if position_code is None:
            return POSITION_NONE
        text = str(position_code).strip()
        if not text:
            return POSITION_NONE
        return text if text in KNOWN_POSITION_CODES else POSITION_NONE

    @staticmethod
    def _is_supported_metrics_code(metrics_code: str) -> bool:
        return metrics_code in SUPPORTED_METRICS_CODES

    @staticmethod
    def _is_value_in_range(metrics_code: str, value: Any) -> bool:
        if value is None:
            return False
        bounds = METRICS_VALUE_RANGES.get(metrics_code)
        if bounds is None:
            return True
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return False
        min_value, max_value = bounds
        return min_value <= numeric_value <= max_value

    def get_value(self, object_id: int, metrics_code: str) -> Optional[float]:
        metrics_data = self.latest_metrics.get(f"{object_id}_{metrics_code}")
        if metrics_data:
            return metrics_data.get("value")
        return None

    def get_attribute_from_any_metric(self, object_id: int, attr_name: str) -> Optional[float]:
        """在指定对象的全部缓存指标中查找 attributes JSON payload 里的属性。"""
        prefix = f"{object_id}_"
        for cache_key, metrics_data in self.latest_metrics.items():
            if cache_key.startswith(prefix):
                attributes = metrics_data.get("attributes")
                if attributes:
                    if isinstance(attributes, str):
                        import json
                        try:
                            attrs = json.loads(attributes)
                        except Exception:
                            continue
                    elif isinstance(attributes, dict):
                        attrs = attributes
                    else:
                        continue

                    if isinstance(attrs, dict) and attr_name in attrs:
                        try:
                            return float(attrs[attr_name])
                        except (ValueError, TypeError):
                            pass
        return None

    def by_step(self, step_index: int) -> Dict[str, Dict[str, Any]]:
        return dict(self.metrics_by_step.get(int(step_index), {}))

    def history(self) -> Dict[int, Dict[str, Dict[str, Any]]]:
        return {step: dict(metrics) for step, metrics in self.metrics_by_step.items()}

    def to_sensor_data(self) -> List["SensorData"]:
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
