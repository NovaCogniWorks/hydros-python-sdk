import unittest

from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.protocol.models import SimulationContext


class MpcTaskStateTest(unittest.TestCase):
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
