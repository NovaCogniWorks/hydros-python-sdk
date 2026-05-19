import unittest
from enum import Enum
from unittest.mock import patch

from hydros_agent_sdk.utils.id_generator import (
    generate_agent_instance_id,
    generate_system_command_id,
    generate_agent_command_id,
    generate_coordination_command_id,
    generate_alert_id,
    generate_sim_task_id,
    generate_hydro_event_id,
    generate_mqtt_client_id,
    generate_monitor_rule_id,
    generate_data_series_id,
    generate_sse_session_id,
    generate_user_id,
)


class DummyTaskType(Enum):
    SIMULATION = "SIMULATION"


class IdGeneratorTest(unittest.TestCase):
    def setUp(self):
        patcher = patch("hydros_agent_sdk.utils.id_generator.datetime")
        self.addCleanup(patcher.stop)
        self.mock_datetime = patcher.start()
        mock_now = self.mock_datetime.now.return_value
        mock_now.strftime.return_value = "202601011230"

        choice_patcher = patch("hydros_agent_sdk.utils.id_generator.choice", return_value="A")
        self.addCleanup(choice_patcher.stop)
        choice_patcher.start()

    def test_java_style_timestamped_ids(self):
        self.assertEqual(generate_agent_instance_id("TWINS_SIMULATION_AGENT"), "AGT202601011230AAAAAA_TWINS_SIMULATION_AGENT")
        self.assertEqual(generate_system_command_id(), "SYSCMD202601011230AAAAAAAAAAAA")
        self.assertEqual(generate_agent_command_id(), "AGTCMD202601011230AAAAAAAAAAAA")
        self.assertEqual(generate_coordination_command_id(), "SIMCMD202601011230AAAAAAAAAAAA")
        self.assertEqual(generate_alert_id(), "RISK202601011230AAAAAAAAAAAA")
        self.assertEqual(generate_sim_task_id(), "TASK202601011230AAAAAAAAAAAA")
        self.assertEqual(generate_monitor_rule_id(), "MRULE_202601011230_AAAAAAAA")
        self.assertEqual(generate_data_series_id(), "TIMESERIES_202601011230_AAAAAAAA")
        self.assertEqual(generate_user_id(), "U202601011230AAAAAAAA")

    def test_hydro_event_id(self):
        self.assertEqual(generate_hydro_event_id("FLOOD"), "EVENTFLOOD202601011230AAAAAA")

    def test_component_and_task_based_ids(self):
        self.assertEqual(
            generate_mqtt_client_id("central"),
            "MQTT_CLIENT_central_202601011230_AAAAAAAA",
        )
        self.assertEqual(
            generate_sse_session_id(DummyTaskType.SIMULATION),
            "SIMULATION_SSE_202601011230_AAAAAAAA",
        )


if __name__ == "__main__":
    unittest.main()
