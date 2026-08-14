import unittest

from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import SimulationContext


class MpcTaskStateTest(unittest.TestCase):
    def test_tracks_runtime_injection_step_by_event_identity(self):
        state = MpcTaskState(
            context=SimulationContext(biz_scene_instance_id="scene-injection-step"),
            rolling_interval_steps=10,
            start_step=5,
        )
        first_event = TimeSeriesDataChangedEvent(auto_schedule_at_step=2)
        second_event = TimeSeriesDataChangedEvent(auto_schedule_at_step=2)

        state.register_hydro_event(first_event, injected_start_step=5)
        state.register_hydro_event(second_event, injected_start_step=8)

        self.assertEqual(state.get_injected_start_step(first_event), 5)
        self.assertEqual(state.get_injected_start_step(second_event), 8)

    def test_injection_step_falls_back_to_event_schedule_step(self):
        state = MpcTaskState(
            context=SimulationContext(biz_scene_instance_id="scene-injection-fallback"),
            rolling_interval_steps=10,
            start_step=5,
        )
        event = TimeSeriesDataChangedEvent(auto_schedule_at_step=7)

        state.register_hydro_event(event)

        self.assertEqual(state.get_injected_start_step(event), 7)

    def test_does_not_roll_at_or_after_total_steps_boundary(self):
        state = MpcTaskState(
            context=SimulationContext(biz_scene_instance_id="scene-96-steps"),
            rolling_interval_steps=1,
            start_step=0,
            current_step=0,
            total_steps=96,
        )

        self.assertTrue(state.should_start_new_rolling(95))
        self.assertFalse(state.should_start_new_rolling(96))
        self.assertFalse(state.should_start_new_rolling(97))


if __name__ == "__main__":
    unittest.main()
