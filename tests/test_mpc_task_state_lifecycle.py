import unittest

from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import ObjectTimeSeries, SimulationContext
from hydros_agent_sdk.mpc.task_state_lifecycle import MpcTaskStateLifecycle


class MpcTaskStateLifecycleTest(unittest.TestCase):
    def test_ensure_task_state_creates_mpc_task_state(self):
        context = SimulationContext(biz_scene_instance_id="scene-lifecycle")
        lifecycle = MpcTaskStateLifecycle(
            context=context,
            get_rolling_interval_steps=lambda: 2,
            get_total_steps=lambda: 12,
            get_output_step_size=lambda: 3600,
            get_algorithm_config_url=lambda: "http://config/algorithm.yaml",
            get_control_config_url=lambda: "http://config/control.yaml",
        )

        state = lifecycle.ensure_task_state(3)

        self.assertIs(lifecycle.task_state, state)
        self.assertEqual(state.context, context)
        self.assertEqual(state.rolling_interval_steps, 2)
        self.assertEqual(state.start_step, 3)
        self.assertEqual(state.current_step, 3)
        self.assertEqual(state.total_steps, 12)
        self.assertEqual(state.output_step_size, 3600)
        self.assertEqual(state.algorithm_config_url, "http://config/algorithm.yaml")
        self.assertEqual(state.control_config_url, "http://config/control.yaml")

    def test_activate_from_event_uses_event_step_and_registers_event(self):
        context = SimulationContext(biz_scene_instance_id="scene-lifecycle-event")
        lifecycle = MpcTaskStateLifecycle(
            context=context,
            get_current_step=lambda: 1,
            get_rolling_interval_steps=lambda: 5,
            get_total_steps=lambda: 20,
        )
        event = TimeSeriesDataChangedEvent(
            hydro_event_source_type="WATER_USE",
            auto_schedule_at_step=7,
            object_time_series=[ObjectTimeSeries(object_id=1001)],
        )

        state = lifecycle.activate_from_event(event)

        self.assertIsNotNone(state)
        self.assertEqual(state.current_step, 7)
        self.assertEqual(state.start_step, 7)
        self.assertEqual(state.hydro_events, [event])

    def test_activate_from_event_can_use_resolved_step_over_event_step(self):
        context = SimulationContext(biz_scene_instance_id="scene-lifecycle-resolved-step")
        lifecycle = MpcTaskStateLifecycle(
            context=context,
            get_current_step=lambda: 10,
            get_rolling_interval_steps=lambda: 5,
            get_total_steps=lambda: 20,
        )
        event = TimeSeriesDataChangedEvent(
            hydro_event_source_type="WATER_USE",
            auto_schedule_at_step=2,
            object_time_series=[ObjectTimeSeries(object_id=1001)],
        )

        state = lifecycle.activate_from_event(event, step=10, use_event_step=False)

        self.assertIsNotNone(state)
        self.assertEqual(state.current_step, 10)
        self.assertEqual(state.start_step, 10)

    def test_ensure_task_state_refreshes_existing_state_without_resetting_start_step(self):
        context = SimulationContext(biz_scene_instance_id="scene-lifecycle-refresh")
        total_steps = {"value": 20}
        lifecycle = MpcTaskStateLifecycle(
            context=context,
            get_rolling_interval_steps=lambda: 3,
            get_total_steps=lambda: total_steps["value"],
        )

        state = lifecycle.ensure_task_state(4)
        total_steps["value"] = 30
        refreshed = lifecycle.ensure_task_state(8)

        self.assertIs(refreshed, state)
        self.assertEqual(refreshed.start_step, 4)
        self.assertEqual(refreshed.current_step, 8)
        self.assertEqual(refreshed.total_steps, 30)

    def test_clear_releases_task_state(self):
        lifecycle = MpcTaskStateLifecycle(
            context=SimulationContext(biz_scene_instance_id="scene-lifecycle-clear"),
            get_rolling_interval_steps=lambda: 3,
            get_total_steps=lambda: 30,
        )
        lifecycle.ensure_task_state(4)

        lifecycle.clear()

        self.assertIsNone(lifecycle.task_state)


if __name__ == "__main__":
    unittest.main()
