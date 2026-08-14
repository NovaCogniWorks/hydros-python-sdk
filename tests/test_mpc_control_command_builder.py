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
    def test_reports_unresolved_target_without_dropping_dispatchable_commands(self):
        context = SimulationContext(biz_scene_instance_id="scene-partial-build")
        source = build_agent("source-agent", context)
        target = build_agent("target-agent", context)
        builder = MpcControlCommandBuilder(
            source_agent=source,
            get_sibling_agent_instance=lambda _agent_code: target,
            resolve_target_agent_for_object=(
                lambda object_id, _object_type: target if object_id == 101 else None
            ),
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
                                ValueItem(value_type="water_level", value=3.5)
                            ],
                        ),
                        ControlObjectResult(
                            object_type="PumpStation",
                            object_id=102,
                            target_value_list=[
                                ValueItem(value_type="water_level", value=4.5)
                            ],
                        ),
                    ],
                )
            ],
        )
        plan = MpcControlExecutionPlan.from_responses(4, [response])

        result = builder.build_result_from_control_plan(
            plan,
            horizon_step=1,
            current_step=4,
        )

        self.assertEqual([command.object_id for command in result.commands], [101])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].control_target.object_id, 102)
        self.assertEqual(
            result.failures[0].error_code,
            "MPC_CONTROL_COMMAND_DISPATCH_FAILED",
        )

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
                            algo_required_inputs=[
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
        self.assertTrue(commands[0].group_id.startswith("MPC_CTRL_GROUP:scene-structured-control:4:4:1:water_level:"))
        self.assertEqual(len(commands[0].algo_required_inputs), 1)
        planning_signal = commands[0].algo_required_inputs[0]
        self.assertEqual(planning_signal.value_type, "front_water_level")
        self.assertEqual(planning_signal.series, [3.3, 3.7])
        self.assertEqual(planning_signal.attributes, {"source": "mpc"})

    def test_accepts_all_numeric_targets_for_edge_executable_station_types(self):
        context = SimulationContext(biz_scene_instance_id="scene-mixed-control")
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
                            object_id=1001,
                            target_value_list=[ValueItem(value_type="water_level", value=12.5)],
                        ),
                        ControlObjectResult(
                            object_type="PowerStation",
                            object_id=2001,
                            target_value_list=[
                                ValueItem(value_type="output_power", value=88.0),
                                ValueItem(value_type="water_flow", value=8.0),
                            ],
                        ),
                        ControlObjectResult(
                            object_type="PumpStation",
                            object_id=3001,
                            target_value_list=[ValueItem(value_type="WATER_FLOW", value=6.0)],
                        ),
                        ControlObjectResult(
                            object_type="Turbine",
                            object_id=4001,
                            target_value_list=[ValueItem(value_type="output_power", value=54.25614)],
                        ),
                    ],
                )
            ],
        )

        plan = MpcControlExecutionPlan.from_responses(4, [response])
        commands = builder.build_from_control_plan(plan, horizon_step=1, current_step=4)

        self.assertEqual(4, len(commands))
        commands_by_key = {
            (command.object_id, command.target_value_type.lower()): command
            for command in commands
        }
        power_flow_command = commands_by_key[(2001, "water_flow")]
        power_output_command = commands_by_key[(2001, "output_power")]
        pump_flow_command = commands_by_key[(3001, "water_flow")]
        gate_level_command = commands_by_key[(1001, "water_level")]
        self.assertEqual("PowerStation", power_output_command.object_type)
        self.assertEqual(88.0, power_output_command.target_value)
        self.assertEqual(1, gate_level_command.group_size)
        self.assertEqual(1, power_output_command.group_size)
        self.assertEqual(2, power_flow_command.group_size)
        self.assertEqual(2, pump_flow_command.group_size)
        self.assertIn(":water_level:", gate_level_command.group_id)
        self.assertIn(":output_power:", power_output_command.group_id)
        self.assertIn(":water_flow:", power_flow_command.group_id)
        self.assertEqual(
            power_flow_command.group_id,
            pump_flow_command.group_id,
        )
        self.assertFalse(any(command.object_id == 4001 for command in commands))


if __name__ == "__main__":
    unittest.main()
