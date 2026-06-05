"""时序数据缓存。"""

from __future__ import annotations

from typing import Dict, Optional

from hydros_agent_sdk.protocol.models import ObjectTimeSeries


class TimeSeriesCache:
    """按对象和指标缓存 ObjectTimeSeries，并提供按 step 查询。"""

    def __init__(self):
        self.store: Dict[str, ObjectTimeSeries] = {}

    @staticmethod
    def build_key(object_id: int, metrics_code: str) -> str:
        return f"{object_id}_{metrics_code}"

    def update(self, object_time_series: ObjectTimeSeries) -> None:
        self.store[
            self.build_key(
                object_time_series.object_id,
                object_time_series.metrics_code,
            )
        ] = object_time_series

    def get(self, object_id: int, metrics_code: str) -> Optional[ObjectTimeSeries]:
        return self.store.get(self.build_key(object_id, metrics_code))

    def get_value(
        self,
        object_id: int,
        metrics_code: str,
        step: int,
    ) -> Optional[float]:
        time_series = self.get(object_id, metrics_code)
        if not time_series or not time_series.time_series:
            return None

        for ts_value in time_series.time_series:
            if ts_value.step == step:
                return ts_value.value
        return None
