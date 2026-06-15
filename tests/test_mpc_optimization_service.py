import unittest
from types import SimpleNamespace

from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache
from hydros_agent_sdk.mpc.models import MpcOptimizeResponse, SensorData
from hydros_agent_sdk.mpc.optimization_service import MpcOptimizationService
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.protocol.models import SimulationContext


class FakeMpcPlanningClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def execute_optimization(self, mpc_task_state, sensor_data, sensor_provider=None):
        self.calls.append(
            {
                "state": mpc_task_state,
                "sensor_data": list(sensor_data),
                "sensor_provider": sensor_provider,
            }
        )
        return self.responses


class FakeMpcResultReporter:
    def __init__(self):
        self.published = []

    def publish(self, source_agent_instance, mpc_task_state, responses):
        self.published.append(
            {
                "source": source_agent_instance,
                "state": mpc_task_state,
                "responses": list(responses),
            }
        )


class MpcOptimizationServiceTest(unittest.TestCase):
    def test_creates_planning_client_with_configured_timeout(self):
        service = MpcOptimizationService(
            properties=AgentProperties(
                {
                    "mpc_service_base_url": "http://mpc.local/hydros/api/v1/mpc/planning/start",
                    "mpc_request_timeout_seconds": "75",
                }
            ),
            metrics_data_cache=FieldMetricsCache(max_steps=3),
        )

        client = service.get_or_create_mpc_planning_client()

        self.assertIsNotNone(client)
        self.assertEqual(client.base_url, "http://mpc.local/hydros/api/v1/mpc/planning/start")
        self.assertEqual(client.timeout_seconds, 75.0)

    def test_optimizes_with_cache_sensor_data_and_reports_responses(self):
        context = SimulationContext(biz_scene_instance_id="scene-service")
        source = SimpleNamespace(context=context)
        state = MpcTaskState(context=context, rolling_interval_steps=3, start_step=1, current_step=4)
        cache = FieldMetricsCache(max_steps=3)
        cache.update(
            {
                "object_id": 1001,
                "metrics_code": "water_level",
                "value": 12.5,
                "step_index": 4,
                "position_code": "none",
            }
        )
        response = MpcOptimizeResponse(plan_type="OPTIMAL")
        mpc_client = FakeMpcPlanningClient([response])
        reporter = FakeMpcResultReporter()
        service = MpcOptimizationService(
            properties=AgentProperties(),
            metrics_data_cache=cache,
            mpc_planning_client=mpc_client,
            mpc_result_reporter=reporter,
        )

        responses = service.optimize(source, state, step=4)

        self.assertEqual(responses, [response])
        self.assertEqual(len(mpc_client.calls), 1)
        self.assertEqual(mpc_client.calls[0]["sensor_data"][0].object_id, 1001)
        self.assertEqual(reporter.published[0]["source"], source)
        self.assertEqual(reporter.published[0]["responses"], [response])

    def test_uses_injected_sensor_provider(self):
        context = SimulationContext(biz_scene_instance_id="scene-provider")
        source = SimpleNamespace(context=context)
        state = MpcTaskState(context=context, rolling_interval_steps=3, start_step=1, current_step=4)
        mpc_client = FakeMpcPlanningClient([MpcOptimizeResponse(plan_type="OPTIMAL")])
        service = MpcOptimizationService(
            properties=AgentProperties(),
            metrics_data_cache=FieldMetricsCache(max_steps=3),
            mpc_planning_client=mpc_client,
            mpc_result_reporter=FakeMpcResultReporter(),
            mpc_sensor_provider=lambda agent, task_state: [
                SensorData(object_id=2001, metrics_code="flow", value=3.5, step_index=task_state.current_step)
            ],
        )

        sensor_data = service.list_sensor_data(source, state)

        self.assertEqual(len(sensor_data), 1)
        self.assertEqual(sensor_data[0].object_id, 2001)
        self.assertEqual(sensor_data[0].step_index, 4)


if __name__ == "__main__":
    unittest.main()
