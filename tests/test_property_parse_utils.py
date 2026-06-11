import unittest

from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.utils.property_parse_utils import PropertyParseUtils


class PropertyParseUtilsTest(unittest.TestCase):
    def test_reads_typed_values_from_agent_properties(self):
        properties = AgentProperties()
        properties["roll_steps"] = "6"
        properties["threshold"] = "3.5"
        properties["topic"] = 1001
        properties["enabled"] = "yes"

        self.assertEqual(PropertyParseUtils.get_int(properties, "roll_steps", 1), 6)
        self.assertEqual(PropertyParseUtils.get_float(properties, "threshold", 1.0), 3.5)
        self.assertEqual(PropertyParseUtils.get_string(properties, "topic", None), "1001")
        self.assertTrue(PropertyParseUtils.get_bool(properties, "enabled", False))

    def test_uses_defaults_and_preserves_missing_string_as_none(self):
        properties = AgentProperties()

        self.assertEqual(PropertyParseUtils.get_int(properties, "roll_steps", 3), 3)
        self.assertEqual(PropertyParseUtils.get_float(properties, "threshold", 1.25), 1.25)
        self.assertEqual(PropertyParseUtils.get_string(properties, "topic", "metrics"), "metrics")
        self.assertIsNone(PropertyParseUtils.get_string(properties, "topic", None))
        self.assertFalse(PropertyParseUtils.get_bool(properties, "enabled", False))

    def test_required_numeric_properties_raise_when_missing(self):
        properties = AgentProperties()

        with self.assertRaises(ValueError):
            PropertyParseUtils.get_int(properties, "roll_steps", None)

        with self.assertRaises(ValueError):
            PropertyParseUtils.get_float(properties, "threshold", None)


if __name__ == "__main__":
    unittest.main()
