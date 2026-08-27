import json
import os
from pathlib import Path
import pickle
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

import pandas as pd

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
from pump_flow_dmpc.types import PumpFlowDmpcArguments  # noqa: E402
from pump_flow_dmpc.odd_dmpc.flow_service import FlowDepartService  # noqa: E402
from pump_flow_dmpc.odd_dmpc.local_controller import LocalController  # noqa: E402
from pump_flow_dmpc.odd_dmpc.pump_unit import PumpUnit  # noqa: E402
from pump_flow_dmpc.odd_dmpc.station_model import PumpStationModel  # noqa: E402
from pump_flow_dmpc_service import (  # noqa: E402
    PumpFlowDmpcHttpHost,
    create_pump_flow_dmpc_server,
)
from pump_flow_dmpc.odd_dmpc.types import ControlAction  # noqa: E402


class StubPumpFlowDmpcSolver:
    """Return a deterministic ODD-DMPC action without loading project data."""

    def solve(self, arguments):
        selected_flow = min(arguments.reference_flow[0], 30.0)
        return ControlAction(
            station_id=arguments.station_id,
            mode=arguments.mode,
            selected_flow=selected_flow,
            unit_status=dict(arguments.unit_status),
            unit_openings={
                unit_id: min(opening + 5.0, 40.0)
                for unit_id, opening in arguments.unit_openings.items()
            },
            unit_flows={
                unit_id: selected_flow / 2
                for unit_id in arguments.unit_openings
            },
            fit_score=0.95,
            objective=1.0,
            predicted_flow_error=selected_flow - arguments.reference_flow[0],
            predicted_level_error=0.0,
            predicted_back_level=5.0,
            predicted_front_level=10.0,
            predicted_head=5.0,
        )


class PumpFlowDmpcTest(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._prev_step_cache_dir = os.environ.get(
            "HYDROS_PUMP_FLOW_DMPC_STEP_CACHE_DIR"
        )
        os.environ["HYDROS_PUMP_FLOW_DMPC_STEP_CACHE_DIR"] = self._temp_dir.name
        self.algorithm = PumpStationFlowDmpcAlgorithm(
            solver=StubPumpFlowDmpcSolver(),
            resolver=PumpFlowDmpcInputResolver(),
        )

    def tearDown(self):
        if self._prev_step_cache_dir is None:
            os.environ.pop("HYDROS_PUMP_FLOW_DMPC_STEP_CACHE_DIR", None)
        else:
            os.environ["HYDROS_PUMP_FLOW_DMPC_STEP_CACHE_DIR"] = (
                self._prev_step_cache_dir
            )
        self._temp_dir.cleanup()

    def _cache_algorithm(self, solver):
        return PumpStationFlowDmpcAlgorithm(
            solver=solver,
            resolver=PumpFlowDmpcInputResolver(),
            cache_dir=Path(self._temp_dir.name) / "cache",
        )

    def _counted_solver(self):
        stub = StubPumpFlowDmpcSolver()
        solver = Mock(wraps=stub)
        solver.solve.side_effect = stub.solve
        return solver

    @staticmethod
    def _set_main_step_index(input_data, value):
        for signal in input_data.signals:
            if signal.value_type == "station_memory":
                signal.attributes = dict(signal.attributes)
                if value is None:
                    signal.attributes.pop("main_step_index", None)
                else:
                    signal.attributes["main_step_index"] = value
                return
        raise AssertionError("station_memory signal not found")

    def test_same_upper_step_is_computed_once_and_cached(self):
        solver = self._counted_solver()
        algorithm = self._cache_algorithm(solver)

        first = algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))
        second = algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))

        self.assertEqual(ControlAlgorithmStatus.CONTINUE, first.status)
        self.assertEqual(first.actuator_targets, second.actuator_targets)
        solver.solve.assert_called_once()
        cache_file = Path(self._temp_dir.name) / "cache" / "scene_001" / "step_000012.json"
        self.assertTrue(cache_file.exists())

    def test_cache_hit_remaps_request_id(self):
        solver = self._counted_solver()
        algorithm = self._cache_algorithm(solver)

        algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))
        input_data = self._input(target_flow=34.0, current_flow=20.0)
        input_data.context = input_data.context.model_copy(
            update={"request_id": "request-002"}
        )
        second = algorithm.solve(input_data)

        self.assertEqual("request-002", second.request_id)
        solver.solve.assert_called_once()

    def test_new_upper_step_triggers_recompute(self):
        solver = self._counted_solver()
        algorithm = self._cache_algorithm(solver)

        algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))
        input_data = self._input(target_flow=34.0, current_flow=20.0)
        self._set_main_step_index(input_data, 13)
        algorithm.solve(input_data)

        self.assertEqual(2, solver.solve.call_count)

    def test_missing_main_step_index_always_recomputes(self):
        solver = self._counted_solver()
        algorithm = self._cache_algorithm(solver)

        input_data = self._input(target_flow=34.0, current_flow=20.0)
        self._set_main_step_index(input_data, None)
        algorithm.solve(input_data)
        algorithm.solve(input_data)

        self.assertEqual(2, solver.solve.call_count)

    def test_failed_solve_is_not_cached(self):
        failing = PumpFlowDmpcSolver()
        algorithm = self._cache_algorithm(failing)

        first = algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))
        self.assertEqual(ControlAlgorithmStatus.FAILED, first.status)
        cache_root = Path(self._temp_dir.name) / "cache"
        self.assertFalse(any(cache_root.rglob("*.json")))

    @staticmethod
    def _three_unit_station():
        return SimpleNamespace(
            id=2001,
            name="Station1",
            unit_name_by_id={2101: "Pump1", 2102: "Pump2", 2103: "Pump3"},
        )

    @staticmethod
    def _flow_depart_table(specifications):
        unit_names = {2101: "Pump1", 2102: "Pump2", 2103: "Pump3"}
        rows = []
        for specification in specifications:
            row = {
                "总流量(m³/s)": specification["total_flow"],
                "扬程(m)": 5.0,
                "平均效率(%)": specification["efficiency"],
            }
            for unit_id, unit_name in unit_names.items():
                running = int(specification["statuses"].get(unit_id, 0)) == 1
                prefix = f"泵_{unit_name}"
                row[f"{prefix}_状态"] = "true" if running else "false"
                row[f"{prefix}_流量"] = specification["flows"].get(unit_id, 0.0)
                row[f"{prefix}_开度"] = -0.3 if running else 0.0
            rows.append(row)
        return pd.DataFrame(rows)

    def test_projects_available_and_running_blade_angle_candidates(self):
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
        self.assertTrue(all(target.available for target in output.actuator_targets))
        self.assertEqual("water_flow", output.results[0].value_type)
        self.assertLessEqual(output.results[0].value, 30.0)
        self.assertIn("unit_openings", output.next_state)

    def test_projects_solver_mode_and_selected_flow_into_next_state(self):
        output = self.algorithm.solve(self._input(target_flow=20.5, current_flow=20.0))

        self.assertEqual(ControlAlgorithmStatus.CONTINUE, output.status)
        self.assertEqual("ODD2", output.next_state["mode"])
        self.assertEqual(20.5, output.next_state["selected_flow"])

    def test_resolver_uses_all_edge_actuators_and_edge_current_facts(self):
        input_data = self._input(target_flow=64.0, current_flow=32.0)
        station_memory = next(
            signal
            for signal in input_data.signals
            if signal.value_type == "station_memory"
        )
        station_memory.attributes["active_unit_ids"] = [2101]
        input_data.signals.append(
            ControlSignal(
                type=SignalType.OBSERVATION,
                object_type="PUMP",
                object_id=2102,
                value_type="unit_memory",
                attributes={
                    "unit_status": 0,
                    "unit_opening": 100.0,
                    "time_since_adjust": 7,
                    "time_since_switch": 8,
                },
            )
        )

        arguments = PumpFlowDmpcInputResolver().resolve(input_data)

        self.assertEqual([2101, 2102], arguments.available_unit_ids)
        self.assertEqual([2101, 2102], arguments.active_unit_ids)
        self.assertEqual(1, arguments.unit_status[2102])
        self.assertEqual(10.0, arguments.unit_openings[2102])
        self.assertEqual((0.0, 40.0), arguments.unit_blade_bounds[2102])
        self.assertEqual(7, arguments.time_since_adjust[2102])
        self.assertEqual(5.0, arguments.max_blade_delta_per_step)

    def test_resolver_reads_nested_algorithm_params_for_lower_controller(self):
        input_data = self._input(target_flow=64.0, current_flow=32.0)
        input_data.parameters = {
            "algorithm_params": {
                "lower_controller": {
                    "max_blade_delta_per_step": 200.0,
                },
            },
        }

        arguments = PumpFlowDmpcInputResolver().resolve(input_data)

        self.assertEqual(200.0, arguments.max_blade_delta_per_step)
        self.assertEqual(
            {"lower_controller": {"max_blade_delta_per_step": 200.0}},
            arguments.algorithm_params,
        )

    def test_projects_stopped_unit_as_unavailable_without_blade_angle(self):
        input_data = self._input(target_flow=34.0, current_flow=20.0)
        input_data.actuators[1].status = "OFF"

        output = self.algorithm.solve(input_data)

        self.assertEqual(ControlAlgorithmStatus.CONTINUE, output.status)
        targets_by_unit = {target.object_id: target for target in output.actuator_targets}
        self.assertEqual({2101, 2102}, set(targets_by_unit))
        self.assertFalse(targets_by_unit[2102].available)
        self.assertEqual({}, targets_by_unit[2102].target_values)
        self.assertTrue(targets_by_unit[2101].available)
        self.assertIn("blade_angle", targets_by_unit[2101].target_values)

    def test_resolver_does_not_revive_stopped_actuator_from_stale_memory(self):
        input_data = self._input(target_flow=64.0, current_flow=32.0)
        input_data.actuators[1].status = "OFF"
        input_data.signals.append(
            ControlSignal(
                type=SignalType.OBSERVATION,
                object_type="PUMP",
                object_id=2102,
                value_type="unit_memory",
                attributes={
                    "unit_status": 1,
                    "unit_opening": -1.99,
                    "time_since_adjust": 0,
                    "time_since_switch": 999,
                },
            )
        )

        arguments = PumpFlowDmpcInputResolver().resolve(input_data)

        self.assertEqual([2101], arguments.active_unit_ids)
        self.assertEqual(0, arguments.unit_status[2102])
        self.assertEqual(0.0, arguments.unit_openings[2102])

    def test_resolver_skips_unavailable_actuator_from_candidate_pool(self):
        input_data = self._input(target_flow=64.0, current_flow=32.0)
        input_data.actuators[1].available = False

        arguments = PumpFlowDmpcInputResolver().resolve(input_data)

        self.assertEqual([2101], arguments.available_unit_ids)
        self.assertEqual([2101], arguments.active_unit_ids)
        self.assertNotIn(2102, arguments.unit_status)
        self.assertNotIn(2102, arguments.unit_openings)

    def test_single_step_optimizer_honors_maximum_blade_delta(self):
        unit_model = SimpleNamespace(
            angle_min=0.0,
            angle_max=40.0,
            h_min=1.0,
            h_max=10.0,
            q_min=0.0,
            q_max=40.0,
            predict_flow=lambda *, blade_angle, water_head: blade_angle,
            predict_efficiency=lambda flow, head: 80.0,
            is_feasible=lambda flow, head: True,
        )
        controller = LocalController(
            system_config=SimpleNamespace(),
            runtime=SimpleNamespace(),
            flow_service=Mock(),
        )

        result = controller._optimize_single_step(
            active_unit_ids=[2101],
            unit_models={2101: unit_model},
            head=5.0,
            target_flow=30.0,
            initial_openings={2101: 10.0},
            max_opening_delta=2.0,
        )

        self.assertIsNotNone(result)
        self.assertLessEqual(abs(result["openings"][2101] - 10.0), 2.0 + 1.0e-9)

    def test_single_step_optimizer_intersects_model_and_actuator_blade_bounds(self):
        unit_model = SimpleNamespace(
            angle_min=0.0,
            angle_max=40.0,
            h_min=1.0,
            h_max=10.0,
            q_min=0.0,
            q_max=40.0,
            predict_flow=lambda *, blade_angle, water_head: blade_angle,
            predict_efficiency=lambda flow, head: 80.0,
            is_feasible=lambda flow, head: True,
        )
        controller = LocalController(
            system_config=SimpleNamespace(),
            runtime=SimpleNamespace(),
            flow_service=Mock(),
        )

        result = controller._optimize_single_step(
            active_unit_ids=[2101],
            unit_models={2101: unit_model},
            head=5.0,
            target_flow=30.0,
            initial_openings={2101: 10.0},
            blade_angle_bounds={2101: (0.0, 11.0)},
        )

        self.assertIsNotNone(result)
        self.assertLessEqual(result["openings"][2101], 11.0)

    def test_single_step_optimizer_rejects_head_outside_unit_model(self):
        unit_model = SimpleNamespace(
            angle_min=-7.0,
            angle_max=5.0,
            h_min=0.5,
            h_max=5.1,
            q_min=14.0,
            q_max=39.0,
            predict_flow=Mock(),
            predict_efficiency=Mock(),
            is_feasible=Mock(),
        )
        controller = LocalController(
            system_config=SimpleNamespace(),
            runtime=SimpleNamespace(),
            flow_service=Mock(),
        )

        result = controller._optimize_single_step(
            active_unit_ids=[2101],
            unit_models={2101: unit_model},
            head=6.0,
            target_flow=30.0,
            initial_openings={2101: 0.0},
        )

        self.assertIsNone(result)
        unit_model.predict_flow.assert_not_called()

    def test_pump_unit_inverts_blade_angle_and_head_to_constrained_flow(self):
        efficiency = pd.DataFrame(
            [
                [10.0, 1.0, 80.0],
                [20.0, 1.0, 80.0],
                [10.0, 2.0, 80.0],
                [20.0, 2.0, 80.0],
            ],
            columns=["Q", "H", "E"],
        )
        opening = pd.DataFrame(
            [
                [10.0, 1.0, -5.0],
                [20.0, 1.0, 5.0],
                [10.0, 2.0, -5.0],
                [20.0, 2.0, 5.0],
            ],
            columns=["Q", "H", "R"],
        )
        unit = PumpUnit("Pump1", efficiency, opening)

        flow = unit.predict_flow(blade_angle=0.0, water_head=1.5)

        self.assertAlmostEqual(15.0, flow, places=3)

    def test_odd3_enumerates_all_available_unit_combinations(self):
        controller = LocalController(
            system_config=SimpleNamespace(),
            runtime=SimpleNamespace(),
            flow_service=Mock(),
        )

        self.assertEqual(
            [[2101], [2102], [2101, 2102]],
            controller._candidate_active_sets(
                mode="ODD3",
                available_unit_ids=[2101, 2102],
                current_active_unit_ids=[2102],
            ),
        )

    def test_odd3_uses_online_nlp_and_selects_two_units_for_target_64(self):
        unit_model = SimpleNamespace(
            angle_min=-7.0,
            angle_max=5.0,
            h_min=0.5,
            h_max=5.1,
            q_min=14.0,
            q_max=39.0,
            predict_flow=lambda *, blade_angle, water_head: 32.0 + float(blade_angle),
            predict_efficiency=lambda flow, head: 80.0,
            is_feasible=lambda flow, head: True,
        )
        flow_service = Mock()
        flow_service.get_unit_model.return_value = unit_model
        controller = LocalController(
            system_config=SimpleNamespace(),
            runtime=SimpleNamespace(
                control_horizon_lower=1,
                opening_change_threshold=0.0,
                lower_flow_weight=3.0,
                lower_adjust_count_weight=0.0,
                lower_switch_weight=0.0,
            ),
            flow_service=flow_service,
        )
        station_ctx = SimpleNamespace(
            station_id=2001,
            station_model=Mock(),
            available_unit_ids=[2101, 2102],
            max_blade_delta_per_step=float("inf"),
        )
        transfer_bundle = SimpleNamespace(
            reference_flow=[64.0],
            reference_head=[5.0],
            reference_back_level=[10.0],
            reference_front_level=[5.0],
        )
        station_memory = SimpleNamespace(
            active_unit_ids=[2102],
            unit_openings={2101: 0.0, 2102: 0.0},
            unit_status={2101: 0, 2102: 1},
            time_since_switch={2101: 999, 2102: 999},
        )

        action = controller.solve(
            mode="ODD3",
            station_ctx=station_ctx,
            upstream_prediction={},
            disturbance_forecast={},
            transfer_bundle=transfer_bundle,
            station_memory=station_memory,
        )

        self.assertEqual({2101: 1, 2102: 1}, action.unit_status)
        self.assertAlmostEqual(64.0, action.selected_flow, places=6)
        self.assertAlmostEqual(64.0, sum(action.unit_flows.values()), places=6)
        # 流量/扬程预筛后，只有 [2101, 2102] 能命中 64 m³/s；
        # 单机组合被筛掉，不再进入在线 NLP。
        self.assertEqual(1, len(action.candidate_plans))

    def test_station_model_rejects_superset_row_with_unavailable_active_unit(self):
        table = self._flow_depart_table(
            [
                {
                    "total_flow": 64.0,
                    "efficiency": 90.0,
                    "statuses": {2101: 1, 2102: 0, 2103: 1},
                    "flows": {2101: 32.0, 2102: 0.0, 2103: 32.0},
                },
                {
                    "total_flow": 64.0,
                    "efficiency": 80.0,
                    "statuses": {2101: 1, 2102: 1, 2103: 0},
                    "flows": {2101: 32.0, 2102: 32.0, 2103: 0.0},
                },
            ]
        )
        model = PumpStationModel(self._three_unit_station(), table)

        selected = model.best_row_for_target(
            target_flow=64.0,
            head=5.0,
            available_unit_ids=[2101, 2102],
        )

        self.assertIsNotNone(selected)
        self.assertEqual({2101: 1, 2102: 1}, selected.unit_status)
        self.assertEqual(64.0, sum(selected.unit_flows.values()))

    def test_station_model_rejects_row_with_inconsistent_total_flow(self):
        table = self._flow_depart_table(
            [
                {
                    "total_flow": 64.0,
                    "efficiency": 90.0,
                    "statuses": {2101: 1, 2102: 1, 2103: 0},
                    "flows": {2101: 16.0, 2102: 16.0, 2103: 0.0},
                }
            ]
        )
        model = PumpStationModel(self._three_unit_station(), table)

        self.assertEqual(
            [],
            model.candidate_rows(
                head=5.0,
                available_unit_ids=[2101, 2102],
            ),
        )
        self.assertEqual((0.0, 0.0), model.global_feasible_flow_range([2101, 2102]))

    def test_fails_when_target_flow_is_missing(self):
        input_data = self._input(target_flow=30.0, current_flow=20.0)
        input_data.signals = [
            signal
            for signal in input_data.signals
            if not (
                signal.type == SignalType.TARGET
                and signal.value_type == "water_flow"
            )
        ]

        output = self.algorithm.solve(input_data)

        self.assertEqual(ControlAlgorithmStatus.FAILED, output.status)
        self.assertEqual("MISSING_TARGET_FLOW", output.error_code)
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

    def test_service_factory_registers_algorithm_without_eager_config_loading(self):
        server = create_pump_flow_dmpc_server(port=0)
        try:
            self.assertGreater(server.server_address[1], 0)
        finally:
            server.server_close()

    def test_solver_reports_missing_runtime_config_deterministically(self):
        algorithm = PumpStationFlowDmpcAlgorithm(
            solver=PumpFlowDmpcSolver(),
            resolver=PumpFlowDmpcInputResolver(),
        )

        with self.assertLogs("pump_flow_dmpc.algorithm", level="ERROR") as captured_logs:
            output = algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))

        self.assertEqual(ControlAlgorithmStatus.FAILED, output.status)
        self.assertEqual("CONFIG_NOT_FOUND", output.error_code)
        self.assertEqual([], output.actuator_targets)
        self.assertEqual(1, len(captured_logs.records))
        self.assertIsNotNone(captured_logs.records[0].exc_info)
        formatted_log = captured_logs.output[0]
        self.assertIn("algorithmClass=PumpStationFlowDmpcAlgorithm", formatted_log)
        self.assertIn("errorCode=CONFIG_NOT_FOUND", formatted_log)
        self.assertIn(
            "exceptionClass=pump_flow_dmpc.solver.PumpFlowDmpcSolver",
            formatted_log,
        )
        self.assertIn("exceptionFunction=_load_config_payload", formatted_log)
        self.assertIn("PumpFlowDmpcError", formatted_log)
        self.assertIn("pump_flow_dmpc/solver.py", formatted_log)

    def test_solver_reports_target_station_missing_from_loaded_config(self):
        solver = PumpFlowDmpcSolver()
        solver._system_config = SimpleNamespace(station_by_id={1: object()})
        solver._loaded_config_source = ""
        solver._flow_service = Mock()
        solver._local_controller = Mock()
        algorithm = PumpStationFlowDmpcAlgorithm(
            solver=solver,
            resolver=PumpFlowDmpcInputResolver(),
        )

        output = algorithm.solve(self._input(target_flow=34.0, current_flow=20.0))

        self.assertEqual(ControlAlgorithmStatus.FAILED, output.status)
        self.assertEqual("TARGET_STATION_NOT_CONFIGURED", output.error_code)
        self.assertIn("target station 2001", output.error_message)
        solver._flow_service.get_station_model.assert_not_called()

    def test_solver_loads_remote_runtime_config_from_url(self):
        solver = PumpFlowDmpcSolver()
        expected_payload = {"stations": [{"id": 20000}]}

        with patch(
            "pump_flow_dmpc.solver.YamlLoader.from_url",
            return_value=expected_payload,
        ) as load_from_url:
            payload = solver._load_config_payload("https://config.example/mpc.yaml")

        self.assertIs(expected_payload, payload)
        load_from_url.assert_called_once_with("https://config.example/mpc.yaml")

    def test_solver_local_runtime_config_contains_deployed_station_id(self):
        solver = PumpFlowDmpcSolver()
        config_path = os.path.abspath("custom-agent/pump/data/mpc_config.yaml")

        with tempfile.TemporaryDirectory() as temporary_directory, patch.object(
            solver,
            "_resolve_flow_depart_cache_dir",
            return_value=Path(temporary_directory),
        ):
            solver._ensure_loaded(
                PumpFlowDmpcArguments(
                    station_id=20000,
                    mode="ODD2",
                    config_path=config_path,
                )
            )

        self.assertIn(20000, solver._system_config.station_by_id)
        self.assertEqual(config_path, solver._loaded_config_source)
        self.assertFalse(solver._flow_service.generation_enabled)

    def test_solver_uses_algorithm_params_without_loading_config_url(self):
        solver = PumpFlowDmpcSolver()

        with tempfile.TemporaryDirectory() as temporary_directory, patch.object(
            solver,
            "_resolve_flow_depart_cache_dir",
            return_value=Path(temporary_directory),
        ), patch.object(
            solver,
            "_load_config_payload",
            side_effect=AssertionError("must not load runtime YAML"),
        ):
            solver._ensure_loaded(
                PumpFlowDmpcArguments(
                    station_id=20000,
                    mode="ODD2",
                    config_path="https://config.example/mpc.yaml",
                    reference_flow=[50.0],
                    algorithm_params={
                        "odd": {
                            "odd1_flow_tolerance": 4.0,
                            "odd1_level_tolerance": 0.15,
                            "odd3_flow_tolerance": 8.0,
                            "odd3_level_tolerance": 0.8,
                        },
                        "lower_controller": {
                            "control_horizon_lower": 10,
                            "lower_flow_weight": 4.0,
                            "lower_level_weight": 2.5,
                            "lower_switch_weight": 0.0,
                            "lower_adjust_count_weight": 0.0,
                            "max_blade_delta_per_step": 200.0,
                        },
                    },
                )
            )

        self.assertIn(20000, solver._system_config.station_by_id)
        self.assertEqual(4.0, solver._runtime.odd1_flow_tolerance)
        self.assertEqual(4.0, solver._runtime.lower_flow_weight)
        self.assertTrue(solver._loaded_config_source.startswith("parameters.algorithm_params:"))

    def test_edge_flow_service_never_generates_missing_offline_table(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = FlowDepartService(
                system_config=SimpleNamespace(source_config_path="unused.yaml"),
                cache_dir=temporary_directory,
                generation_enabled=False,
            )
            with patch(
                "pump_flow_dmpc.odd_dmpc.flow_service.generate_flow_depart"
            ) as generate:
                with self.assertRaisesRegex(
                    FileNotFoundError,
                    r"station 20000.*available units \(20005,\)",
                ):
                    service.get_optimal_table(20000, [20005])

        generate.assert_not_called()

    def test_edge_flow_service_reads_precomputed_table_from_file(self):
        expected = pd.DataFrame({"total_flow": [20.0], "head": [3.0]})
        cache_key = (20000, (20005,))
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "flow_depart_cache.pkl"
            with cache_path.open("wb") as cache_file:
                pickle.dump({cache_key: expected}, cache_file)
            service = FlowDepartService(
                system_config=SimpleNamespace(source_config_path="unused.yaml"),
                cache_dir=temporary_directory,
                generation_enabled=False,
            )

            with patch(
                "pump_flow_dmpc.odd_dmpc.flow_service.generate_flow_depart"
            ) as generate:
                loaded_count = service.load_flow_depart_cache()
                actual = service.get_optimal_table(20000, [20005])

        self.assertEqual(1, loaded_count)
        pd.testing.assert_frame_equal(expected, actual)
        generate.assert_not_called()

    def test_edge_flow_service_rejects_cached_superset_for_exact_unit_set(self):
        full_station_table = pd.DataFrame({"table": ["all-five-units"]})
        smaller_superset_table = pd.DataFrame({"table": ["three-units"]})
        cache = {
            (20000, (20001, 20002, 20003, 20004, 20005)): full_station_table,
            (20000, (20003, 20004, 20005)): smaller_superset_table,
            (20300, (20301, 20302)): pd.DataFrame({"table": ["other-station"]}),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "flow_depart_cache.pkl"
            with cache_path.open("wb") as cache_file:
                pickle.dump(cache, cache_file)
            service = FlowDepartService(
                system_config=SimpleNamespace(source_config_path="unused.yaml"),
                cache_dir=temporary_directory,
                generation_enabled=False,
            )

            with patch(
                "pump_flow_dmpc.odd_dmpc.flow_service.generate_flow_depart"
            ) as generate:
                service.load_flow_depart_cache()
                with self.assertRaisesRegex(
                    FileNotFoundError,
                    r"station 20000.*available units \(20003, 20005\)",
                ):
                    service.get_optimal_table(20000, [20003, 20005])

        generate.assert_not_called()

    def test_station_model_is_built_from_exact_cached_table(self):
        exact_table = pd.DataFrame({"table": ["two-units"]})
        superset_table = pd.DataFrame({"table": ["all-five-units"]})
        station = SimpleNamespace(id=20000)
        service = FlowDepartService(
            system_config=SimpleNamespace(
                source_config_path="unused.yaml",
                station_by_id={20000: station},
            ),
            generation_enabled=False,
            _cache={
                (20000, (20003, 20005)): exact_table,
                (20000, (20001, 20002, 20003, 20004, 20005)): superset_table,
            },
        )
        expected_model = object()

        with patch(
            "pump_flow_dmpc.odd_dmpc.flow_service.PumpStationModel",
            return_value=expected_model,
        ) as station_model:
            actual = service.get_station_model(20000, [20003, 20005])

        self.assertIs(expected_model, actual)
        station_model.assert_called_once()
        self.assertIs(station, station_model.call_args.args[0])
        pd.testing.assert_frame_equal(exact_table, station_model.call_args.args[1])

    def test_solver_does_not_query_offline_flow_depart_table(self):
        solver = PumpFlowDmpcSolver()
        solver._system_config = SimpleNamespace(station_by_id={2001: object()})
        solver._loaded_config_source = ""
        solver._flow_service = Mock()
        solver._local_controller = Mock()
        input_data = self._input(target_flow=34.0, current_flow=20.0)
        arguments = PumpFlowDmpcInputResolver().resolve(input_data)
        solver._local_controller.solve.return_value = StubPumpFlowDmpcSolver().solve(arguments)
        algorithm = PumpStationFlowDmpcAlgorithm(
            solver=solver,
            resolver=PumpFlowDmpcInputResolver(),
        )

        output = algorithm.solve(input_data)

        self.assertEqual(ControlAlgorithmStatus.CONTINUE, output.status)
        solver._flow_service.get_station_model.assert_not_called()
        solver._local_controller.solve.assert_called_once()

    def test_managed_http_host_starts_and_stops_on_dynamic_port(self):
        host = PumpFlowDmpcHttpHost(host="127.0.0.1", port=0)

        host.start()
        try:
            self.assertIsNotNone(host.server_address)
            self.assertGreater(host.server_address[1], 0)
        finally:
            host.stop()

        self.assertIsNone(host.server_address)

    def test_managed_http_host_returns_missing_request_config_failure(self):
        host = PumpFlowDmpcHttpHost(host="127.0.0.1", port=0)
        host.start()
        try:
            endpoint = (
                "http://127.0.0.1:%s/engine/v1/api/control-algorithms/"
                "pump_station_flow_dmpc/solve" % host.server_address[1]
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
            self.assertEqual("FAILED", payload["status"])
            self.assertEqual("CONFIG_NOT_FOUND", payload["error_code"])
            self.assertEqual([], payload["actuator_targets"])
        finally:
            host.stop()

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
            self.assertEqual(
                {"blade_angle"},
                set(payload["actuator_targets"][0]["target_values"]),
            )
            self.assertTrue(payload["actuator_targets"][0]["available"])
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
                    value_type="station_memory",
                    attributes={
                        "mode": "ODD2",
                        "last_selected_flow": current_flow,
                        "active_unit_ids": [2101, 2102],
                        "main_step_index": 12,
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
                    values={"blade_angle": 10.0},
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


    def test_solve_aggregates_all_pump_station_decisions(self):
        input_data = self._multi_station_input()
        output = self.algorithm.solve(input_data)

        self.assertEqual(ControlAlgorithmStatus.CONTINUE, output.status)
        self.assertEqual(3, output.evidence["station_count"])
        self.assertEqual([20000, 20300, 20600], output.evidence["station_ids"])
        self.assertEqual(
            {20000, 20300, 20600},
            {
                result.object_id
                for result in output.results
                if result.value_type == "water_flow"
            },
        )
        self.assertEqual(
            {20000, 20300, 20600},
            {int(station_id) for station_id in output.next_state["stations"]},
        )
        self.assertEqual(
            {20001, 20301, 20601},
            {target.object_id for target in output.actuator_targets},
        )

    @staticmethod
    def _station_pump_input(station_id, unit_id, target_flow, current_flow):
        signals = [
            ControlSignal(
                type=SignalType.TARGET,
                object_type="PumpStation",
                object_id=station_id,
                value_type="water_flow",
                value=target_flow,
            ),
            ControlSignal(
                type=SignalType.OBSERVATION,
                object_type="PumpStation",
                object_id=station_id,
                value_type="water_flow",
                value=current_flow,
            ),
            ControlSignal(
                type=SignalType.OBSERVATION,
                object_type="PumpStation",
                object_id=station_id,
                value_type="station_memory",
                attributes={"mode": "ODD2", "last_selected_flow": current_flow},
            ),
            ControlSignal(
                type=SignalType.REFERENCE,
                object_type="PumpStation",
                object_id=station_id,
                value_type="station_front_water_level",
                series=[10.0],
            ),
            ControlSignal(
                type=SignalType.REFERENCE,
                object_type="PumpStation",
                object_id=station_id,
                value_type="station_back_water_level",
                series=[5.0],
            ),
        ]
        actuators = [
            ControlActuator(
                object_type="Pump",
                object_id=unit_id,
                available=True,
                values={"blade_angle": 10.0},
                ranges={
                    "blade_angle": ControlValueRange(
                        min_value=0.0,
                        max_value=40.0,
                    )
                },
                attributes={"station_object_id": station_id},
            )
        ]
        return signals, actuators

    @staticmethod
    def _multi_station_input():
        stations = [
            (20000, 20001, 50.0, 20.0),
            (20300, 20301, 46.0, 21.0),
            (20600, 20601, 53.0, 22.0),
        ]
        signals = []
        actuators = []
        for station_id, unit_id, target_flow, current_flow in stations:
            station_signals, station_actuators = PumpFlowDmpcTest._station_pump_input(
                station_id,
                unit_id,
                target_flow,
                current_flow,
            )
            signals.extend(station_signals)
            actuators.extend(station_actuators)

        return ControlAlgorithmInput(
            schema_version="1.0",
            algorithm_type="pump_station_flow_dmpc",
            algorithm_version="1.0.0",
            control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
            context=ControlAlgorithmContext(
                request_id="request-multi",
                context_id="scene-multi",
                step_index=1,
                target_object_type="PumpStation",
                target_object_id=20000,
            ),
            signals=signals,
            actuators=actuators,
            parameters={
                "flow_tolerance": 1.0,
                "max_blade_delta_per_step": 5.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
