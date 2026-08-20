import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("custom-agent/pump"))

from hydros_agent_sdk import (
    ControlActuator,
    ControlActuatorTarget,
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    ControlValueRange,
    SignalType,
)
from pump_flow_dmpc import (
    PumpFlowDmpcInputResolver,
    PumpStationFlowDmpcAlgorithm,
)
from pump_flow_dmpc.odd_dmpc.types import (
    ControlAction,
    PoolConfig,
    StationConfig,
    SystemConfig,
    UnitConfig,
)
from pump_flow_dmpc.plot_tracker import PumpFlowDmpcExecutionTracker
from pump_flow_dmpc.types import PumpFlowDmpcArguments
from pump_flow_dmpc_service import create_default_plot_tracker


class StubSolver:
    def solve(self, arguments):
        return ControlAction(
            station_id=arguments.station_id,
            mode=arguments.mode,
            selected_flow=min(arguments.reference_flow[0], 30.0),
            unit_status=dict(arguments.unit_status),
            unit_openings={
                unit_id: min(opening + 5.0, 40.0)
                for unit_id, opening in arguments.unit_openings.items()
            },
            unit_flows={
                unit_id: min(arguments.reference_flow[0], 30.0) / 2
                for unit_id in arguments.unit_openings
            },
            fit_score=0.95,
            objective=1.0,
            predicted_flow_error=0.0,
            predicted_level_error=0.0,
            predicted_back_level=5.0,
            predicted_front_level=10.0,
            predicted_head=5.0,
            predicted_efficiencies=[0.8, 0.8],
        )


class PumpFlowDmpcExecutionTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.output_dir = Path(self.tmpdir.name) / "plots"

    def _system_config(self):
        return SystemConfig(
            project="test",
            description="test",
            rho=1000.0,
            g=9.81,
            horizon_hours=72,
            dt_hours=1.0,
            target_avg_flow_last_station=20.0,
            stations=[
                StationConfig(
                    id=2001,
                    name="Station1",
                    level_back_min=0.0,
                    level_back_max=10.0,
                    level_front_min=0.0,
                    level_front_max=10.0,
                    num_units=2,
                    units=[
                        UnitConfig(id=2101, name="Pump1"),
                        UnitConfig(id=2102, name="Pump2"),
                    ],
                )
            ],
            canal_pools=[PoolConfig(id=1, name="Pool1")],
            flow_depart_step_q=1.0,
            flow_depart_step_h=1.0,
            flow_depart_data_dir="data",
            flow_depart_output_dir="output",
        )

    def _arguments(self):
        return PumpFlowDmpcArguments(
            station_id=2001,
            mode="ODD2",
            config_path="",
            active_unit_ids=[2101, 2102],
            unit_openings={2101: 10.0, 2102: 12.0},
            unit_status={2101: 1, 2102: 1},
            reference_flow=[20.5],
            reference_front_level=[10.0],
            reference_back_level=[5.0],
            reference_head=[5.0],
            available_unit_ids=[2101, 2102],
            unit_blade_bounds={2101: (0.0, 40.0), 2102: (0.0, 40.0)},
            current_front_level=10.0,
            current_back_level=5.0,
            current_head=5.0,
            current_flow=18.0,
        )

    def _action(self):
        return ControlAction(
            station_id=2001,
            mode="ODD2",
            selected_flow=20.5,
            unit_status={2101: 1, 2102: 1},
            unit_openings={2101: 15.0, 2102: 17.0},
            unit_flows={2101: 10.2, 2102: 10.3},
            fit_score=0.95,
            objective=1.2,
            predicted_flow_error=0.0,
            predicted_level_error=0.0,
            predicted_back_level=5.0,
            predicted_front_level=10.0,
            predicted_head=5.0,
            predicted_efficiencies=[0.8, 0.81],
            predicted_unit_efficiencies={2101: [0.8], 2102: [0.81]},
            predicted_unit_flows={2101: [10.2], 2102: [10.3]},
        )

    def _input(self):
        return ControlAlgorithmInput(
            schema_version="1.0",
            algorithm_type="pump_station_flow_dmpc",
            algorithm_version="1.8.1",
            control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
            context=ControlAlgorithmContext(
                request_id="request-001",
                context_id="scene-001",
                step_index=3,
                target_object_type="PumpStation",
                target_object_id=2001,
            ),
            signals=[],
            actuators=[],
        )

    def _output(self):
        return ControlAlgorithmOutput(
            schema_version="1.0",
            request_id="request-001",
            status=ControlAlgorithmStatus.CONTINUE,
            actuator_targets=[
                ControlActuatorTarget(
                    object_type="Pump",
                    object_id=2101,
                    available=True,
                    target_values={"blade_angle": 15.0},
                ),
                ControlActuatorTarget(
                    object_type="Pump",
                    object_id=2102,
                    available=True,
                    target_values={"blade_angle": 17.0},
                ),
            ],
        )

    def test_record_and_finalize_create_scheduling_style_files(self):
        tracker = PumpFlowDmpcExecutionTracker(output_dir=self.output_dir)
        tracker.record_decision(
            input_data=self._input(),
            arguments=self._arguments(),
            action=self._action(),
            output=self._output(),
            system_config=self._system_config(),
        )

        tracker.finalize()
        self.assertTrue((self.output_dir / "step_003.png").exists())
        self.assertTrue((self.output_dir / "closed_loop_overview_2001.png").exists())
        self.assertTrue((self.output_dir / "summary_and_predictions.xlsx").exists())

    def test_default_output_dir_uses_edge_execution(self):
        tracker = PumpFlowDmpcExecutionTracker(save_step_plots=False)
        self.assertEqual(
            str(tracker.output_dir).replace("\\", "/"),
            "output/edge_execution",
        )

    def test_create_default_plot_tracker_disabled_by_default(self):
        tracker = create_default_plot_tracker(output_dir=self.output_dir)
        self.assertIsNone(tracker)

    def test_create_default_plot_tracker_returns_tracker_when_enabled(self):
        tracker = create_default_plot_tracker(
            output_dir=self.output_dir,
            enabled=True,
        )
        self.assertIsNotNone(tracker)
        self.assertEqual(
            str(tracker.output_dir).replace("\\", "/"),
            str(self.output_dir).replace("\\", "/"),
        )

    def test_none_tracker_does_not_break_algorithm_solve(self):
        algorithm = PumpStationFlowDmpcAlgorithm(
            solver=StubSolver(),
            resolver=PumpFlowDmpcInputResolver(),
            execution_tracker=None,
        )
        output = algorithm.solve(self._resolver_input())
        self.assertEqual(ControlAlgorithmStatus.CONTINUE, output.status)
        self.assertEqual("request-001", output.request_id)

    def _resolver_input(self):
        return ControlAlgorithmInput(
            schema_version="1.0",
            algorithm_type="pump_station_flow_dmpc",
            algorithm_version="1.8.1",
            control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
            context=ControlAlgorithmContext(
                request_id="request-001",
                context_id="scene-001",
                step_index=3,
                target_object_type="PumpStation",
                target_object_id=2001,
            ),
            signals=[
                ControlSignal(
                    type=SignalType.TARGET,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="water_flow",
                    value=20.5,
                ),
                ControlSignal(
                    type=SignalType.OBSERVATION,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="water_flow",
                    value=18.0,
                ),
                ControlSignal(
                    type=SignalType.OBSERVATION,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="station_memory",
                    attributes={
                        "mode": "ODD2",
                        "last_selected_flow": 18.0,
                        "active_unit_ids": [2101, 2102],
                    },
                ),
                ControlSignal(
                    type=SignalType.REFERENCE,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="station_front_water_level",
                    series=[10.0],
                ),
                ControlSignal(
                    type=SignalType.REFERENCE,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="station_back_water_level",
                    series=[5.0],
                ),
            ],
            actuators=[
                ControlActuator(
                    object_type="Pump",
                    object_id=2101,
                    available=True,
                    values={"blade_angle": 10.0},
                    ranges={
                        "blade_angle": ControlValueRange(
                            min_value=0.0,
                            max_value=40.0,
                        )
                    },
                    attributes={"station_object_id": 2001},
                ),
                ControlActuator(
                    object_type="Pump",
                    object_id=2102,
                    available=True,
                    values={"blade_angle": 12.0},
                    ranges={
                        "blade_angle": ControlValueRange(
                            min_value=0.0,
                            max_value=40.0,
                        )
                    },
                    attributes={"station_object_id": 2001},
                ),
            ],
            parameters={"max_blade_delta_per_step": 5.0},
        )


if __name__ == "__main__":
    unittest.main()
