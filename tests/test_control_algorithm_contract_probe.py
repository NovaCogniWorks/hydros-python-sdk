import json
import os
import sys
import threading
import unittest
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.abspath("custom-agent/pump"))

from control_algorithm_contract_probe import ControlAlgorithmContractProbe  # noqa: E402
from control_algorithm_contract_probe_service import (  # noqa: E402
    create_control_algorithm_contract_probe_server,
)
from hydros_agent_sdk import (  # noqa: E402
    ControlAlgorithmContext,
    ControlAlgorithmInput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    ControlTaskType,
)


class ControlAlgorithmContractProbeTest(unittest.TestCase):
    def test_returns_hold_without_computing_or_proposing_actuator_targets(self):
        runtime = ControlAlgorithmRuntime()
        runtime.register(ControlAlgorithmContractProbe())

        output = runtime.solve(
            ControlAlgorithmInput(
                schema_version="1.0",
                algorithm_type="pump_station_flow_dmpc",
                control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
                context=ControlAlgorithmContext(
                    request_id="scene-001:12:2001:pump_station_flow_dmpc",
                    context_id="scene-001",
                    step_index=12,
                    target_object_type="PumpStation",
                    target_object_id=2001,
                ),
            )
        )

        self.assertEqual(ControlAlgorithmStatus.HOLD, output.status)
        self.assertEqual("CONTRACT_PROBE_ONLY", output.reason)
        self.assertEqual([], output.actuator_targets)
        self.assertEqual([], output.results)
        self.assertEqual({}, output.next_state)
        self.assertEqual("dry_run", output.evidence["mode"])
        self.assertEqual("control_contract_probe", output.evidence["implementation"])
        self.assertEqual("pump_station_flow_dmpc", output.evidence["algorithm_type"])

    def test_http_service_accepts_edge_pump_flow_dmpc_endpoint(self):
        server = create_control_algorithm_contract_probe_server(port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            input_data = ControlAlgorithmInput(
                schema_version="1.0",
                algorithm_type="pump_station_flow_dmpc",
                control_task_type=ControlTaskType.STATION_FLOW_ALLOCATION,
                context=ControlAlgorithmContext(
                    request_id="scene-001:12:2001:pump_station_flow_dmpc",
                    context_id="scene-001",
                    step_index=12,
                    target_object_type="PumpStation",
                    target_object_id=2001,
                ),
            )
            endpoint = (
                "http://127.0.0.1:%s/engine/v1/api/control-algorithms/"
                "pump_station_flow_dmpc/solve" % server.server_address[1]
            )
            request = Request(
                endpoint,
                data=json.dumps(input_data.model_dump(mode="json")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(200, response.status)
            self.assertEqual("HOLD", payload["status"])
            self.assertEqual("control_contract_probe", payload["evidence"]["implementation"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
