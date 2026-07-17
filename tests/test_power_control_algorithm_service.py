import importlib
import json
import os
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _load_power_control_module():
    power_dir = os.path.abspath("custom-agent/power")
    if power_dir not in sys.path:
        sys.path.insert(0, power_dir)
    return importlib.import_module("control_algorithm_service")


def _load_power_control_models():
    power_dir = os.path.abspath("custom-agent/power")
    if power_dir not in sys.path:
        sys.path.insert(0, power_dir)
    return importlib.import_module("edge_control.models")


class PowerControlAlgorithmServiceTest(unittest.TestCase):
    def test_runtime_allocates_station_output_power_to_turbines(self):
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
                "target_object_type": "Station",
                "target_object_id": 20300,
            },
            "signals": [
                {
                    "type": "TARGET",
                    "object_type": "Station",
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

        self.assertEqual("CONTINUE", output.status.value)
        target_map = {
            item.object_id: item.target_values["output_power"]
            for item in output.actuator_targets
        }
        self.assertAlmostEqual(60.0, target_map[20301])
        self.assertAlmostEqual(30.0, target_map[20302])

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
                    "/control-algorithms/power_station_edge_control/solve"
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


if __name__ == "__main__":
    unittest.main()
