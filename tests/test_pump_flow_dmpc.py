import json
import os
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.abspath("custom-agent/pump"))

from hydros_agent_sdk import (  # noqa: E402
    ControlActuator,
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    ControlSignal,
    ControlTaskType,
    ControlValueRange,
    SignalType,
    create_control_algorithm_http_server,
)
from pump_flow_dmpc import (  # noqa: E402
    PumpFlowCurvePoint,
    PumpFlowDmpcInputResolver,
    PumpFlowDmpcSolver,
    PumpStationFlowDmpcAlgorithm,
    TabulatedPumpPerformanceRepository,
)
from pump_flow_dmpc_service import create_pump_flow_dmpc_server  # noqa: E402


class PumpFlowDmpcTest(unittest.TestCase):
    def setUp(self):
        performance = TabulatedPumpPerformanceRepository(
            {
                (2001, 2101): (
                    PumpFlowCurvePoint(5.0, 0.0, 0.0),
                    PumpFlowCurvePoint(5.0, 20.0, 20.0),
                    PumpFlowCurvePoint(5.0, 40.0, 40.0),
                ),
                (2001, 2102): (
                    PumpFlowCurvePoint(5.0, 0.0, 0.0),
                    PumpFlowCurvePoint(5.0, 20.0, 20.0),
                    PumpFlowCurvePoint(5.0, 40.0, 40.0),
                ),
            }
        )
        self.algorithm = PumpStationFlowDmpcAlgorithm(
            solver=PumpFlowDmpcSolver(performance),
            resolver=PumpFlowDmpcInputResolver(),
        )

    def test_projects_only_blade_angle_candidates_and_flow_result(self):
        output = self.algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))

        self.assertEqual(ControlAlgorithmStatus.CONTINUE, output.status)
        self.assertEqual("request-001", output.request_id)
        self.assertEqual(2, len(output.actuator_targets))
        self.assertTrue(
            all(
                set(target.target_values) == {"blade_angle"}
                for target in output.actuator_targets
            )
        )
        self.assertEqual("water_flow", output.results[0].value_type)
        self.assertLessEqual(output.results[0].value, 30.0)
        self.assertIn("previous_blade_angles", output.next_state)

    def test_completes_without_candidates_when_current_flow_is_within_tolerance(self):
        output = self.algorithm.solve(self._input(target_flow=20.5, current_flow=20.0))

        self.assertEqual(ControlAlgorithmStatus.COMPLETED, output.status)
        self.assertEqual([], output.actuator_targets)
        self.assertEqual("FLOW_TARGET_REACHED", output.reason)

    def test_fails_when_required_head_signal_is_missing(self):
        input_data = self._input(target_flow=30.0, current_flow=20.0)
        input_data.signals = [
            signal for signal in input_data.signals if signal.value_type != "water_head"
        ]

        output = self.algorithm.solve(input_data)

        self.assertEqual(ControlAlgorithmStatus.FAILED, output.status)
        self.assertEqual("MISSING_OR_AMBIGUOUS_SIGNAL", output.error_code)
        self.assertEqual([], output.actuator_targets)

    def test_loads_and_interpolates_tabulated_performance_from_yaml(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = os.path.join(temporary_directory, "pump-performance.yaml")
            with open(config_path, "w", encoding="utf-8") as config_file:
                config_file.write(
                    "stations:\n"
                    "  '2001':\n"
                    "    units:\n"
                    "      '2101':\n"
                    "        curve:\n"
                    "          - {water_head: 4.0, blade_angle: 0.0, water_flow: 0.0}\n"
                    "          - {water_head: 4.0, blade_angle: 20.0, water_flow: 24.0}\n"
                    "          - {water_head: 6.0, blade_angle: 0.0, water_flow: 0.0}\n"
                    "          - {water_head: 6.0, blade_angle: 20.0, water_flow: 16.0}\n"
                )

            performance = TabulatedPumpPerformanceRepository.from_yaml(config_path)

        self.assertEqual(
            10.0,
            performance.predict_unit_flow(
                station_id=2001,
                unit_id=2101,
                blade_angle=10.0,
                water_head=5.0,
            ),
        )

    def test_service_factory_registers_algorithm_from_yaml_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = os.path.join(temporary_directory, "pump-performance.yaml")
            with open(config_path, "w", encoding="utf-8") as config_file:
                config_file.write(
                    "stations:\n"
                    "  '2001':\n"
                    "    units:\n"
                    "      '2101':\n"
                    "        curve:\n"
                    "          - {water_head: 5.0, blade_angle: 0.0, water_flow: 0.0}\n"
                    "          - {water_head: 5.0, blade_angle: 20.0, water_flow: 20.0}\n"
                    "      '2102':\n"
                    "        curve:\n"
                    "          - {water_head: 5.0, blade_angle: 0.0, water_flow: 0.0}\n"
                    "          - {water_head: 5.0, blade_angle: 20.0, water_flow: 20.0}\n"
                )
            server = create_pump_flow_dmpc_server(config_path, port=0)
            try:
                self.assertGreater(server.server_address[1], 0)
            finally:
                server.server_close()

    def test_runtime_and_http_service_return_standard_output(self):
        runtime = ControlAlgorithmRuntime()
        runtime.register(self.algorithm)
        server = create_control_algorithm_http_server(runtime, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = (
                "http://127.0.0.1:%s/engine/v1/api/control-algorithms/"
                "pump_station_flow_dmpc/solve" % server.server_address[1]
            )
            request = Request(
                endpoint,
                data=json.dumps(self._input(34.0, 20.0).model_dump(mode="json")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(200, response.status)
            self.assertEqual("CONTINUE", payload["status"])
            self.assertEqual("request-001", payload["request_id"])
            self.assertEqual({"blade_angle"}, set(payload["actuator_targets"][0]["target_values"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    @staticmethod
    def _input(target_flow, current_flow):
        return ControlAlgorithmInput(
            schema_version="1.0",
            algorithm_type="pump_station_flow_dmpc",
            algorithm_version="1.0.0",
            control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
            context=ControlAlgorithmContext(
                request_id="request-001",
                context_id="scene-001",
                step_index=12,
                target_object_type="PumpStation",
                target_object_id=2001,
            ),
            signals=[
                ControlSignal(
                    type=SignalType.TARGET,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="water_flow",
                    value=target_flow,
                ),
                ControlSignal(
                    type=SignalType.OBSERVATION,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="water_flow",
                    value=current_flow,
                ),
                ControlSignal(
                    type=SignalType.OBSERVATION,
                    object_type="PumpStation",
                    object_id=2001,
                    value_type="water_head",
                    value=5.0,
                ),
            ],
            actuators=[
                ControlActuator(
                    object_type="Pump",
                    object_id=2101,
                    available=True,
                    values={"unit_status": 1.0, "blade_angle": 10.0},
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
                    values={"unit_status": 1.0, "blade_angle": 10.0},
                    ranges={
                        "blade_angle": ControlValueRange(
                            min_value=0.0,
                            max_value=40.0,
                        )
                    },
                    attributes={"station_object_id": 2001},
                ),
            ],
            parameters={
                "flow_tolerance": 1.0,
                "max_blade_delta_per_step": 5.0,
                "candidate_angle_step": 1.0,
                "max_solver_iterations": 4,
                "movement_weight": 0.1,
            },
        )


if __name__ == "__main__":
    unittest.main()
