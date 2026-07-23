import unittest

from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache


class FieldMetricsCacheTest(unittest.TestCase):
    def test_updates_latest_and_step_cache_for_none_position_metrics(self):
        cache = FieldMetricsCache(max_steps=3)

        directional_key = cache.update(
            {
                "biz_scene_instance_id": "TASK_001",
                "object_id": 1001,
                "metrics_code": "water_flow",
                "value": 1.0,
                "step_index": 1,
                "position_code": "up_stream",
            }
        )
        cache_key = cache.update(
            {
                "biz_scene_instance_id": "TASK_001",
                "object_id": 1001,
                "object_type": "Gate",
                "metrics_code": "water_flow",
                "value": 2.0,
                "step_index": 2,
                "position_code": "none",
                "attributes": "{\"front_water_flow\":2.0}",
            }
        )

        self.assertEqual(directional_key, "TASK_001#1001#water_flow#up_stream")
        self.assertEqual(cache_key, "TASK_001#1001#water_flow#none")
        self.assertEqual(cache.get_value(1001, "water_flow"), 2.0)
        self.assertEqual(cache.get_value(1001, "water_flow", "up_stream"), 1.0)
        self.assertEqual(cache.by_step(1)["TASK_001#1001#water_flow#up_stream"]["position_code"], "up_stream")
        self.assertEqual(cache.by_step(2)["TASK_001#1001#water_flow#none"]["position_code"], "none")
        self.assertEqual(cache.by_step(2)["TASK_001#1001#water_flow#none"]["attributes"], "{\"front_water_flow\":2.0}")

    def test_trims_step_history_by_max_steps(self):
        cache = FieldMetricsCache(max_steps=2)

        for step in range(1, 5):
            cache.update(
                {
                    "biz_scene_instance_id": "TASK_001",
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
                "biz_scene_instance_id": "TASK_001",
                "object_id": 1001,
                "metrics_code": "water_level",
                "value": 2.0,
                "step_index": 2,
            }
        )

        self.assertEqual(cache_key, "TASK_001#1001#water_level#none")
        self.assertEqual(cache.by_step(2)["TASK_001#1001#water_level#none"]["position_code"], "none")

    def test_reads_directional_attribute_from_top_level_payload(self):
        cache = FieldMetricsCache(max_steps=3)

        cache.update(
            {
                "biz_scene_instance_id": "TASK_001",
                "object_id": 20001,
                "object_type": "Pump",
                "metrics_code": "blade_angle",
                "value": 100.0,
                "step_index": 1,
                "back_water_flow": 3.5,
            }
        )

        self.assertEqual(cache.get_attribute_from_any_metric(20001, "back_water_flow"), 3.5)
        self.assertEqual(
            cache.by_step(1)["TASK_001#20001#blade_angle#none"]["back_water_flow"],
            3.5,
        )

    def test_keeps_custom_metrics_but_excludes_them_from_sensor_data(self):
        cache = FieldMetricsCache(max_steps=3)

        custom_key = cache.update(
            {
                "biz_scene_instance_id": "TASK_001",
                "object_id": 1001,
                "metrics_code": "pump_status",
                "value": 2.0,
                "step_index": 2,
                "position_code": "none",
            }
        )
        out_of_range_key = cache.update(
            {
                "biz_scene_instance_id": "TASK_001",
                "object_id": 1002,
                "metrics_code": "water_level",
                "value": 1001.0,
                "step_index": 2,
                "position_code": "none",
            }
        )

        self.assertEqual(custom_key, "TASK_001#1001#pump_status#none")
        self.assertEqual(out_of_range_key, "TASK_001#1002#water_level#none")
        self.assertEqual(cache.get_value(1001, "pump_status"), 2.0)
        self.assertEqual(cache.get_value(1001, "PUMP_STATUS"), 2.0)
        self.assertEqual(cache.to_sensor_data(), [])

    def test_converts_latest_metrics_to_sensor_data(self):
        cache = FieldMetricsCache(max_steps=3)
        cache.update(
            {
                "biz_scene_instance_id": "TASK_001",
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

    def test_excludes_directional_metrics_from_mpc_sensor_data(self):
        cache = FieldMetricsCache(max_steps=3)
        cache.update(
            {
                "biz_scene_instance_id": "TASK_001",
                "object_id": 1001,
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 7,
                "position_code": "up_stream",
            }
        )

        self.assertEqual(cache.get_value(1001, "water_level", "up_stream"), 12.5)
        self.assertEqual(cache.to_mpc_sensor_data(), [])

    def test_uses_default_task_identity_when_payload_omits_task_id(self):
        cache = FieldMetricsCache(max_steps=3, biz_scene_instance_id="TASK_DEFAULT")

        cache_key = cache.update(
            {
                "object_id": 1001,
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 7,
            }
        )

        self.assertEqual(cache_key, "TASK_DEFAULT#1001#water_level#none")
        self.assertEqual(cache.get_value(1001, "water_level"), 12.5)


if __name__ == "__main__":
    unittest.main()
