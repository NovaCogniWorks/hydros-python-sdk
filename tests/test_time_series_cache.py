import unittest

from hydros_agent_sdk.runtime.time_series_cache import TimeSeriesCache
from hydros_agent_sdk.protocol.models import ObjectTimeSeries, TimeSeriesValue


class TimeSeriesCacheTest(unittest.TestCase):
    def test_get_value_returns_value_for_object_metric_and_step(self):
        cache = TimeSeriesCache()
        cache.update(
            ObjectTimeSeries(
                object_id=1,
                object_name="node-a",
                object_type="NODE",
                metrics_code="WATER_LEVEL",
                time_series=[
                    TimeSeriesValue(step=1, value=72.1),
                    TimeSeriesValue(step=2, value=72.4),
                ],
            )
        )

        self.assertEqual(cache.get_value(1, "WATER_LEVEL", 2), 72.4)
        self.assertIsNone(cache.get_value(1, "WATER_LEVEL", 3))
        self.assertIsNone(cache.get_value(1, "WATER_FLOW", 2))


if __name__ == "__main__":
    unittest.main()
