import unittest

from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache


class FieldMetricsCacheTest(unittest.TestCase):
    def test_updates_latest_and_step_cache_for_none_position_metrics(self):
        cache = FieldMetricsCache(max_steps=3)

        self.assertIsNone(
            cache.update(
                {
                    "object_id": 1001,
                    "metrics_code": "water_flow",
                    "value": 1.0,
                    "step_index": 1,
                    "position_code": "up_stream",
                }
            )
        )
        cache_key = cache.update(
            {
                "object_id": 1001,
                "object_type": "Gate",
                "metrics_code": "water_flow",
                "value": 2.0,
                "step_index": 2,
                "position_code": "none",
                "attributes": "{\"front_water_flow\":2.0}",
            }
        )

        self.assertEqual(cache_key, "1001_water_flow")
        self.assertEqual(cache.get_value(1001, "water_flow"), 2.0)
        self.assertEqual(cache.by_step(1), {})
        self.assertEqual(cache.by_step(2)["1001_water_flow"]["position_code"], "none")
        self.assertEqual(cache.by_step(2)["1001_water_flow"]["attributes"], "{\"front_water_flow\":2.0}")

    def test_trims_step_history_by_max_steps(self):
        cache = FieldMetricsCache(max_steps=2)

        for step in range(1, 5):
            cache.update(
                {
                    "object_id": 1001,
                    "metrics_code": "water_flow",
                    "value": float(step),
                    "step_index": step,
                    "position_code": "none",
                }
            )

        self.assertEqual(set(cache.history().keys()), {3, 4})
        self.assertEqual(cache.get_value(1001, "water_flow"), 4.0)

    def test_defaults_missing_position_code_to_none(self):
        cache = FieldMetricsCache(max_steps=3)

        cache_key = cache.update(
            {
                "object_id": 1001,
                "metrics_code": "water_level",
                "value": 2.0,
                "step_index": 2,
            }
        )

        self.assertEqual(cache_key, "1001_water_level")
        self.assertEqual(cache.by_step(2)["1001_water_level"]["position_code"], "none")

    def test_ignores_unsupported_metric_codes_and_out_of_range_values(self):
        cache = FieldMetricsCache(max_steps=3)

        self.assertIsNone(
            cache.update(
                {
                    "object_id": 1001,
                    "metrics_code": "water_volume",
                    "value": 2.0,
                    "step_index": 2,
                    "position_code": "none",
                }
            )
        )
        self.assertIsNone(
            cache.update(
                {
                    "object_id": 1001,
                    "metrics_code": "water_level",
                    "value": 1001.0,
                    "step_index": 2,
                    "position_code": "none",
                }
            )
        )
        self.assertEqual(cache.history(), {})

    def test_converts_latest_metrics_to_sensor_data(self):
        cache = FieldMetricsCache(max_steps=3)
        cache.update(
            {
                "object_id": 1001,
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 7,
                "position_code": "none",
                "attributes": "{\"front_water_level\":12.5}",
            }
        )

        sensor_data = cache.to_sensor_data()

        self.assertEqual(len(sensor_data), 1)
        self.assertEqual(sensor_data[0].object_id, 1001)
        self.assertEqual(sensor_data[0].metrics_code, "water_level")
        self.assertEqual(sensor_data[0].value, 12.5)
        self.assertEqual(sensor_data[0].step_index, 7)
        self.assertEqual(sensor_data[0].attributes, "{\"front_water_level\":12.5}")


if __name__ == "__main__":
    unittest.main()
