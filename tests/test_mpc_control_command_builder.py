import unittest

from hydros_agent_sdk.control_algorithms import ControlSignal, SignalType
from hydros_agent_sdk.mpc.control_command_builder import MpcControlCommandBuilder
from hydros_agent_sdk.mpc.control_execution_plan import MpcControlExecutionPlan
from hydros_agent_sdk.mpc.models import (
    ControlObjectResult,
    HorizonStep,
    MpcOptimizeResponse,
    PredictedResult,
    ValueItem,
)
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    HydroAgentInstance,
    SimulationContext,
)


def build_agent(agent_id: str, context: SimulationContext) -> HydroAgentInstance:
    return HydroAgentInstance(
        agent_id=agent_id,
        agent_code=agent_id,
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name=agent_id,
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster-a",
        hydros_node_id="node-a",
        context=context,
        drive_mode=AgentDriveMode.PROACTIVE,
    )


class MpcControlCommandBuilderTest(unittest.TestCase):
    def test_builds_commands_only_from_numeric_structured_control_targets(self):
        context = SimulationContext(biz_scene_instance_id="scene-structured-control")
        source = build_agent("source-agent", context)
        target = build_agent("target-agent", context)
        builder = MpcControlCommandBuilder(
            source_agent=source,
            get_sibling_agent_instance=lambda _agent_code: target,
            resolve_target_agent_for_object=lambda _object_id, _object_type: target,
        )
        response = MpcOptimizeResponse(
            plan_type="OPTIMAL",
            horizon_controls=[
                HorizonStep(
                    horizon_step=1,
                    control_object_list=[
                        ControlObjectResult(
                            object_type="GateStation",
                            object_id=101,
                            target_value_list=[
                                ValueItem(value_type="water_level", value=3.5),
                                ValueItem(value_type="enabled", value=True),
                                ValueItem(value_type="label", value="manual"),
                            ],
                            planning_signals=[
                                ControlSignal(
                                    type=SignalType.REFERENCE,
                                    object_type="GateStation",
                                    object_id=101,
                                    value_type="front_water_level",
                                    value=3.3,
                                    series=[3.3, 3.7],
                                    attributes={"source": "mpc"},
                                )
                            ],
                        )
                    ],
                    predicted_result_list=[
                        PredictedResult(
                            object_type="GateStation",
                            object_id=101,
                            target_value=ValueItem(
                                value_type="water_level",
                                value=3.6,
                            ),
                            predicted_value_list=[
                                ValueItem(value_type="front_water_level", value=3.4)
                            ],
                        )
                    ],
                ),
                HorizonStep(
                    horizon_step=2,
                    predicted_result_list=[
                        PredictedResult(
                            object_type="GateStation",
                            object_id=101,
                            predicted_value_list=[
                                ValueItem(value_type="front_water_level", value=3.6)
                            ],
                        )
                    ],
                ),
            ],
        )

        plan = MpcControlExecutionPlan.from_responses(4, [response])
        commands = builder.build_from_control_plan(plan, horizon_step=1, current_step=4)

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].object_id, 101)
        self.assertEqual(commands[0].target_value_type, "water_level")
        self.assertEqual(commands[0].target_value, 3.5)
        self.assertEqual(commands[0].group_size, 1)
        self.assertEqual(commands[0].main_step_index, 4)
        self.assertTrue(commands[0].group_id.startswith("MPC_CTRL_GROUP:scene-structured-control:4:4:1:"))
        self.assertEqual(len(commands[0].planning_signals), 1)
        planning_signal = commands[0].planning_signals[0]
        self.assertEqual(planning_signal.value_type, "front_water_level")
        self.assertEqual(planning_signal.series, [3.3, 3.7])
        self.assertEqual(planning_signal.attributes, {"source": "mpc"})


if __name__ == "__main__":
    unittest.main()
