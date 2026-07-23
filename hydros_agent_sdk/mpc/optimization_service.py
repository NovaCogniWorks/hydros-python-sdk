"""默认 MPC 优化工作流服务。"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional

from hydros_agent_sdk.agent_properties import AgentProperties
from hydros_agent_sdk.field_metrics_cache import FieldMetricsCache
from hydros_agent_sdk.mpc.client import MpcPlanningClient
from hydros_agent_sdk.mpc.config import MpcConfigResolver
from hydros_agent_sdk.mpc.models import MpcOptimizeResponse
from hydros_agent_sdk.mpc.mpc_prediction_result_reporter import MpcPredictionResultReporter
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.sensor_data import SensorData

logger = logging.getLogger(__name__)


class MpcOptimizationService:
    """运行 SDK 默认的 MPC 规划和结果上报工作流。"""

    def __init__(
        self,
        properties: AgentProperties,
        metrics_data_cache: FieldMetricsCache,
        configured_mpc_service_base_url: Optional[str] = None,
        configured_mpc_request_timeout_seconds: Optional[float] = None,
        mpc_planning_client: Optional[MpcPlanningClient] = None,
        mpc_prediction_result_reporter: Optional[MpcPredictionResultReporter] = None,
        mpc_sensor_provider: Optional[Callable[..., Iterable[SensorData | Dict[str, Any]]]] = None,
    ):
        self.properties = properties
        self.metrics_data_cache = metrics_data_cache
        self.configured_mpc_service_base_url = configured_mpc_service_base_url
        self.configured_mpc_request_timeout_seconds = configured_mpc_request_timeout_seconds
        self.mpc_planning_client = mpc_planning_client
        self.mpc_prediction_result_reporter = mpc_prediction_result_reporter or MpcPredictionResultReporter()
        self.mpc_sensor_provider = mpc_sensor_provider

    def get_or_create_mpc_planning_client(self) -> Optional[MpcPlanningClient]:
        if self.mpc_planning_client is not None:
            return self.mpc_planning_client

        mpc_config = MpcConfigResolver.resolve(
            self.properties,
            configured_mpc_service_base_url=self.configured_mpc_service_base_url,
            configured_mpc_request_timeout_seconds=self.configured_mpc_request_timeout_seconds,
        )
        base_url = mpc_config.mpc_service_base_url
        if not base_url:
            return None
        self.mpc_planning_client = MpcPlanningClient(
            base_url=base_url,
            timeout_seconds=mpc_config.mpc_request_timeout_seconds,
        )
        return self.mpc_planning_client

    def list_sensor_data(
        self,
        source_agent_instance: Any,
        mpc_task_state: Optional[MpcTaskState] = None,
    ) -> List[SensorData]:
        if self.mpc_sensor_provider is not None:
            provided = self._call_sensor_provider(source_agent_instance, mpc_task_state)
            return [
                item if isinstance(item, SensorData) else SensorData.model_validate(item)
                for item in (provided or [])
            ]

        return self.metrics_data_cache.to_sensor_data()

    def optimize(
        self,
        source_agent_instance: Any,
        mpc_task_state: MpcTaskState,
        step: int,
    ) -> Optional[List[MpcOptimizeResponse]]:
        mpc_client = self.get_or_create_mpc_planning_client()
        if mpc_client is None:
            logger.warning(
                "MPC planning client is not configured; skip default optimization at step %s",
                step,
            )
            return None

        sensor_data = self.list_sensor_data(source_agent_instance, mpc_task_state)
        logger.debug(
            "MPC sensorData prepared: bizSceneInstanceId=%s, step=%s, sensorDataCount=%s",
            source_agent_instance.context.biz_scene_instance_id,
            step,
            len(sensor_data),
        )
        if not sensor_data:
            logger.warning(
                "MPC sensorData is empty before optimization: bizSceneInstanceId=%s, "
                "step=%s, fieldMetricsCacheSize=%s",
                source_agent_instance.context.biz_scene_instance_id,
                step,
                len(self.metrics_data_cache.latest_metrics),
            )

        responses = mpc_client.execute_optimization(
            mpc_task_state,
            sensor_data,
            sensor_provider=lambda: self.list_sensor_data(source_agent_instance, mpc_task_state),
        )
        if not responses:
            return None

        self.mpc_prediction_result_reporter.publish(source_agent_instance, mpc_task_state, responses)
        return responses

    def _call_sensor_provider(
        self,
        source_agent_instance: Any,
        mpc_task_state: Optional[MpcTaskState],
    ) -> Iterable[SensorData | Dict[str, Any]]:
        provider = self.mpc_sensor_provider
        if provider is None:
            return []
        try:
            signature = inspect.signature(provider)
            if len(signature.parameters) >= 2:
                return provider(source_agent_instance, mpc_task_state)
            if len(signature.parameters) == 1:
                return provider(mpc_task_state)
            return provider()
        except (TypeError, ValueError):
            return provider()
