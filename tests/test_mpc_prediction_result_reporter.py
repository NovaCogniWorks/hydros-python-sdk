import json
import unittest
from types import SimpleNamespace

from hydros_agent_sdk.mpc.models import (
    ControlObjectResult,
    DeviceResult,
    HorizonStep,
    MpcOptimizeResponse,
    PredictedResult,
    ValueItem,
)
from hydros_agent_sdk.mpc.mpc_prediction_result_reporter import (
    MpcPredictionResultReporter,
)
from hydros_agent_sdk.protocol.models import (
    AgentDriveMode,
    HydroAgentInstance,
    SimulationContext,
)


def build_source_agent(context: SimulationContext) -> HydroAgentInstance:
    return HydroAgentInstance(
        agent_id="central-agent",
        agent_code="CENTRAL_SCHEDULING_AGENT",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="central-agent",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster-a",
        hydros_node_id="node-a",
        context=context,
        drive_mode=AgentDriveMode.PROACTIVE,
    )


class MpcPredictionResultReporterTest(unittest.TestCase):
    def test_default_report_builds_control_only_water_level_response(self):
        state = SimpleNamespace(
            context=SimulationContext(biz_scene_instance_id="scene-control-only"),
            current_step=4,
            max_steps=12,
            rolling_interval_steps=3,
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
                                ValueItem(value_type="water_level", value=3.4)
                            ],
                        )
                    ],
                )
            ],
        )

        report = MpcPredictionResultReporter().build_report(
            build_source_agent(state.context),
            state,
            [response],
        )

        self.assertIsNotNone(report)
        self.assertEqual(len(report.mpc_prediction_results), 1)
        result = report.mpc_prediction_results[0]
        self.assertEqual(len(result.details), 1)
        detail = result.details[0]
        self.assertEqual(detail.node_id, 101)
        self.assertEqual(detail.object_id, 101)
        self.assertEqual(detail.command_type, "water_level")
        self.assertEqual(detail.target_value, 3.4)
        self.assertEqual(
            detail.biz_idem_key,
            "MPC_DETAIL:4:1:101:101:water_level",
        )

    def test_default_report_skips_control_only_non_water_level_response(self):
        state = SimpleNamespace(
            context=SimulationContext(biz_scene_instance_id="scene-control-only"),
            current_step=4,
            max_steps=12,
            rolling_interval_steps=3,
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
                                ValueItem(value_type="gate_opening", value=0.4)
                            ],
                        )
                    ],
                )
            ],
        )

        report = MpcPredictionResultReporter().build_report(
            SimpleNamespace(context=state.context),
            state,
            [response],
        )

        self.assertIsNone(report)

    def test_truncates_horizon_at_zero_based_max_steps_boundary(self):
        state = SimpleNamespace(
            context=SimulationContext(biz_scene_instance_id="scene-96-steps"),
            current_step=0,
            max_steps=96,
            rolling_interval_steps=10,
        )
        horizons = [
            HorizonStep(
                horizon_step=step,
                control_object_list=[
                    ControlObjectResult(
                        object_type="GateStation",
                        object_id=101,
                        target_value_list=[
                            ValueItem(value_type="water_level", value=3.5),
                        ],
                    )
                ],
            )
            for step in range(1, 98)
        ]

        result = MpcPredictionResultReporter.build_prediction_result(
            mpc_task_state=state,
            horizon_step=horizons,
            plan_type="OPTIMAL",
        )

        self.assertEqual(len(result.details), 96)
        self.assertEqual(
            [detail.horizon_step for detail in result.details],
            list(range(1, 97)),
        )

    def test_truncates_rolling_horizon_near_task_end(self):
        state = SimpleNamespace(
            context=SimulationContext(biz_scene_instance_id="scene-last-window"),
            current_step=90,
            max_steps=96,
            rolling_interval_steps=10,
        )
        horizons = [
            HorizonStep(
                horizon_step=step,
                control_object_list=[
                    ControlObjectResult(
                        object_type="GateStation",
                        object_id=101,
                        target_value_list=[
                            ValueItem(value_type="water_level", value=3.5),
                        ],
                    )
                ],
            )
            for step in range(1, 11)
        ]

        result = MpcPredictionResultReporter.build_prediction_result(
            mpc_task_state=state,
            horizon_step=horizons,
            plan_type="OPTIMAL",
        )

        self.assertEqual(
            [detail.horizon_step for detail in result.details],
            list(range(1, 7)),
        )

    def test_projects_structured_station_and_device_predictions(self):
        state = SimpleNamespace(
            context=SimulationContext(biz_scene_instance_id="scene-structured-report"),
            current_step=4,
            max_steps=12,
            rolling_interval_steps=3,
        )
        horizon = HorizonStep(
            horizon_step=1,
            control_object_list=[
                ControlObjectResult(
                    object_type="GateStation",
                    object_id=101,
                    target_value_list=[
                        ValueItem(value_type="water_level", value=3.5),
                    ],
                )
            ],
            predicted_result_list=[
                PredictedResult(
                    object_type="GateStation",
                    object_id=101,
                    target_value=ValueItem(
                        value_type="WATER_LEVEL",
                        value=3.5,
                    ),
                    predicted_value_list=[
                        ValueItem(value_type="front_water_level", value=3.4),
                        ValueItem(value_type="back_water_level", value=3.1),
                        ValueItem(value_type="out_flow", value=18.5),
                    ],
                    device_result_list=[
                        DeviceResult(
                            object_type="Gate",
                            object_id=501,
                            value_list=[
                                ValueItem(value_type="gate_opening", value=0.45),
                                ValueItem(value_type="enabled", value=True),
                            ],
                        )
                    ],
                )
            ],
        )

        result = MpcPredictionResultReporter.build_prediction_result(
            mpc_task_state=state,
            horizon_step=[horizon],
            plan_type="OPTIMAL",
        )

        self.assertEqual(len(result.details), 2)
        self.assertEqual(len(result.station_prediction_details), 1)
        self.assertEqual(len(result.device_prediction_details), 1)
        station_detail, device_detail = result.details
        self.assertEqual(station_detail.object_id, 101)
        self.assertEqual(station_detail.target_value, 3.5)
        self.assertEqual(station_detail.front_water_level, 3.4)
        self.assertEqual(station_detail.back_water_level, 3.1)
        self.assertEqual(station_detail.out_flow, 18.5)
        self.assertEqual(
            station_detail.biz_idem_key,
            "MPC_DETAIL:4:1:101:101:water_level",
        )
        self.assertEqual(device_detail.node_id, 101)
        self.assertEqual(device_detail.object_id, 501)
        self.assertEqual(device_detail.command_type, "gate_opening")
        self.assertEqual(device_detail.value, 0.45)
        self.assertEqual(
            device_detail.biz_idem_key,
            "MPC_DETAIL:4:1:101:501:gate_opening",
        )
        self.assertEqual(json.loads(device_detail.attributes)["value_role"], "forecast")

    def test_projects_pollutant_concentration_as_independent_prediction_detail(self):
        state = SimpleNamespace(
            context=SimulationContext(biz_scene_instance_id="scene-pollution-report"),
            current_step=10,
            max_steps=36,
            rolling_interval_steps=10,
        )
        horizon = HorizonStep(
            horizon_step=1,
            predicted_result_list=[
                PredictedResult(
                    object_type="Canal",
                    object_id=701,
                    target_value=ValueItem(
                        value_type="safe_concentration",
                        value=0.3,
                    ),
                    predicted_value_list=[
                        ValueItem(value_type="front_water_level", value=12.4),
                        ValueItem(value_type="pollutant_concentration", value=0.72),
                    ],
                )
            ],
        )

        result = MpcPredictionResultReporter.build_prediction_result(
            mpc_task_state=state,
            horizon_step=[horizon],
            plan_type="OPTIMAL",
        )

        self.assertEqual(len(result.station_prediction_details), 2)
        hydraulic_detail, pollutant_detail = result.station_prediction_details
        self.assertEqual(hydraulic_detail.command_type, "water_level")
        self.assertEqual(hydraulic_detail.value, 12.4)
        self.assertIsNone(hydraulic_detail.target_value)
        self.assertEqual(
            pollutant_detail.biz_idem_key,
            "MPC_DETAIL:10:1:701:701:pollutant_concentration",
        )
        self.assertEqual(
            pollutant_detail.command_type,
            "pollutant_concentration",
        )
        self.assertEqual(pollutant_detail.value, 0.72)
        self.assertEqual(pollutant_detail.target_value, 0.3)
        self.assertEqual(
            json.loads(pollutant_detail.attributes),
            {
                "value_role": "forecast",
                "final_target_safe_concentration": 0.3,
            },
        )


if __name__ == "__main__":
    unittest.main()
