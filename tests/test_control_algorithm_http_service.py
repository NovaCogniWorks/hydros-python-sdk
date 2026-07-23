import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hydros_agent_sdk import (  # noqa: E402
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    ControlTaskType,
    create_control_algorithm_http_server,
)


class _HoldAlgorithm:
    algorithm_version = "1.0.0"

    def __init__(self, algorithm_type, reason):
        self.algorithm_type = algorithm_type
        self.reason = reason

    def solve(self, input_data):
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.HOLD,
            reason=self.reason,
        )


class ControlAlgorithmHttpServiceTest(unittest.TestCase):
    def setUp(self):
        runtime = ControlAlgorithmRuntime()
        runtime.register(_HoldAlgorithm("hold_algorithm", "NO_CHANGE_REQUIRED"))
        runtime.register(_HoldAlgorithm("alternate_hold_algorithm", "ALTERNATE_HOLD"))
        self.server = create_control_algorithm_http_server(runtime, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = (
            "http://127.0.0.1:%s/engine/v1/api/control-algorithms/"
            "hold_algorithm/solve" % self.server.server_address[1]
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def test_returns_standard_runtime_output(self):
        status, payload = self._post(self.endpoint, self._input().model_dump(mode="json"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "HOLD")
        self.assertEqual(payload["request_id"], "scene-001:12:2001:hold_algorithm")

    def test_routes_multiple_algorithms_through_same_http_service(self):
        endpoint = self._endpoint("alternate_hold_algorithm")

        status, payload = self._post(
            endpoint,
            self._input(algorithm_type="alternate_hold_algorithm").model_dump(mode="json"),
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "HOLD")
        self.assertEqual(payload["reason"], "ALTERNATE_HOLD")

    def test_logs_received_control_algorithm_request_payload(self):
        with self.assertLogs(
            "hydros_agent_sdk.control_algorithms.http_service", level="INFO"
        ) as captured_logs:
            status, _ = self._post(
                self.endpoint,
                self._input().model_dump(mode="json"),
            )

        self.assertEqual(status, 200)
        log_output = "\n".join(captured_logs.output)
        self.assertIn("Control algorithm HTTP request received", log_output)
        self.assertIn('"request_id":"scene-001:12:2001:hold_algorithm"', log_output)
        self.assertIn('"algorithm_type":"hold_algorithm"', log_output)

    def test_runtime_returns_standard_failure_for_unknown_algorithm(self):
        input_data = self._input(algorithm_type="missing")
        endpoint = self.endpoint.replace("hold_algorithm", "missing")

        status, payload = self._post(endpoint, input_data.model_dump(mode="json"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["error_code"], "UNSUPPORTED_ALGORITHM")

    def test_rejects_path_and_body_algorithm_type_mismatch(self):
        with self.assertRaises(HTTPError) as error:
            self._post(self.endpoint, self._input(algorithm_type="other").model_dump(mode="json"))

        self.assertEqual(error.exception.code, 400)
        self.assertEqual(
            json.loads(error.exception.read().decode("utf-8"))["error_code"],
            "ALGORITHM_TYPE_MISMATCH",
        )

    def test_rejects_non_canonical_paths(self):
        for path_prefix in (
            "/engine/v1/api/edge-control",
            "/control-algorithms",
        ):
            endpoint = (
                "http://127.0.0.1:%s%s/hold_algorithm/solve"
                % (self.server.server_address[1], path_prefix)
            )

            with self.assertRaises(HTTPError) as error:
                self._post(endpoint, self._input().model_dump(mode="json"))

            self.assertEqual(error.exception.code, 404)

    def _endpoint(self, algorithm_type):
        return (
            "http://127.0.0.1:%s/engine/v1/api/control-algorithms/%s/solve"
            % (self.server.server_address[1], algorithm_type)
        )

    @staticmethod
    def _post(endpoint, payload):
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _input(algorithm_type="hold_algorithm"):
        return ControlAlgorithmInput(
            schema_version="1.0",
            algorithm_type=algorithm_type,
            control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
            context=ControlAlgorithmContext(
                request_id="scene-001:12:2001:%s" % algorithm_type,
                context_id="scene-001",
                step_index=12,
                target_object_type="PumpStation",
                target_object_id=2001,
            ),
        )


if __name__ == "__main__":
    unittest.main()
