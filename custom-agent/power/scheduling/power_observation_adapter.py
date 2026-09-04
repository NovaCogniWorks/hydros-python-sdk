from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional


@dataclass
class PowerObservationResult:
    step_index: int
    metrics_scope: str
    metrics_count: int
    stage_hints: List[Dict[str, Any]] = field(default_factory=list)
    station_output_power_by_station: Dict[int, float] = field(default_factory=dict)
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

        stage_hints: List[Dict[str, Any]] = []
        diagnostics: List[str] = []
        fallback_hints = list(internal_stage_hints or [])
        previous_total_release: Optional[float] = None
        for station_index, station_id in enumerate(self._station_node_ids):
            flow_config = self._flow_configs[station_index] if station_index < len(self._flow_configs) else {}
            fallback_hint = fallback_hints[station_index] if station_index < len(fallback_hints) else {}
            stage = self._resolve_station_stage(metrics, station_id)
            design_stage = self._resolve_float(
                fallback_hint.get("design_stage"),
                flow_config.get("design_stage"),
            )
            if stage is not None:
                hint = self._build_observed_stage_hint(
                    station_id=station_id,
                    station_name=str(flow_config.get("Name") or fallback_hint.get("station") or station_id),
                    stage=stage,
                    design_stage=design_stage,
                    power_outflow=station_power_outflow.get(station_id),
                    spill_outflow=station_spill_outflow.get(station_id),
                    output_power=station_output_power.get(station_id),
                    upstream_release=previous_total_release,
                    inflow=self._resolve_station_inflow(metrics, station_id, previous_total_release),
                )
            else:
                hint = dict(fallback_hint)
                hint.setdefault("station", str(flow_config.get("Name") or station_id))
                hint.setdefault("station_id", station_id)
                hint["stage_hints_source"] = "internal_reservoir_fallback"
                hint["fallback_reason"] = "missing_station_stage_observation"
                diagnostics.append(f"station:{station_id}:missing_stage_observation")

            if station_power_outflow.get(station_id) is not None:
                hint["power_outflow_m3s"] = float(station_power_outflow[station_id])
            if station_spill_outflow.get(station_id) is not None:
                hint["spill_outflow_m3s"] = float(station_spill_outflow[station_id])
            if station_output_power.get(station_id) is not None:
                hint["output_power_mw"] = float(station_output_power[station_id])
            if previous_total_release is not None:
                hint.setdefault("upstream_release_m3s", float(previous_total_release))

            total_release = (station_power_outflow.get(station_id) or 0.0) + (
                station_spill_outflow.get(station_id) or 0.0
            )
            previous_total_release = total_release
            stage_hints.append(hint)

        return PowerObservationResult(
            step_index=int(step_index),
            metrics_scope=metrics_scope,
            metrics_count=len(metrics),
            stage_hints=stage_hints,
            station_output_power_by_station=station_output_power,
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
            flow = self._first_numeric(
                item.get("front_water_flow"),
                item.get("back_water_flow"),
                self._attribute_value(item, "front_water_flow"),
                self._attribute_value(item, "back_water_flow"),
                item.get("value") if str(item.get("metrics_code") or "").lower() == "water_flow" else None,
            )
            if flow is None:
                continue
            result[station_id] = result.get(station_id, 0.0) + flow
        return result

    def _resolve_station_stage(
        self,
        metrics: List[Dict[str, Any]],
        station_id: int,
    ) -> Optional[float]:
        for item in metrics:
            object_id = self._normalize_int(item.get("object_id"))
            if object_id != int(station_id):
                continue
            stage = self._first_numeric(
                item.get("front_water_level"),
                self._attribute_value(item, "front_water_level"),
                item.get("value") if str(item.get("metrics_code") or "").lower() == "water_level" else None,
            )
            if stage is not None:
                return stage
        return None

    def _resolve_station_inflow(
        self,
        metrics: List[Dict[str, Any]],
        station_id: int,
        upstream_release: Optional[float],
    ) -> Optional[float]:
        direct_flow = self._resolve_station_metric_value(metrics, station_id, "water_flow")
        if direct_flow is not None:
            return direct_flow
        return upstream_release

    def _resolve_station_metric_value(
        self,
        metrics: List[Dict[str, Any]],
        station_id: int,
        metrics_code: str,
    ) -> Optional[float]:
        for item in metrics:
            object_id = self._normalize_int(item.get("object_id"))
            if object_id != int(station_id):
                continue
            if str(item.get("metrics_code") or "").lower() != metrics_code.lower():
                continue
            value = self._normalize_float(item.get("value"))
            if value is not None:
                return value
        return None

    def _build_observed_stage_hint(
        self,
        *,
        station_id: int,
        station_name: str,
        stage: float,
        design_stage: Optional[float],
        power_outflow: Optional[float],
        spill_outflow: Optional[float],
        output_power: Optional[float],
        upstream_release: Optional[float],
        inflow: Optional[float],
    ) -> Dict[str, Any]:
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
        }
        if power_outflow is not None:
            hint["power_outflow_m3s"] = float(power_outflow)
        if spill_outflow is not None:
            hint["spill_outflow_m3s"] = float(spill_outflow)
            hint["upstream_spill_outflow_m3s"] = float(spill_outflow)
        if output_power is not None:
            hint["output_power_mw"] = float(output_power)
        if upstream_release is not None:
            hint["upstream_release_m3s"] = float(upstream_release)
        if inflow is not None:
            hint["inflow_m3s"] = float(inflow)
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
