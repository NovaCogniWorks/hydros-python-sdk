from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent
from hydros_agent_sdk.protocol.models import ObjectTimeSeries, TimeSeriesValue

from .models import MpcOptimizeRequest, MpcOptimizeResponse, SensorData

if TYPE_CHECKING:
    from hydros_agent_sdk.agents.central_scheduling_agent import MpcTaskState

logger = logging.getLogger(__name__)


class MpcPlanningError(RuntimeError):
    """Raised when the MPC planning service cannot produce usable results."""


class MpcPlanningClient:
    """HTTP client and request builder for the strategy-planning MPC API."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 180.0,
        opener: Optional[Callable[[Request, float], Any]] = None,
        require_sensor_data: bool = True,
        empty_sensor_retry_delay_seconds: float = 2.0,
        empty_sensor_retry_count: int = 1,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._opener = opener or self._default_opener
        self.require_sensor_data = require_sensor_data
        self.empty_sensor_retry_delay_seconds = empty_sensor_retry_delay_seconds
        self.empty_sensor_retry_count = empty_sensor_retry_count

    @property
    def planning_start_url(self) -> str:
        return self.base_url

    def execute_optimization(
        self,
        mpc_task_state: "MpcTaskState",
        sensor_data: Iterable[SensorData | Dict[str, Any]],
        sensor_provider: Optional[Callable[[], Iterable[SensorData | Dict[str, Any]]]] = None,
    ) -> List[MpcOptimizeResponse]:
        normalized_sensor_data = self._normalize_sensor_data(sensor_data)
        logger.info(
            "MPC optimization sensorData before request build: bizSceneInstanceId=%s, "
            "step=%s, sensorDataCount=%s",
            mpc_task_state.context.biz_scene_instance_id,
            mpc_task_state.current_step,
            len(normalized_sensor_data),
        )
        request_model = self.build_optimize_request(
            mpc_task_state,
            normalized_sensor_data,
            sensor_provider=sensor_provider,
        )
        request_payload = request_model.model_dump(mode="json", by_alias=True, exclude_none=True)
        request_payload_text = self._format_json_for_log(request_payload)
        body = request_payload_text.encode("utf-8")
        request = Request(
            self.planning_start_url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        try:
            logger.info(
                "Sending MPC optimization request: bizSceneInstanceId=%s, step=%s, url=%s",
                mpc_task_state.context.biz_scene_instance_id,
                mpc_task_state.current_step,
                self.planning_start_url,
            )
            logger.info("MPC optimization request payload: %s", request_payload_text)
            response = self._opener(request, self.timeout_seconds)
            payload_bytes = response.read()
            raw_payload_text = payload_bytes.decode("utf-8", errors="replace")
            logger.info("MPC optimization raw response: %s", raw_payload_text)
        except HTTPError as exc:
            logger.error(
                "MPC planning service returned HTTP %s, response=%s",
                exc.code,
                self._read_http_error_body(exc),
            )
            raise MpcPlanningError(f"MPC planning service returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise MpcPlanningError(f"MPC planning service is unreachable: {exc.reason}") from exc
        except Exception as exc:
            raise MpcPlanningError(f"MPC planning request failed: {exc}") from exc

        try:
            payload = json.loads(raw_payload_text)
        except Exception as exc:
            raise MpcPlanningError("MPC planning service returned invalid JSON") from exc

        responses = self.parse_optimize_response(payload)
        logger.info(
            "MPC optimization parsed response: %s",
            self._format_json_for_log([
                item.model_dump(mode="json", by_alias=True, exclude_none=True)
                for item in responses
            ]),
        )
        return responses

    def build_optimize_request(
        self,
        mpc_task_state: "MpcTaskState",
        sensor_data: Iterable[SensorData | Dict[str, Any]],
        sensor_provider: Optional[Callable[[], Iterable[SensorData | Dict[str, Any]]]] = None,
    ) -> MpcOptimizeRequest:
        normalized_sensor_data = self._normalize_sensor_data(sensor_data)
        if self.require_sensor_data and not normalized_sensor_data:
            logger.warning(
                "MPC sensorData is empty before retry: bizSceneInstanceId=%s, step=%s",
                mpc_task_state.context.biz_scene_instance_id,
                mpc_task_state.current_step,
            )
            normalized_sensor_data = self._retry_sensor_data(sensor_provider)
            logger.info(
                "MPC sensorData after retry: bizSceneInstanceId=%s, step=%s, sensorDataCount=%s",
                mpc_task_state.context.biz_scene_instance_id,
                mpc_task_state.current_step,
                len(normalized_sensor_data),
            )
        if self.require_sensor_data and not normalized_sensor_data:
            logger.error(
                "MPC sensorData is empty; request will not be sent: bizSceneInstanceId=%s, step=%s",
                mpc_task_state.context.biz_scene_instance_id,
                mpc_task_state.current_step,
            )
            raise MpcPlanningError("MPC optimization requires non-empty sensor data")

        targets = self.build_targets(mpc_task_state.hydro_events)
        return MpcOptimizeRequest(
            biz_scene_instance_id=mpc_task_state.context.biz_scene_instance_id,
            step_index=mpc_task_state.current_step,
            mpc_config_url=mpc_task_state.mpc_config_url,
            control_config_url=mpc_task_state.target_and_constrain_config_url,
            upstream_boundaries=self.build_lateral_inflow_boundaries(
                mpc_task_state.hydro_events,
                mpc_task_state.current_step,
            ),
            sensor_data=normalized_sensor_data,
            fixed_controls=self.build_fixed_controls(mpc_task_state.hydro_events),
            targets=targets,
            include_diversion=bool(targets),
        )

    @staticmethod
    def parse_optimize_response(payload: Any) -> List[MpcOptimizeResponse]:
        if payload is None:
            raise MpcPlanningError("MPC planning service returned empty response")

        data = payload
        if isinstance(payload, dict):
            failed = payload.get("failure") or payload.get("failed")
            success = payload.get("success")
            if failed or success is False:
                raise MpcPlanningError(f"MPC planning service returned failure: {payload}")
            data = payload.get("data")

        if data is None:
            return []
        if not isinstance(data, list):
            raise MpcPlanningError("MPC planning service response data must be a list")
        return [MpcOptimizeResponse.model_validate(item) for item in data]

    @classmethod
    def build_lateral_inflow_boundaries(
        cls,
        events: Iterable[TimeSeriesDataChangedEvent],
        current_step: int,
    ) -> Dict[str, List[float]]:
        boundaries: Dict[str, List[float]] = {}
        for event in events or []:
            for object_time_series in event.object_time_series or []:
                values = cls.collect_values_with_interpolation(object_time_series, current_step)
                if values and object_time_series.object_id is not None:
                    boundaries[str(object_time_series.object_id)] = values
        return boundaries

    @classmethod
    def collect_values_with_interpolation(
        cls,
        object_time_series: ObjectTimeSeries,
        current_step: int,
    ) -> List[float]:
        series = sorted(
            [item for item in object_time_series.time_series if item.step is not None and item.value is not None],
            key=lambda item: item.step,
        )
        if not series:
            return []

        min_step = series[0].step
        if min_step is None or current_step < min_step:
            logger.warning(
                "Object %s (%s) time series starts after current step: minStep=%s, currentStep=%s",
                object_time_series.object_name,
                object_time_series.object_id,
                min_step,
                current_step,
            )
            return []

        prev_value = cls._find_prev_value(series, current_step)
        next_value = cls._find_next_value(series, current_step)
        if prev_value is None:
            return []

        if prev_value.step == current_step:
            return cls._collect_values_from_start(series, prev_value.step)

        if next_value is None:
            return []

        prev_step = prev_value.step
        next_step = next_value.step
        if prev_step is None or next_step is None or next_step == prev_step:
            return []

        ratio = (current_step - prev_step) / (next_step - prev_step)
        interpolated_value = float(prev_value.value) + (float(next_value.value) - float(prev_value.value)) * ratio
        return [interpolated_value] + cls._collect_values_from_start(series, next_step)

    @staticmethod
    def build_fixed_controls(events: Iterable[TimeSeriesDataChangedEvent]) -> Dict[str, float]:
        fixed_controls: Dict[str, float] = {}
        for event in events or []:
            if event.hydro_event_source_type != "DEVICE_FAULT":
                continue
            for object_time_series in event.object_time_series or []:
                if object_time_series.object_id is not None:
                    fixed_controls[str(object_time_series.object_id)] = 0.0
        return fixed_controls

    @staticmethod
    def build_targets(events: Iterable[TimeSeriesDataChangedEvent]) -> Dict[int, List[float]]:
        targets: Dict[int, List[float]] = {}
        for event in events or []:
            if event.hydro_event_source_type != "WATER_USE":
                continue
            for object_time_series in event.object_time_series or []:
                if object_time_series.object_id is None:
                    continue
                values = [
                    float(item.value)
                    for item in object_time_series.time_series
                    if item.value is not None
                ]
                if values:
                    targets[int(object_time_series.object_id)] = values
        return targets

    @staticmethod
    def _find_prev_value(
        series: List[TimeSeriesValue],
        current_step: int,
    ) -> Optional[TimeSeriesValue]:
        candidates = [item for item in series if item.step is not None and item.step <= current_step]
        return candidates[-1] if candidates else None

    @staticmethod
    def _find_next_value(
        series: List[TimeSeriesValue],
        current_step: int,
    ) -> Optional[TimeSeriesValue]:
        candidates = [item for item in series if item.step is not None and item.step > current_step]
        return candidates[0] if candidates else None

    @staticmethod
    def _collect_values_from_start(series: List[TimeSeriesValue], start_step: int) -> List[float]:
        return [
            float(item.value)
            for item in series
            if item.step is not None and item.step >= start_step and item.value is not None
        ]

    def _retry_sensor_data(
        self,
        sensor_provider: Optional[Callable[[], Iterable[SensorData | Dict[str, Any]]]],
    ) -> List[SensorData]:
        if sensor_provider is None:
            return []
        sensor_data: List[SensorData] = []
        for _ in range(self.empty_sensor_retry_count):
            time.sleep(self.empty_sensor_retry_delay_seconds)
            sensor_data = self._normalize_sensor_data(sensor_provider())
            if sensor_data:
                return sensor_data
        return sensor_data

    @staticmethod
    def _normalize_sensor_data(sensor_data: Iterable[SensorData | Dict[str, Any]]) -> List[SensorData]:
        normalized: List[SensorData] = []
        for item in sensor_data or []:
            normalized.append(item if isinstance(item, SensorData) else SensorData.model_validate(item))
        return normalized

    @staticmethod
    def _default_opener(request: Request, timeout_seconds: float) -> Any:
        return urlopen(request, timeout=timeout_seconds)

    @staticmethod
    def _format_json_for_log(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _read_http_error_body(exc: HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")
        except Exception:
            return ""
