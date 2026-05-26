import unittest

from hydros_agent_sdk.mpc.metrics_data_cache import MetricsDataCache


class MetricsDataCacheTest(unittest.TestCase):
    def test_updates_latest_and_step_cache_for_none_position_metrics(self):
        cache = MetricsDataCache(max_steps=3)

        self.assertIsNone(
            cache.update(
                {
                    "object_id": 1001,
                    "metrics_code": "flow",
                    "value": 1.0,
                    "step_index": 1,
                    "position_code": "upstream",
                }
            )
        )
        cache_key = cache.update(
            {
                "object_id": 1001,
                "object_type": "Gate",
                "metrics_code": "flow",
                "value": 2.0,
                "step_index": 2,
                "position_code": "none",
            }
        )

        self.assertEqual(cache_key, "1001_flow")
        self.assertEqual(cache.get_value(1001, "flow"), 2.0)
        self.assertEqual(cache.by_step(1), {})
        self.assertEqual(cache.by_step(2)["1001_flow"]["position_code"], "none")

    def test_trims_step_history_by_max_steps(self):
        cache = MetricsDataCache(max_steps=2)

        for step in range(1, 5):
            cache.update(
                {
                    "object_id": 1001,
                    "metrics_code": "flow",
                    "value": float(step),
                    "step_index": step,
                    "position_code": "none",
                }
            )

        self.assertEqual(set(cache.history().keys()), {3, 4})
        self.assertEqual(cache.get_value(1001, "flow"), 4.0)

    def test_converts_latest_metrics_to_sensor_data(self):
        cache = MetricsDataCache(max_steps=3)
        cache.update(
            {
                "object_id": 1001,
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 7,
                "position_code": "none",
            }
        )

        sensor_data = cache.to_sensor_data()

        self.assertEqual(len(sensor_data), 1)
        self.assertEqual(sensor_data[0].object_id, 1001)
        self.assertEqual(sensor_data[0].metrics_code, "water_level")
        self.assertEqual(sensor_data[0].value, 12.5)
        self.assertEqual(sensor_data[0].step_index, 7)


if __name__ == "__main__":
    unittest.main()
