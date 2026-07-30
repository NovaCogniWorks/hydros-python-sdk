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
