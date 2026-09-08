from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

SOURCE_TIMESTAMP_FIELDS = (
    "source_timestamp_ms",
    "sourceTimestampMs",
    "timestamp",
    "sample_time",
    "event_time",
    "time",
)

GATE_STATION_OBJECT_TYPE = "gatestation"
WATER_LEVEL_METRICS_CODE = "water_level"
UPSTREAM_POSITION_CODE = "up_stream"


@dataclass(frozen=True)
class StationStageObservation:
    value: float
    metric_ref: Dict[str, Any]


@dataclass
class PowerObservationResult:
    step_index: int
    metrics_scope: str
    metrics_count: int
    stage_hints: List[Dict[str, Any]] = field(default_factory=list)
    station_output_power_by_station: Dict[int, float] = field(default_factory=dict)
    predicted_output_power_by_station: Dict[int, float] = field(default_factory=dict)
    prediction_error_by_station: Dict[int, float] = field(default_factory=dict)
    environment_observations: List[Dict[str, Any]] = field(default_factory=list)
    missing_observed_stage_station_ids: List[int] = field(default_factory=list)
    missing_critical_fields: List[str] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)

    @property
    def observed_stage_count(self) -> int:
        return sum(
            1
            for hint in self.stage_hints
            if hint.get("stage_hints_source") == "observation_adapter"
        )

    @property
    def fallback_stage_count(self) -> int:
        return sum(
            1
            for hint in self.stage_hints
            if hint.get("stage_hints_source") != "observation_adapter"
        )

    @property
    def should_apply_to_runtime(self) -> bool:
        return self.observed_stage_count > 0 and bool(self.stage_hints)

    @property
    def observation_quality(self) -> str:
        if self.observed_stage_count <= 0:
            return "internal_reservoir_fallback"
        if self.fallback_stage_count > 0:
            return "mixed_observation_internal_fallback"
        return "closed_loop_observation"


class PowerObservationAdapter:
    """Build Power-specific observations from the full FieldMetricsCache."""

    def __init__(
        self,
        *,
        metrics_data_cache: Any,
        station_node_ids: Iterable[int],
        flow_configs: Iterable[Mapping[str, Any]],
    ) -> None:
        self._metrics_data_cache = metrics_data_cache
        self._station_node_ids = [int(item) for item in station_node_ids]
        self._flow_configs = [dict(item) for item in flow_configs]

    def build(
        self,
        *,
        step_index: int,
        session: Any,
        internal_stage_hints: Optional[List[Dict[str, Any]]] = None,
    ) -> PowerObservationResult:
        metrics_scope, metrics_by_key = self._metrics_for_step_or_latest(step_index)
        metrics = list(metrics_by_key.values())
        device_station_map = self._build_device_station_map(session)
        station_output_power = self._aggregate_turbine_output_power(metrics, device_station_map)
        predicted_station_output_power = self._resolve_predicted_station_output_power(
            session,
            step_index,
        )
        prediction_error = self._build_prediction_error(
            observed_values=station_output_power,
            predicted_values=predicted_station_output_power,
        )
        station_power_outflow = self._aggregate_device_port_flow(
            metrics,
            device_station_map,
            object_type="Turbine",
        )
        station_spill_outflow = self._aggregate_device_port_flow(
            metrics,
            device_station_map,
            object_type="Gate",
        )
        metric_refs_by_station = self._collect_metric_refs_by_station(metrics, device_station_map)
        step_runtime = getattr(session, "step_runtime", None)

        stage_hints: List[Dict[str, Any]] = []
        environment_observations: List[Dict[str, Any]] = []
        diagnostics: List[str] = []
        missing_observed_stage_station_ids: List[int] = []
        missing_critical_fields: List[str] = []
        fallback_hints = list(internal_stage_hints or [])
        previous_power_outflow: Optional[float] = None
        previous_spill_outflow: Optional[float] = None
        previous_total_release: Optional[float] = None
        for station_index, station_id in enumerate(self._station_node_ids):
            flow_config = self._flow_configs[station_index] if station_index < len(self._flow_configs) else {}
            fallback_hint = fallback_hints[station_index] if station_index < len(fallback_hints) else {}
            stage_observation = self._resolve_station_stage(metrics, station_id)
            design_stage = self._resolve_float(
                fallback_hint.get("design_stage"),
                flow_config.get("design_stage"),
            )
            if stage_observation is not None:
                hint = self._build_observed_stage_hint(
                    station_id=station_id,
                    station_name=str(flow_config.get("Name") or fallback_hint.get("station") or station_id),
                    stage_observation=stage_observation,
                    design_stage=design_stage,
                    power_outflow=station_power_outflow.get(station_id),
                    spill_outflow=station_spill_outflow.get(station_id),
                    output_power=station_output_power.get(station_id),
                    predicted_output_power=predicted_station_output_power.get(station_id),
                    prediction_error=prediction_error.get(station_id),
                    internal_hint=fallback_hint,
                    upstream_release=previous_total_release,
                    upstream_power_outflow=previous_power_outflow,
                    upstream_spill_outflow=previous_spill_outflow,
                )
            else:
                hint = dict(fallback_hint)
                hint.setdefault("station", str(flow_config.get("Name") or station_id))
                hint.setdefault("station_id", station_id)
                hint["stage_hints_source"] = "internal_reservoir_fallback"
                hint["fallback_reason"] = "missing_station_stage_observation"
                if hint.get("inflow_m3s") is not None:
                    hint["inflow_source"] = "v47_river_array_internal_state"
                if hint.get("upstream_release_m3s") is not None:
                    hint["upstream_release_source"] = "v47_river_array_internal_state"
                diagnostics.append(f"station:{station_id}:missing_stage_observation")
                missing_observed_stage_station_ids.append(int(station_id))
                missing_critical_fields.append(f"{station_id}:stage")

            if station_power_outflow.get(station_id) is not None:
                hint["power_outflow_m3s"] = float(station_power_outflow[station_id])
            if station_spill_outflow.get(station_id) is not None:
                hint["spill_outflow_m3s"] = float(station_spill_outflow[station_id])
            if station_output_power.get(station_id) is not None:
                hint["output_power_mw"] = float(station_output_power[station_id])
            if predicted_station_output_power.get(station_id) is not None:
                hint["predicted_output_power_mw"] = float(predicted_station_output_power[station_id])
            if prediction_error.get(station_id) is not None:
                hint["prediction_error_mw"] = float(prediction_error[station_id])
            if previous_total_release is not None:
                hint["upstream_release_m3s"] = float(previous_total_release)
                hint["upstream_release_source"] = "ontology_actual_device_outflows"
            if previous_power_outflow is not None:
                hint["upstream_power_outflow_m3s"] = float(previous_power_outflow)
            if previous_spill_outflow is not None:
                hint["upstream_spill_outflow_m3s"] = float(previous_spill_outflow)
            if hint.get("inflow_source") is not None:
                hint["inflow_source_step"] = int(step_index)
            if hint.get("upstream_release_source") is not None:
                hint["upstream_release_source_step"] = int(step_index)

            current_power_outflow = station_power_outflow.get(station_id)
            current_spill_outflow = station_spill_outflow.get(station_id)
            total_release = self._sum_complete_release(
                current_power_outflow,
                current_spill_outflow,
            )
            environment_observations.append(
                self._build_environment_observation(
                    step_index=step_index,
                    station_id=station_id,
                    station_name=str(flow_config.get("Name") or fallback_hint.get("station") or station_id),
                    hint=hint,
                    target_stage=self._resolve_target_stage(step_runtime, station_id, step_index),
                    power_outflow=station_power_outflow.get(station_id),
                    spill_outflow=station_spill_outflow.get(station_id),
                    total_release=total_release,
                    output_power=station_output_power.get(station_id),
                    predicted_output_power=predicted_station_output_power.get(station_id),
                    prediction_error=prediction_error.get(station_id),
                    metric_refs=metric_refs_by_station.get(station_id, []),
                )
            )
            previous_power_outflow = current_power_outflow
            previous_spill_outflow = current_spill_outflow
            previous_total_release = total_release
            stage_hints.append(hint)

        return PowerObservationResult(
            step_index=int(step_index),
            metrics_scope=metrics_scope,
            metrics_count=len(metrics),
            stage_hints=stage_hints,
            station_output_power_by_station=station_output_power,
            predicted_output_power_by_station=predicted_station_output_power,
            prediction_error_by_station=prediction_error,
            environment_observations=environment_observations,
            missing_observed_stage_station_ids=missing_observed_stage_station_ids,
            missing_critical_fields=missing_critical_fields,
            diagnostics=diagnostics,
        )

    def _metrics_for_step_or_latest(self, step_index: int) -> tuple[str, Dict[str, Dict[str, Any]]]:
        by_step = self._metrics_data_cache.by_step(int(step_index))
        if by_step:
            return "step", by_step
        return "latest", dict(getattr(self._metrics_data_cache, "latest_metrics", {}) or {})

    def _build_device_station_map(self, session: Any) -> Dict[int, int]:
        mapping: Dict[int, int] = {}
        for device in getattr(session, "latest_device_output_series", []) or []:
            if device.get("object_id") is None or device.get("node_id") is None:
                continue
            mapping[int(device["object_id"])] = int(device["node_id"])

        step_runtime = getattr(session, "step_runtime", None)
        for item in getattr(step_runtime, "control_domains", []) or []:
            if item.get("device_id") is None or item.get("node_id") is None:
                continue
            mapping[int(item["device_id"])] = int(item["node_id"])
        return mapping

    def _resolve_predicted_station_output_power(
        self,
        session: Any,
        step_index: int,
    ) -> Dict[int, float]:
        result: Dict[int, float] = {}
        for station in getattr(session, "latest_station_power_series", []) or []:
            metrics_code = station.get("metrics_code")
            if metrics_code is not None and str(metrics_code).lower() != "output_power":
                continue
            object_type = station.get("object_type")
            if object_type is not None and str(object_type).lower() not in {"station", "powerstation"}:
                continue
            station_id = self._normalize_int(station.get("node_id", station.get("object_id")))
            if station_id is None:
                continue
            value = self._series_value_for_step(station.get("time_series", []), step_index)
            if value is not None:
                result[station_id] = value

        step_runtime = getattr(session, "step_runtime", None)
        for station_id, series in (getattr(step_runtime, "station_power_plan", {}) or {}).items():
            normalized_station_id = self._normalize_int(station_id)
            if normalized_station_id is None or normalized_station_id in result:
                continue
            value = self._series_value_for_step(series, step_index)
            if value is not None:
                result[normalized_station_id] = value
        return result

    def _build_prediction_error(
        self,
        *,
        observed_values: Mapping[int, float],
        predicted_values: Mapping[int, float],
    ) -> Dict[int, float]:
        result: Dict[int, float] = {}
        for station_id, observed_value in observed_values.items():
            predicted_value = predicted_values.get(station_id)
            if predicted_value is None:
                continue
            result[int(station_id)] = float(observed_value) - float(predicted_value)
        return result

    def _aggregate_turbine_output_power(
        self,
        metrics: List[Dict[str, Any]],
        device_station_map: Mapping[int, int],
    ) -> Dict[int, float]:
        result: Dict[int, float] = {}
        for item in metrics:
            if str(item.get("object_type") or "").lower() != "turbine":
                continue
            if str(item.get("metrics_code") or "").lower() != "output_power":
                continue
            object_id = self._normalize_int(item.get("object_id"))
            value = self._normalize_float(item.get("value"))
            if object_id is None or value is None:
                continue
            station_id = device_station_map.get(object_id)
            if station_id is None:
                continue
            result[station_id] = result.get(station_id, 0.0) + value
        return result

    def _aggregate_device_port_flow(
        self,
        metrics: List[Dict[str, Any]],
        device_station_map: Mapping[int, int],
        *,
        object_type: str,
    ) -> Dict[int, float]:
        device_flows: Dict[int, tuple[int, float]] = {}
        result: Dict[int, float] = {}
        for item in metrics:
            if str(item.get("object_type") or "").lower() != object_type.lower():
                continue
            object_id = self._normalize_int(item.get("object_id"))
            if object_id is None:
                continue
            station_id = device_station_map.get(object_id)
            if station_id is None:
                continue
            is_water_flow_metric = str(item.get("metrics_code") or "").lower() == "water_flow"
            metric_flow = self._normalize_float(item.get("value")) if is_water_flow_metric else None
            flow = metric_flow
            priority = 2
            if flow is None:
                flow = self._first_numeric(
                    item.get("front_water_flow"),
                    item.get("back_water_flow"),
                    self._attribute_value(item, "front_water_flow"),
                    self._attribute_value(item, "back_water_flow"),
                )
                priority = 1
            if flow is None:
                continue
            current = device_flows.get(object_id)
            if current is None or priority > current[0]:
                device_flows[object_id] = (priority, flow)

        for object_id, (_, flow) in device_flows.items():
            station_id = device_station_map[object_id]
            result[station_id] = result.get(station_id, 0.0) + flow
        return result

    def _collect_metric_refs_by_station(
        self,
        metrics: List[Dict[str, Any]],
        device_station_map: Mapping[int, int],
    ) -> Dict[int, List[Dict[str, Any]]]:
        result: Dict[int, List[Dict[str, Any]]] = {}
        station_ids = set(self._station_node_ids)
        for item in metrics:
            object_id = self._normalize_int(item.get("object_id"))
            if object_id is None:
                continue
            station_id = object_id if object_id in station_ids else device_station_map.get(object_id)
            if station_id is None:
                continue
            metric_ref = self._metric_ref(item)
            if metric_ref is None:
                continue
            result.setdefault(int(station_id), []).append(metric_ref)
        return result

    def _resolve_station_stage(
        self,
        metrics: List[Dict[str, Any]],
        station_id: int,
    ) -> Optional[StationStageObservation]:
        for item in metrics:
            object_id = self._normalize_int(item.get("object_id"))
            if object_id != int(station_id):
                continue
            if str(item.get("object_type") or "").replace("_", "").lower() != GATE_STATION_OBJECT_TYPE:
                continue
            if str(item.get("metrics_code") or "").lower() != WATER_LEVEL_METRICS_CODE:
                continue
            if str(item.get("position_code") or "").lower() != UPSTREAM_POSITION_CODE:
                continue
            stage = self._normalize_float(item.get("value"))
            metric_ref = self._metric_ref(item)
            if stage is not None and metric_ref is not None:
                return StationStageObservation(value=stage, metric_ref=metric_ref)
        return None

    @staticmethod
    def _sum_complete_release(
        power_outflow: Optional[float],
        spill_outflow: Optional[float],
    ) -> Optional[float]:
        if power_outflow is None or spill_outflow is None:
            return None
        return float(power_outflow) + float(spill_outflow)

    def _resolve_target_stage(
        self,
        step_runtime: Any,
        station_id: int,
        step_index: int,
    ) -> Optional[float]:
        target_stage_by_node = getattr(step_runtime, "target_stage_by_node", {}) or {}
        series = target_stage_by_node.get(int(station_id))
        return self._series_value_for_step(series, step_index)

    def _build_environment_observation(
        self,
        *,
        step_index: int,
        station_id: int,
        station_name: str,
        hint: Mapping[str, Any],
        target_stage: Optional[float],
        power_outflow: Optional[float],
        spill_outflow: Optional[float],
        total_release: Optional[float],
        output_power: Optional[float],
        predicted_output_power: Optional[float],
        prediction_error: Optional[float],
        metric_refs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        observation: Dict[str, Any] = {
            "step_index": int(step_index),
            "station_id": int(station_id),
            "station": station_name,
            "source": str(hint.get("stage_hints_source") or "unknown"),
            "stage_metric_ref": hint.get("stage_metric_ref"),
            "stage_m": self._normalize_float(hint.get("stage")),
            "design_stage_m": self._normalize_float(hint.get("design_stage")),
            "target_stage_m": target_stage,
            "delta_m": self._normalize_float(hint.get("delta")),
            "zone": hint.get("zone"),
            "inflow_m3s": self._normalize_float(hint.get("inflow_m3s")),
            "inflow_source": hint.get("inflow_source"),
            "inflow_source_step": self._normalize_int(hint.get("inflow_source_step")),
            "upstream_release_m3s": self._normalize_float(hint.get("upstream_release_m3s")),
            "upstream_release_source": hint.get("upstream_release_source"),
            "upstream_release_source_step": self._normalize_int(
                hint.get("upstream_release_source_step")
            ),
            "power_outflow_m3s": power_outflow,
            "spill_outflow_m3s": spill_outflow,
            "total_release_m3s": total_release,
            "observed_output_power_mw": output_power,
            "predicted_output_power_mw": predicted_output_power,
            "prediction_error_mw": prediction_error,
            "metric_refs": metric_refs,
            "fallback_reason": hint.get("fallback_reason"),
        }
        observation["missing_fields"] = [
            name
            for name, value in (
                ("stage_m", observation.get("stage_m")),
                ("observed_output_power_mw", output_power),
            )
            if value is None
        ]
        return observation

    def _metric_ref(self, item: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        object_id = self._normalize_int(item.get("object_id"))
        if object_id is None:
            return None
        metric_ref: Dict[str, Any] = {
            "object_id": object_id,
            "source_object_id": object_id,
            "object_type": item.get("object_type"),
            "object_name": item.get("object_name"),
            "metrics_code": item.get("metrics_code"),
            "position_code": item.get("position_code"),
            "step_index": self._normalize_int(item.get("step_index")),
            "value": self._normalize_float(item.get("value")),
        }
        for field_name in SOURCE_TIMESTAMP_FIELDS:
            if item.get(field_name) is not None:
                metric_ref["source_timestamp_ms"] = item.get(field_name)
                break
        return metric_ref

    def _build_observed_stage_hint(
        self,
        *,
        station_id: int,
        station_name: str,
        stage_observation: StationStageObservation,
        design_stage: Optional[float],
        power_outflow: Optional[float],
        spill_outflow: Optional[float],
        output_power: Optional[float],
        predicted_output_power: Optional[float],
        prediction_error: Optional[float],
        internal_hint: Mapping[str, Any],
        upstream_release: Optional[float],
        upstream_power_outflow: Optional[float],
        upstream_spill_outflow: Optional[float],
    ) -> Dict[str, Any]:
        stage = float(stage_observation.value)
        if design_stage is None:
            design_stage = stage
        delta = float(stage) - float(design_stage)
        abs_delta = abs(delta)
        if abs_delta <= 0.2:
            zone = "green"
        elif abs_delta <= 1.0:
            zone = "yellow"
        else:
            zone = "red"
        hint: Dict[str, Any] = {
            "station_id": int(station_id),
            "station": station_name,
            "stage": float(stage),
            "design_stage": float(design_stage),
            "delta": delta,
            "zone": zone,
            "direction": self._clip(delta / max(1.0 if zone == "red" else 0.2, 1e-6), -2.0, 2.0),
            "stage_hints_source": "observation_adapter",
            "stage_metric_ref": dict(stage_observation.metric_ref),
        }
        for field_name in (
            "upstream_release_m3s",
            "upstream_power_outflow_m3s",
            "upstream_spill_outflow_m3s",
        ):
            if internal_hint.get(field_name) is not None:
                hint[field_name] = internal_hint[field_name]
        if hint.get("upstream_release_m3s") is not None:
            hint["upstream_release_source"] = "v47_river_array_internal_state"
        inflow = self._normalize_float(internal_hint.get("inflow_m3s"))
        if inflow is not None:
            hint["inflow_m3s"] = inflow
            hint["inflow_source"] = "v47_river_array_internal_state"
        if power_outflow is not None:
            hint["power_outflow_m3s"] = float(power_outflow)
        if spill_outflow is not None:
            hint["spill_outflow_m3s"] = float(spill_outflow)
        if output_power is not None:
            hint["output_power_mw"] = float(output_power)
        if predicted_output_power is not None:
            hint["predicted_output_power_mw"] = float(predicted_output_power)
        if prediction_error is not None:
            hint["prediction_error_mw"] = float(prediction_error)
        if upstream_release is not None:
            hint["upstream_release_m3s"] = float(upstream_release)
            hint["upstream_release_source"] = "ontology_actual_device_outflows"
        if upstream_power_outflow is not None:
            hint["upstream_power_outflow_m3s"] = float(upstream_power_outflow)
        if upstream_spill_outflow is not None:
            hint["upstream_spill_outflow_m3s"] = float(upstream_spill_outflow)
        return hint

    @staticmethod
    def _attribute_value(item: Mapping[str, Any], attr_name: str) -> Any:
        attributes = item.get("attributes")
        if isinstance(attributes, str):
            try:
                attributes = json.loads(attributes)
            except Exception:
                return None
        if isinstance(attributes, Mapping):
            return attributes.get(attr_name)
        return None

    @staticmethod
    def _first_numeric(*values: Any) -> Optional[float]:
        for value in values:
            normalized = PowerObservationAdapter._normalize_float(value)
            if normalized is not None:
                return normalized
        return None

    @staticmethod
    def _resolve_float(*values: Any) -> Optional[float]:
        return PowerObservationAdapter._first_numeric(*values)

    @staticmethod
    def _series_value_for_step(series: Any, step_index: int) -> Optional[float]:
        if series is None or isinstance(series, (str, bytes, Mapping)):
            return None
        target_step = int(step_index)
        for row in series:
            if isinstance(row, Mapping):
                row_step = PowerObservationAdapter._normalize_int(row.get("step"))
                if row_step == target_step:
                    return PowerObservationAdapter._normalize_float(row.get("value"))
        if 0 <= target_step < len(series):
            row = series[target_step]
            if isinstance(row, Mapping):
                return PowerObservationAdapter._normalize_float(row.get("value"))
            return PowerObservationAdapter._normalize_float(row)
        return None

    @staticmethod
    def _normalize_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clip(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))
