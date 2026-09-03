import importlib
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _load_power_control_module():
    power_dir = os.path.abspath("custom-agent/power")
    if power_dir not in sys.path:
        sys.path.insert(0, power_dir)
    return importlib.import_module("control_algorithm_service")


def _load_power_control_models():
    return importlib.import_module("hydros_agent_sdk.control_algorithms")


def _load_power_allocation_module():
    power_dir = os.path.abspath("custom-agent/power")
    if power_dir not in sys.path:
        sys.path.insert(0, power_dir)
    return importlib.import_module("allocation")


class PowerAllocationModuleTest(unittest.TestCase):
    def test_v47_allocator_allocates_by_current_power_ratio(self):
        allocation = _load_power_allocation_module()
        allocator = allocation.HydroSimV47PowerAllocator()

        result = allocator.allocate_station(allocation.StationPowerAllocationInput(
            station_id=20300,
            target_output_power=90.0,
            turbines=[
                allocation.TurbinePowerInput(
                    object_id=20301,
                    current_output_power=40.0,
                    min_output_power=0.0,
                    max_output_power=100.0,
                    head=100.0,
                    efficiency=0.9,
                ),
                allocation.TurbinePowerInput(
                    object_id=20302,
                    current_output_power=20.0,
                    min_output_power=0.0,
                    max_output_power=100.0,
                    head=100.0,
                    efficiency=0.9,
                ),
            ],
        ))

        targets = {
            item.object_id: item.target_output_power
            for item in result.turbine_allocations
        }
        self.assertAlmostEqual(60.0, targets[20301])
        self.assertAlmostEqual(30.0, targets[20302])
        self.assertAlmostEqual(90.0, result.allocated_output_power)
        self.assertGreater(result.estimated_water_flow, 0.0)
        self.assertEqual("current_power_ratio", result.evidence["allocation"]["mode"])
        turbine_targets = result.evidence["allocation"]["turbine_targets"]
        self.assertEqual(2, len(turbine_targets))
        self.assertEqual(20301, turbine_targets[0]["object_id"])
        self.assertAlmostEqual(40.0, turbine_targets[0]["current_output_power"])
        self.assertAlmostEqual(60.0, turbine_targets[0]["raw_target_output_power"])
        self.assertAlmostEqual(60.0, turbine_targets[0]["projected_target_output_power"])

    def test_v47_allocator_zero_target_stops_turbines(self):
        allocation = _load_power_allocation_module()
        allocator = allocation.HydroSimV47PowerAllocator()

        result = allocator.allocate_station(allocation.StationPowerAllocationInput(
            station_id=20300,
            target_output_power=0.0,
            turbines=[
                allocation.TurbinePowerInput(
                    object_id=20301,
                    current_output_power=40.0,
                    min_output_power=0.0,
                    max_output_power=100.0,
                )
            ],
        ))

        self.assertAlmostEqual(0.0, result.allocated_output_power)
        self.assertAlmostEqual(0.0, result.turbine_allocations[0].target_output_power)
        self.assertEqual("zero_target", result.evidence["allocation"]["mode"])

    def test_v47_allocator_uses_nhq_parameters_for_flow_estimation(self):
        allocation = _load_power_allocation_module()
        allocator = allocation.HydroSimV47PowerAllocator()

        result = allocator.allocate_station(allocation.StationPowerAllocationInput(
            station_id=20300,
            target_output_power=50.0,
            turbines=[
                allocation.TurbinePowerInput(
                    object_id=20301,
                    current_output_power=0.0,
                    min_output_power=0.0,
                    max_output_power=120.0,
                    head=50.0,
                    design_head=50.0,
                    min_head=30.0,
                    max_head=80.0,
                    design_power=100.0,
                    design_efficiency=0.93,
                )
            ],
        ))

        expected_flow, _ = allocation.HydroNHQGenerator(
            design_head=50.0,
            min_head=30.0,
            max_head=80.0,
            design_power=100.0,
            min_power=1e-6,
            max_power=120.0,
            design_efficiency=0.93,
        ).query(50.0, 50.0)
        self.assertAlmostEqual(expected_flow, result.estimated_water_flow)


class PowerControlAlgorithmServiceTest(unittest.TestCase):
    def test_power_service_defaults_to_remotely_reachable_address(self):
        module = _load_power_control_module()

        with patch.dict(os.environ, {}, clear=True):
            host, port = module.resolve_server_address()

        self.assertEqual("0.0.0.0", host)
        self.assertEqual(8015, port)

    def test_runtime_rejects_station_output_power_target(self):
        module = _load_power_control_module()
        models = _load_power_control_models()
        runtime = module.build_runtime()

        output = runtime.solve(models.ControlAlgorithmInput.model_validate({
            "schema_version": "1.0",
            "algorithm_type": "power_station_edge_control",
            "algorithm_version": "1.0.0",
            "control_task_type": "STATION_FLOW_ALLOCATION",
            "context": {
                "request_id": "request-001",
                "target_object_type": "PowerStation",
                "target_object_id": 20300,
            },
            "signals": [
                {
                    "type": "TARGET",
                    "object_type": "PowerStation",
                    "object_id": 20300,
                    "value_type": "output_power",
                    "value": 90.0,
                }
            ],
            "actuators": [
                {
                    "object_type": "Turbine",
                    "object_id": 20301,
                    "available": True,
                    "values": {"output_power": 40.0},
                    "ranges": {"output_power": {"min_value": 0.0, "max_value": 100.0}},
                    "attributes": {"station_object_id": 20300},
                },
                {
                    "object_type": "Turbine",
                    "object_id": 20302,
                    "available": True,
                    "values": {"output_power": 20.0},
                    "ranges": {"output_power": {"min_value": 0.0, "max_value": 100.0}},
                    "attributes": {"station_object_id": 20300},
                },
            ],
        }))

        self.assertEqual("FAILED", output.status.value)
        self.assertEqual("MISSING_TARGET_SIGNAL", output.error_code)
        self.assertEqual([], output.actuator_targets)

    def test_runtime_allocates_station_output_power_to_turbines(self):
        module = _load_power_control_module()
        models = _load_power_control_models()
        runtime = module.build_runtime()

        output = runtime.solve(models.ControlAlgorithmInput.model_validate({
            "schema_version": "1.0",
            "algorithm_type": "power_station_output_power_allocation",
            "algorithm_version": "1.0.0",
            "control_task_type": "STATION_POWER_ALLOCATION",
            "context": {
                "request_id": "request-power-001",
                "target_object_type": "PowerStation",
                "target_object_id": 20300,
            },
            "signals": [
                {
                    "type": "TARGET",
                    "object_type": "PowerStation",
                    "object_id": 20300,
                    "value_type": "output_power",
                    "value": 90.0,
                }
            ],
            "actuators": [
                {
                    "object_type": "Turbine",
                    "object_id": 20301,
                    "available": True,
                    "values": {"output_power": 40.0},
                    "ranges": {"output_power": {"min_value": 0.0, "max_value": 100.0}},
                    "attributes": {"station_object_id": 20300, "head": 100.0, "efficiency": 0.9},
                },
                {
                    "object_type": "Turbine",
                    "object_id": 20302,
                    "available": True,
                    "values": {"output_power": 20.0},
                    "ranges": {"output_power": {"min_value": 0.0, "max_value": 100.0}},
                    "attributes": {"station_object_id": 20300, "head": 100.0, "efficiency": 0.9},
                },
            ],
        }))

        self.assertEqual("CONTINUE", output.status.value)
        self.assertEqual("TURBINE_POWER_TARGET_ALLOCATED", output.reason)
        targets = {
            item.object_id: item.target_values["output_power"]
            for item in output.actuator_targets
        }
        self.assertAlmostEqual(60.0, targets[20301])
        self.assertAlmostEqual(30.0, targets[20302])
        result_values = {
            item.value_type: item.value
            for item in output.results
        }
        self.assertAlmostEqual(90.0, result_values["output_power"])
        self.assertGreater(result_values["water_flow"], 0.0)

    def test_runtime_reports_output_power_capacity_clipping(self):
        module = _load_power_control_module()
        models = _load_power_control_models()
        runtime = module.build_runtime()

        output = runtime.solve(models.ControlAlgorithmInput.model_validate({
            "schema_version": "1.0",
            "algorithm_type": "power_station_output_power_allocation",
            "algorithm_version": "1.0.0",
            "control_task_type": "STATION_POWER_ALLOCATION",
            "context": {
                "request_id": "request-power-over-capacity",
                "target_object_type": "PowerStation",
                "target_object_id": 20300,
            },
            "signals": [{
                "type": "TARGET",
                "object_type": "PowerStation",
                "object_id": 20300,
                "value_type": "output_power",
                "value": 180.0,
            }],
            "actuators": [
                {
                    "object_type": "Turbine",
                    "object_id": 20301,
                    "available": True,
                    "values": {"output_power": 0.0},
                    "ranges": {"output_power": {"min_value": 0.0, "max_value": 50.0}},
                    "attributes": {"station_object_id": 20300},
                },
                {
                    "object_type": "Turbine",
                    "object_id": 20302,
                    "available": True,
                    "values": {"output_power": 0.0},
                    "ranges": {"output_power": {"min_value": 0.0, "max_value": 70.0}},
                    "attributes": {"station_object_id": 20300},
                },
            ],
        }))

        self.assertEqual("CONTINUE", output.status.value)
        targets = {
            item.object_id: item.target_values["output_power"]
            for item in output.actuator_targets
        }
        self.assertAlmostEqual(50.0, targets[20301])
        self.assertAlmostEqual(70.0, targets[20302])
        station_evidence = output.evidence["stations"][0]
        allocation = station_evidence["allocation"]
        self.assertTrue(allocation["target_exceeds_known_capacity"])
        self.assertAlmostEqual(120.0, allocation["allocated_output_power"])
        self.assertAlmostEqual(60.0, allocation["unallocated_output_power"])
        self.assertEqual(2, len(allocation["clipped"]))
        self.assertTrue(
            all(item["reason"] == "above_upper_bound" for item in allocation["clipped"])
        )

    def test_runtime_marks_feedback_used_from_observation_signals(self):
        module = _load_power_control_module()
        models = _load_power_control_models()
        runtime = module.build_runtime()

        output = runtime.solve(models.ControlAlgorithmInput.model_validate({
            "schema_version": "1.0",
            "algorithm_type": "power_station_output_power_allocation",
            "algorithm_version": "1.0.0",
            "control_task_type": "STATION_POWER_ALLOCATION",
            "context": {
                "request_id": "request-power-feedback",
                "target_object_type": "PowerStation",
                "target_object_id": 20300,
            },
            "signals": [
                {
                    "type": "TARGET",
                    "object_type": "PowerStation",
                    "object_id": 20300,
                    "value_type": "output_power",
                    "value": 90.0,
                },
                {
                    "type": "OBSERVATION",
                    "object_type": "PowerStation",
                    "object_id": 20300,
                    "value_type": "water_level",
                    "value": 612.3,
                    "attributes": {"position_code": "up_stream"},
                },
            ],
            "actuators": [{
                "object_type": "Turbine",
                "object_id": 20301,
                "available": True,
                "values": {"output_power": 40.0},
                "ranges": {"output_power": {"min_value": 0.0, "max_value": 100.0}},
                "attributes": {"station_object_id": 20300, "head": 100.0, "efficiency": 0.9},
            }],
        }))

        station_evidence = output.evidence["stations"][0]
        self.assertTrue(station_evidence["feedback_used"])
        self.assertEqual(1, station_evidence["stage_hint_count"])

    def test_http_service_allocates_station_output_power_to_turbines(self):
        module = _load_power_control_module()
        server = module.create_control_algorithm_http_server(
            module.build_runtime(),
            host="127.0.0.1",
            port=0,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = {
                "schema_version": "1.0",
                "algorithm_type": "power_station_output_power_allocation",
                "algorithm_version": "1.0.0",
                "control_task_type": "STATION_POWER_ALLOCATION",
                "context": {
                    "request_id": "request-power-http-001",
                    "target_object_type": "PowerStation",
                    "target_object_id": 20300,
                },
                "signals": [{
                    "type": "TARGET",
                    "object_type": "PowerStation",
                    "object_id": 20300,
                    "value_type": "output_power",
                    "value": 90.0,
                }],
                "actuators": [{
                    "object_type": "Turbine",
                    "object_id": 20301,
                    "available": True,
                    "values": {"output_power": 40.0},
                    "ranges": {"output_power": {"min_value": 0.0, "max_value": 100.0}},
                    "attributes": {"station_object_id": 20300, "head": 100.0, "efficiency": 0.9},
                }],
            }
            request = Request(
                url=(
                    f"http://127.0.0.1:{server.server_address[1]}"
                    "/engine/v1/api/control-algorithms/power_station_output_power_allocation/solve"
                ),
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
            self.assertEqual("CONTINUE", body["status"])
            self.assertEqual("output_power", next(iter(body["actuator_targets"][0]["target_values"])))
        finally:
            server.shutdown()
            server.server_close()

    def test_http_service_rejects_algorithm_type_mismatch(self):
        module = _load_power_control_module()
        server = module.create_control_algorithm_http_server(
            module.build_runtime(),
            host="127.0.0.1",
            port=0,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = {
                "schema_version": "1.0",
                "algorithm_type": "other_algorithm",
                "algorithm_version": "1.0.0",
                "control_task_type": "STATION_FLOW_ALLOCATION",
                "context": {
                    "request_id": "request-002",
                    "target_object_type": "Station",
                    "target_object_id": 20300,
                },
                "signals": [],
                "actuators": [],
            }
            request = Request(
                url=(
                    f"http://127.0.0.1:{server.server_address[1]}"
                    "/engine/v1/api/control-algorithms/power_station_edge_control/solve"
                ),
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as error_ctx:
                urlopen(request, timeout=5)
            self.assertEqual(400, error_ctx.exception.code)
        finally:
            server.shutdown()
            server.server_close()

    def test_runtime_allocates_station_water_flow_to_turbines(self):
        module = _load_power_control_module()
        models = _load_power_control_models()
        runtime = module.build_runtime()

        output = runtime.solve(models.ControlAlgorithmInput.model_validate({
            "schema_version": "1.0",
            "algorithm_type": "power_station_edge_control",
            "control_task_type": "STATION_FLOW_ALLOCATION",
            "context": {
                "request_id": "request-flow-001",
                "target_object_type": "PowerStation",
                "target_object_id": 20100,
            },
            "signals": [{
                "type": "TARGET",
                "object_type": "PowerStation",
                "object_id": 20100,
                "value_type": "water_flow",
                "value": 600.0,
            }],
            "actuators": [
                {
                    "object_type": "Turbine",
                    "object_id": 20104,
                    "available": True,
                    "values": {"water_flow": 200.0},
                    "ranges": {"water_flow": {"min_value": 0.0, "max_value": 600.0}},
                    "attributes": {"station_object_id": 20100},
                },
                {
                    "object_type": "Turbine",
                    "object_id": 20105,
                    "available": True,
                    "values": {"water_flow": 100.0},
                    "ranges": {"water_flow": {"min_value": 0.0, "max_value": 600.0}},
                    "attributes": {"station_object_id": 20100},
                },
            ],
        }))

        self.assertEqual("CONTINUE", output.status.value)
        self.assertEqual("TURBINE_FLOW_TARGET_ALLOCATED", output.reason)
        targets = {
            item.object_id: item.target_values["water_flow"]
            for item in output.actuator_targets
        }
        self.assertAlmostEqual(400.0, targets[20104])
        self.assertAlmostEqual(200.0, targets[20105])

    def test_runtime_honors_edge_max_adjustment_delta(self):
        module = _load_power_control_module()
        models = _load_power_control_models()
        runtime = module.build_runtime()

        output = runtime.solve(models.ControlAlgorithmInput.model_validate({
            "schema_version": "1.0",
            "algorithm_type": "power_station_edge_control",
            "control_task_type": "STATION_FLOW_ALLOCATION",
            "context": {
                "request_id": "request-flow-safety-001",
                "target_object_type": "PowerStation",
                "target_object_id": 20100,
            },
            "signals": [{
                "type": "TARGET",
                "object_type": "PowerStation",
                "object_id": 20100,
                "value_type": "water_flow",
                "value": 600.0,
            }],
            "actuators": [{
                "object_type": "Turbine",
                "object_id": 20104,
                "available": True,
                "values": {"water_flow": 0.0},
                "ranges": {"water_flow": {"min_value": 0.0, "max_value": 600.0}},
                "attributes": {"station_object_id": 20100},
            }],
            "parameters": {"max_adjustment_delta": 25.0},
        }))

        self.assertEqual("CONTINUE", output.status.value)
        self.assertAlmostEqual(25.0, output.actuator_targets[0].target_values["water_flow"])

    def test_runtime_rejects_legacy_station_water_flow_target(self):
        module = _load_power_control_module()
        models = _load_power_control_models()
        runtime = module.build_runtime()

        output = runtime.solve(models.ControlAlgorithmInput.model_validate({
            "schema_version": "1.0",
            "algorithm_type": "power_station_edge_control",
            "control_task_type": "STATION_FLOW_ALLOCATION",
            "context": {
                "request_id": "request-legacy-station-001",
                "target_object_type": "Station",
                "target_object_id": 20100,
            },
            "signals": [{
                "type": "TARGET",
                "object_type": "Station",
                "object_id": 20100,
                "value_type": "water_flow",
                "value": 600.0,
            }],
            "actuators": [],
        }))

        self.assertEqual("FAILED", output.status.value)
        self.assertEqual("MISSING_TARGET_SIGNAL", output.error_code)


if __name__ == "__main__":
    unittest.main()
