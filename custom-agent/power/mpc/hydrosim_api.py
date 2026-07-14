from __future__ import annotations

import contextlib
import copy
import io
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_snake

from hydrosim import config as hydrosim_config
from hydrosim import (
    HydroConfiguredSimulationRequest,
    HydroSimulationEventData,
    HydroSimulationInputBundle,
    HydroSimulationInputPatch,
    HydroOutputMode,
    HydroRandomSimulationRequest,
    HydroSimulationArtifacts,
    HydroSimulationInputResolver,
    HydroSimulationService,
)

__all__ = [
    "CurrentStepPowerPlanningValue",
    "HydroSimulationApi",
    "HydroSimulationSession",
    "HydroSimulationService",
    "HydroRandomSimulationRequest",
    "HydroConfiguredSimulationRequest",
    "HydroSimulationArtifacts",
    "HydroOutputMode",
    "describe_simulation_capabilities",
    "run_random_simulation",
    "run_configured_simulation",
]


class CurrentStepPowerPlanningValue(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_snake,
        populate_by_name=True,
        from_attributes=True,
    )

    object_id: int
    object_type: str
    metrics_code: str
    value: float


@dataclass
class HydroSimulationSession:
    """HydroSim 算法会话。"""

    session_id: str
    inputs: HydroSimulationInputBundle | None = None
    latest_power_planning_file: str | None = None
    latest_station_power_series: List[Dict[str, Any]] = field(default_factory=list)
    latest_device_output_series: List[Dict[str, Any]] = field(default_factory=list)
    step_runtime: "HydroSimulationStepRuntime | None" = None
    current_step_index: int = 0
    cancelled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "input_summary": self._build_input_summary(),
            "latest_power_planning_file": self.latest_power_planning_file,
            "current_step_index": self.current_step_index,
            "cancelled": self.cancelled,
        }

    def _build_input_summary(self) -> Dict[str, Any] | None:
        if self.inputs is None:
            return None
        return {
            "event_series_count": len(self.inputs.event.object_time_series),
            "has_initial_states": bool(self.inputs.initial_states.initial_states),
            "has_constraints": bool(
                self.inputs.constraints.control_targets or self.inputs.constraints.control_domains
            ),
            "has_mpc_config": bool(self.inputs.mpc_config.raw),
        }


@dataclass
class HydroSimulationStepRuntime:
    """HydroSim 步进态：保存 execute_step 所需的真实算法运行上下文。"""

    merged_event: Dict[str, Any]
    initial_states: Dict[str, Any]
    constraints: Dict[str, Any]
    flow_configs: List[Dict[str, Any]]
    steps: Any
    flows_in: Any
    station_power_plan: Dict[int, Any]
    target_stage_by_node: Dict[int, Any]
    control_domains: List[Dict[str, Any]]
    device_names: Dict[int, str]
    multi_river: Any
    multi_reservoir: Any
    multi_stair: Any


class HydroSimulationApi:
    """面向外部集成的稳定 API 门面。"""

    def __init__(self, service: HydroSimulationService | None = None) -> None:
        self.service = service or HydroSimulationService()
        self.input_resolver = HydroSimulationInputResolver()
        self._session: HydroSimulationSession | None = None

    def _normalize_output_value(self, value: Any) -> float:
        return round(float(value), 6)

    def _normalize_event_payload(
        self,
        payload: HydroSimulationEventData | dict[str, Any],
    ) -> Dict[str, Any]:
        model = payload if isinstance(payload, HydroSimulationEventData) else HydroSimulationEventData.model_validate(payload)
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)

    def describe_capabilities(self) -> Dict[str, object]:
        """获取算法能力摘要。"""
        return describe_simulation_capabilities()

    def run_random(
        self,
        request: HydroRandomSimulationRequest | None = None,
        output_mode: HydroOutputMode = "mixed",
        **kwargs,
    ) -> Dict[str, Any]:
        """执行随机仿真。"""
        return self.service.run_random(request=request, output_mode=output_mode, **kwargs)

    def run_configured(
        self,
        request: HydroConfiguredSimulationRequest | None = None,
        output_mode: HydroOutputMode = "mixed",
        input_bundle: HydroSimulationInputBundle | dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """执行配置驱动仿真。"""
        if request is None or input_bundle is None:
            raise ValueError("run_configured requires both request and input_bundle.")
        return self.service.run_configured(request=request, output_mode=output_mode, input_bundle=input_bundle)

    def initialize(
        self,
        input_bundle: HydroSimulationInputBundle | dict[str, Any],
    ) -> Dict[str, Any]:
        bundle = self.input_resolver.resolve_bundle(input_bundle=input_bundle)
        event = bundle.event.model_dump(mode="json", by_alias=True, exclude_none=True)
        steps = self.service.core.runtime._time_axis_from_event(event)
        self._session = HydroSimulationSession(
            session_id=uuid.uuid4().hex,
            inputs=bundle,
        )
        return {
            "message": "HydroSim 算法初始化成功。",
            "session": self._session.to_dict(),
            "time_axis_length": int(len(steps)),
            "station_count": len(hydrosim_config.POWER_CONFIGS),
            "station_names": hydrosim_config.list_station_names(),
        }

    def inject_operating_conditions(
        self,
        patch: HydroSimulationInputPatch | dict[str, Any],
    ) -> Dict[str, Any]:
        session = self._require_session()
        if session.inputs is None:
            raise RuntimeError("当前会话缺少输入快照。")
        patch_model = self.input_resolver.resolve_patch(patch=patch)
        session.inputs = self.input_resolver.merge_patch(session.inputs, patch_model)
        session.latest_power_planning_file = None
        session.latest_station_power_series = []
        session.latest_device_output_series = []
        session.step_runtime = None
        session.current_step_index = 0
        session.cancelled = False
        return {
            "message": "工况注入成功，会话已重置规划结果。",
            "session": session.to_dict(),
        }

    def get_station_power_planning_series(
        self,
        planning_event: HydroSimulationEventData | dict[str, Any],
    ) -> Dict[str, Any]:
        session = self._require_session()
        if session.inputs is None:
            raise RuntimeError("当前会话缺少输入快照。")
        base_event = session.inputs.event.model_dump(mode="json", by_alias=True, exclude_none=True)
        planning_payload = self._normalize_event_payload(planning_event)
        merged_event = self._merge_event_with_power_plan(base_event, planning_payload)
        run_summary, station_power_series, device_output_series = self._run_configured_with_event(
            session,
            merged_event,
        )

        session.latest_power_planning_file = None
        session.latest_station_power_series = station_power_series
        session.latest_device_output_series = device_output_series
        session.step_runtime = self._build_step_runtime(session, merged_event)
        session.current_step_index = 0
        session.cancelled = False

        return {
            "message": "站点规划出力时间序列生成成功。",
            "session": session.to_dict(),
            "run_summary": run_summary,
            "station_power_series": station_power_series,
        }

    def get_station_power_planning_series_from_inflow(
        self,
        inflow_event: HydroSimulationEventData | dict[str, Any],
    ) -> Dict[str, Any]:
        session = self._require_session()
        if session.inputs is None:
            raise RuntimeError("当前会话缺少输入快照。")
        base_event = session.inputs.event.model_dump(mode="json", by_alias=True, exclude_none=True)
        inflow_payload = self._normalize_event_payload(inflow_event)
        merged_event = self._merge_event_with_updates(base_event, inflow_payload)

        generated_event, station_power_series, device_output_series = self._run_inflow_power_planning(
            session,
            merged_event,
        )

        session.latest_power_planning_file = None
        session.latest_station_power_series = station_power_series
        session.latest_device_output_series = device_output_series
        session.step_runtime = self._build_step_runtime(session, generated_event)
        session.current_step_index = 0
        session.cancelled = False

        return {
            "message": "station power planning generated from inflow",
            "session": session.to_dict(),
            "station_power_series": station_power_series,
            "device_output_series": device_output_series,
        }

    def apply_time_series_event_update(
        self,
        event_payload: HydroSimulationEventData | dict[str, Any],
        current_step: int | None = None,
        current_step_metrics: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """将事件时序并入当前 HydroSim 会话，并刷新规划结果与步进上下文。"""

        session = self._require_session()
        base_event = self._resolve_active_merged_event(session)
        merged_event = self._merge_event_with_updates(base_event, event_payload)
        if current_step is not None and current_step >= 0:
            merged_event = self._overlay_current_step_metrics(
                merged_event,
                current_step=int(current_step),
                current_step_metrics=current_step_metrics or [],
            )
        run_summary, station_power_series, device_output_series = self._run_configured_with_event(
            session,
            merged_event,
        )

        session.latest_station_power_series = station_power_series
        session.latest_device_output_series = device_output_series
        session.step_runtime = self._build_step_runtime(session, merged_event)
        session.current_step_index = 0
        session.cancelled = False

        return {
            "message": "HydroSim 会话已应用时序事件更新。",
            "session": session.to_dict(),
            "run_summary": run_summary,
            "station_power_series": station_power_series,
            "device_output_series": device_output_series,
            "updated_time_series_count": len(self._get_object_time_series_items(event_payload)),
        }

    def execute_step(
        self,
        step_index: int | None = None,
        current_step_power_planning_values: List[CurrentStepPowerPlanningValue] | None = None,
    ) -> Dict[str, Any]:
        """每步执行接口。

        用法：
        - 如果已生成规划结果，则按顺序返回下一步各站点出力
        - 如果传入 `step_index`，则返回指定步
        - 如果传入 `current_step_power_planning_values`，则使用包含 `object_id/object_type/metrics_code/value` 的当前步规划值执行步进
        """

        session = self._require_session()
        if session.cancelled:
            raise RuntimeError("当前会话已取消，不能继续执行步进。")
        target_step = session.current_step_index if step_index is None else int(step_index)
        step_runtime = session.step_runtime

        if step_runtime is None:
            raise RuntimeError("当前会话尚未生成可步进的仿真上下文，请先调用获取规划出力时间序列接口。")

        total_steps = int(len(step_runtime.steps))
        if total_steps <= 0:
            raise RuntimeError("当前会话没有可执行的仿真步。")
        if target_step < 0 or target_step >= total_steps:
            raise IndexError(f"step_index={target_step} 超出仿真步范围 [0, {total_steps - 1}]。")

        if current_step_power_planning_values is None and not session.latest_station_power_series:
            raise RuntimeError("当前会话尚未生成规划结果，请先调用获取规划出力时间序列接口。")

        if target_step < session.current_step_index:
            session.step_runtime = self._build_step_runtime(
                session,
                copy.deepcopy(step_runtime.merged_event),
            )
            step_runtime = session.step_runtime
            session.current_step_index = 0

        normalized_values = self._normalize_current_step_power_planning_values(
            current_step_power_planning_values or [],
        )
        planning_values_by_node = self._resolve_step_power_plan_values(
            step_runtime,
            target_step,
            normalized_values,
        )
        self._advance_runtime_to_target_step(
            session=session,
            step_runtime=step_runtime,
            target_step=target_step,
            planning_values_by_node=planning_values_by_node,
        )

        station_step_outputs = self._build_station_step_outputs_from_runtime(step_runtime, target_step)
        device_step_outputs = self._build_device_step_outputs_from_runtime(step_runtime, target_step)
        current_step_power_planning_values = [
            {
                "object_id": node_id,
                "object_type": "Station",
                "metrics_code": "output_power",
                "value": self._normalize_output_value(planning_values_by_node[node_id]),
            }
            for node_id in hydrosim_config.STATION_NODE_IDS
        ]

        return {
            "message": "步进执行成功。",
            "session": session.to_dict(),
            "current_step_index": target_step,
            "has_next_step": target_step + 1 < total_steps,
            "current_step_power_planning_values": current_step_power_planning_values,
            "station_step_outputs": station_step_outputs,
            "device_step_outputs": device_step_outputs,
        }

    def _resolve_total_steps(self, station_power_series: List[Dict[str, Any]]) -> int:
        return max((len(station.get("time_series", [])) for station in station_power_series), default=0)

    def _build_station_step_outputs_from_series(
        self,
        station_power_series: List[Dict[str, Any]],
        target_step: int,
    ) -> List[Dict[str, Any]]:
        station_step_outputs: List[Dict[str, Any]] = []
        for station in station_power_series:
            series = station.get("time_series", [])
            if target_step < 0 or target_step >= len(series):
                raise IndexError(f"step_index={target_step} 超出站点 {station['station']} 的时间序列范围。")
            row = series[target_step]
            station_step_outputs.append(
                {
                    "node_id": int(station["node_id"]),
                    "station": station["station"],
                    "step": int(row["step"]),
                    "power": self._normalize_output_value(row["value"]),
                }
            )
        return station_step_outputs

    def _normalize_current_step_power_planning_values(
        self,
        current_step_power_planning_values: List[CurrentStepPowerPlanningValue | Dict[str, Any]],
    ) -> List[CurrentStepPowerPlanningValue]:
        normalized_values: List[CurrentStepPowerPlanningValue] = []
        station_names = hydrosim_config.build_station_name_map()
        for item in current_step_power_planning_values:
            model = (
                item
                if isinstance(item, CurrentStepPowerPlanningValue)
                else CurrentStepPowerPlanningValue.model_validate(item)
            )
            object_id = int(model.object_id)
            object_type = model.object_type
            metrics_code = model.metrics_code
            if object_type != "Station" or metrics_code != "output_power":
                raise ValueError("current_step_power_planning_values 仅支持 Station/output_power 规划出力数据。")
            if object_id not in station_names:
                raise ValueError(f"current_step_power_planning_values 包含未配置的站点 object_id={object_id}。")
            normalized_values.append(
                CurrentStepPowerPlanningValue(
                    object_id=object_id,
                    object_type=object_type,
                    metrics_code=metrics_code,
                    value=float(model.value),
                )
            )
        return normalized_values

    def _build_step_runtime(
        self,
        session: HydroSimulationSession,
        merged_event: Dict[str, Any],
    ) -> HydroSimulationStepRuntime:
        runtime = self.service.core.runtime
        if session.inputs is None:
            raise RuntimeError("当前会话缺少输入快照。")
        initial_states = session.inputs.initial_states.model_dump(mode="json", by_alias=True, exclude_none=True)
        constraints = session.inputs.constraints.model_dump(mode="json", by_alias=True, exclude_none=True)
        steps = runtime._time_axis_from_event(merged_event)
        flow_configs, default_target_stage_by_node = runtime._apply_yaml_basic_parameters(
            list(self.service.core.flow_configs),
            constraints,
            initial_states,
            merged_event,
        )
        flows_in = runtime._upstream_inflow_series(merged_event, steps, initial_states)
        power_cmd, station_power_plan = runtime._power_series_by_station(merged_event, steps)
        target_stage_by_node = runtime._target_stage_series_by_node(
            merged_event,
            steps,
            default_target_stage_by_node,
        )
        multi_river = runtime.RiverArray(
            1,
            "大渡河_水力_V16_步进",
            flow_configs,
            max(len(steps), 1),
            self.service.core.capa_loc,
        )
        multi_reservoir = runtime.HydroResStairs(
            1,
            "大渡河_水库_V16_步进",
            flow_configs,
            self.service.core.flow_station_cfgs,
            self.service.core.capa_loc,
        )
        multi_stair = runtime.HydroStair(
            1,
            "大渡河_电站_V16_步进",
            float(power_cmd[0]),
            self.service.core.power_configs,
            self.service.core.unit_configs,
        )
        runtime._apply_initial_conditions(multi_reservoir, multi_stair, flow_configs, initial_states)
        return HydroSimulationStepRuntime(
            merged_event=merged_event,
            initial_states=initial_states,
            constraints=constraints,
            flow_configs=flow_configs,
            steps=steps,
            flows_in=flows_in,
            station_power_plan=station_power_plan,
            target_stage_by_node=target_stage_by_node,
            control_domains=list(constraints.get("control_domains", []) or []),
            device_names=self._build_device_name_map(initial_states),
            multi_river=multi_river,
            multi_reservoir=multi_reservoir,
            multi_stair=multi_stair,
        )

    def _run_inflow_power_planning(
        self,
        session: HydroSimulationSession,
        merged_event: Dict[str, Any],
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        runtime = self.service.core.runtime
        if session.inputs is None:
            raise RuntimeError("current session is missing inputs snapshot")
        initial_states = session.inputs.initial_states.model_dump(mode="json", by_alias=True, exclude_none=True)
        constraints = session.inputs.constraints.model_dump(mode="json", by_alias=True, exclude_none=True)
        steps = runtime._time_axis_from_event(merged_event)
        if len(steps) <= 0:
            raise ValueError("inflow time series has no steps")

        flow_configs, default_target_stage_by_node = runtime._apply_yaml_basic_parameters(
            list(self.service.core.flow_configs),
            constraints,
            initial_states,
            merged_event,
        )
        flows_in = runtime._upstream_inflow_series(merged_event, steps, initial_states)
        if len(flows_in) <= 0:
            raise ValueError("no Station/water_flow inflow series found")

        target_stage_by_node = runtime._target_stage_series_by_node(
            merged_event,
            steps,
            default_target_stage_by_node,
        )
        power_cmd = self._inflow_to_total_power_command(flows_in)

        multi_river = runtime.RiverArray(
            1,
            "power_inflow_planning_river",
            flow_configs,
            max(len(steps), 1),
            self.service.core.capa_loc,
        )
        multi_reservoir = runtime.HydroResStairs(
            1,
            "power_inflow_planning_reservoir",
            flow_configs,
            self.service.core.flow_station_cfgs,
            self.service.core.capa_loc,
        )
        multi_stair = runtime.HydroStair(
            1,
            "power_inflow_planning_stair",
            float(power_cmd[0]),
            self.service.core.power_configs,
            self.service.core.unit_configs,
        )
        runtime._apply_initial_conditions(multi_reservoir, multi_stair, flow_configs, initial_states)
        runtime._run_phase_v16(
            title="inflow power planning",
            idx_start=0,
            idx_end=len(steps),
            progress_interval=0,
            flows_in=flows_in,
            power_cmd=power_cmd,
            target_stage_by_node=target_stage_by_node,
            multi_river=multi_river,
            multi_reservoir=multi_reservoir,
            multi_stair=multi_stair,
        )

        station_power_series = self._build_station_power_series_from_runtime(steps, multi_stair)
        generated_event = self._merge_event_with_power_plan(
            merged_event,
            {"object_time_series": self._station_power_series_to_event_items(station_power_series)},
        )
        device_output_series = self._build_device_output_series_from_runtime(
            steps=steps,
            constraints=constraints,
            initial_states=initial_states,
            multi_stair=multi_stair,
            multi_reservoir=multi_reservoir,
        )
        return generated_event, station_power_series, device_output_series

    def _inflow_to_total_power_command(self, flows_in: Any) -> Any:
        runtime = self.service.core.runtime
        np = runtime.np
        flows = np.asarray(flows_in, dtype=float)
        station_heads = np.asarray(
            [float(cfg["design_head"]) for cfg in self.service.core.power_configs],
            dtype=float,
        )
        power_per_flow = float(9.81 * 0.90 * station_heads.sum() / 1000.0)
        max_total_power = float(sum(float(cfg["max_power"]) for cfg in self.service.core.power_configs))
        min_positive_power = float(sum(float(cfg["min_power"]) for cfg in self.service.core.power_configs))
        power_cmd = np.clip(flows * power_per_flow, 0.0, max_total_power)
        return np.where(power_cmd > 1e-6, np.maximum(power_cmd, min_positive_power), 0.0)

    def _build_station_power_series_from_runtime(self, steps: Any, multi_stair: Any) -> List[Dict[str, Any]]:
        station_names = hydrosim_config.build_station_name_map()
        result: List[Dict[str, Any]] = []
        for node_id in hydrosim_config.STATION_NODE_IDS:
            station_idx = hydrosim_config.NODE_TO_INDEX[node_id]
            station = multi_stair.multi_stair[station_idx]
            result.append(
                {
                    "node_id": int(node_id),
                    "station": station_names.get(node_id, str(station.name)),
                    "time_series": [
                        {"step": int(step), "value": self._normalize_output_value(value)}
                        for step, value in zip(steps, station.history["current_power"])
                    ],
                }
            )
        return result

    def _station_power_series_to_event_items(self, station_power_series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "time_series_name": f"{station['station']}_power_plan",
                "object_id": int(station["node_id"]),
                "object_type": "Station",
                "object_name": station["station"],
                "metrics_code": "output_power",
                "time_series": copy.deepcopy(station.get("time_series", [])),
            }
            for station in station_power_series
        ]

    def _build_device_output_series_from_runtime(
        self,
        steps: Any,
        constraints: Dict[str, Any],
        initial_states: Dict[str, Any],
        multi_stair: Any,
        multi_reservoir: Any,
    ) -> List[Dict[str, Any]]:
        result_factory = self.service.core.result_factory
        control_domains = list(constraints.get("control_domains", []) or [])
        device_names = self._build_device_name_map(initial_states)
        result: List[Dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for row in control_domains:
            if row.get("device_id") is None:
                continue
            device_id = int(row["device_id"])
            control_type = str(row.get("type", ""))
            for metric in result_factory._device_metrics_for_control_type(control_type):
                key = (device_id, metric)
                if key in seen:
                    continue
                seen.add(key)
                values = result_factory._control_domain_device_series(
                    device_id=device_id,
                    metric=metric,
                    control_type=control_type,
                    control_domains=control_domains,
                    multi_stair=multi_stair,
                    multi_reservoir=multi_reservoir,
                )
                if not values:
                    continue
                result.append(
                    {
                        "object_id": device_id,
                        "object_type": control_type,
                        "object_name": device_names.get(device_id, f"device_{device_id}"),
                        "metrics_code": metric,
                        "node_id": row.get("node_id"),
                        "time_series": [
                            {
                                "step": int(step),
                                "value": self._normalize_output_value(value),
                            }
                            for step, value in zip(steps, values)
                        ],
                    }
                )
        return result

    def _build_device_name_map(self, initial_states: Dict[str, Any]) -> Dict[int, str]:
        result: Dict[int, str] = {}
        root = initial_states.get("initial_states", initial_states)
        for section in root.values():
            if not isinstance(section, dict):
                continue
            overrides = section.get("overrides", [])
            if isinstance(overrides, dict):
                rows: List[Dict[str, Any]] = []
                for values in overrides.values():
                    if isinstance(values, list):
                        rows.extend(values)
            else:
                rows = list(overrides or [])
            for row in rows:
                if not isinstance(row, dict) or row.get("id") is None or not row.get("name"):
                    continue
                try:
                    device_id = int(row["id"])
                except (TypeError, ValueError):
                    continue
                result[device_id] = str(row["name"])
        return result

    def _resolve_step_power_plan_values(
        self,
        step_runtime: HydroSimulationStepRuntime,
        target_step: int,
        normalized_values: List[CurrentStepPowerPlanningValue],
    ) -> Dict[int, float]:
        planning_values_by_node = {
            int(node_id): float(step_runtime.station_power_plan[node_id][target_step])
            for node_id in hydrosim_config.STATION_NODE_IDS
        }
        for item in normalized_values:
            planning_values_by_node[int(item.object_id)] = float(item.value)
        return planning_values_by_node

    def _advance_runtime_to_target_step(
        self,
        session: HydroSimulationSession,
        step_runtime: HydroSimulationStepRuntime,
        target_step: int,
        planning_values_by_node: Dict[int, float],
    ) -> None:
        while session.current_step_index <= target_step:
            step_to_run = session.current_step_index
            step_plan = (
                planning_values_by_node
                if step_to_run == target_step
                else {
                    int(node_id): float(step_runtime.station_power_plan[node_id][step_to_run])
                    for node_id in hydrosim_config.STATION_NODE_IDS
                }
            )
            self._execute_runtime_step(step_runtime, step_to_run, step_plan)
            session.current_step_index = step_to_run + 1

    def _execute_runtime_step(
        self,
        step_runtime: HydroSimulationStepRuntime,
        step_index: int,
        planning_values_by_node: Dict[int, float],
    ) -> None:
        runtime = self.service.core.runtime
        runtime._set_step_target_stages(
            step_runtime.multi_reservoir,
            step_runtime.target_stage_by_node,
            step_index,
        )
        step_runtime.multi_stair.update_stage_hints(step_runtime.multi_reservoir.stage_hints())
        total_power_cmd = float(sum(planning_values_by_node.values()))
        step_runtime.multi_stair.step_execute(total_power_cmd)
        step_runtime.multi_reservoir.step(
            step_runtime.multi_river,
            step_runtime.multi_stair,
            record=True,
        )
        step_runtime.multi_river.step_execute(
            step_runtime.multi_reservoir,
            float(step_runtime.flows_in[step_index]),
        )

    def _build_station_step_outputs_from_runtime(
        self,
        step_runtime: HydroSimulationStepRuntime,
        target_step: int,
    ) -> List[Dict[str, Any]]:
        outputs: List[Dict[str, Any]] = []
        for node_id in hydrosim_config.STATION_NODE_IDS:
            station_idx = hydrosim_config.NODE_TO_INDEX[node_id]
            station = step_runtime.multi_stair.multi_stair[station_idx]
            outputs.append(
                {
                    "node_id": int(node_id),
                    "station": str(station.name),
                    "step": int(target_step),
                    "power": self._normalize_output_value(station.history["current_power"][-1]),
                }
            )
        return outputs

    def _build_device_step_outputs_from_runtime(
        self,
        step_runtime: HydroSimulationStepRuntime,
        target_step: int,
    ) -> List[Dict[str, Any]]:
        result_factory = self.service.core.result_factory
        outputs: List[Dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for row in step_runtime.control_domains:
            if row.get("device_id") is None:
                continue
            device_id = int(row["device_id"])
            control_type = str(row.get("type", ""))
            for metric in result_factory._device_metrics_for_control_type(control_type):
                key = (device_id, metric)
                if key in seen:
                    continue
                seen.add(key)
                series = result_factory._control_domain_device_series(
                    device_id=device_id,
                    metric=metric,
                    control_type=control_type,
                    control_domains=step_runtime.control_domains,
                    multi_stair=step_runtime.multi_stair,
                    multi_reservoir=step_runtime.multi_reservoir,
                )
                if not series:
                    continue
                outputs.append(
                    {
                        "object_id": device_id,
                        "object_type": control_type,
                        "object_name": step_runtime.device_names.get(device_id, f"device_{device_id}"),
                        "metrics_code": metric,
                        "node_id": row.get("node_id"),
                        "step": int(target_step),
                        "value": self._normalize_output_value(series[-1]),
                    }
                )
        return outputs

    def cancel(self) -> Dict[str, Any]:
        """取消接口。

        调用后会将当前会话标记为已取消，并清空最近一次规划结果。
        """

        session = self._require_session()
        session.cancelled = True
        session.latest_station_power_series = []
        session.latest_device_output_series = []
        session.latest_power_planning_file = None
        session.step_runtime = None
        session.current_step_index = 0
        return {
            "message": "当前 HydroSim 会话已取消。",
            "session": session.to_dict(),
        }

    def get_session_info(self) -> Dict[str, Any]:
        """获取当前会话信息。"""
        session = self._require_session()
        return {
            "message": "当前会话信息获取成功。",
            "session": session.to_dict(),
            "has_active_power_plan": bool(session.latest_station_power_series),
            "has_active_device_outputs": bool(session.latest_device_output_series),
        }

    def _require_session(self) -> HydroSimulationSession:
        if self._session is None:
            raise RuntimeError("HydroSim 尚未初始化，请先调用算法初始化接口。")
        return self._session

    def _run_configured_with_event(
        self,
        session: HydroSimulationSession,
        merged_event: Dict[str, Any],
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        with tempfile.TemporaryDirectory(prefix="hydrosim_api_") as temp_dir:
            with contextlib.redirect_stdout(io.StringIO()):
                if session.inputs is None:
                    raise RuntimeError("current session is missing inputs snapshot")
                bundle = HydroSimulationInputBundle(
                    event=HydroSimulationEventData.model_validate(merged_event),
                    initial_states=session.inputs.initial_states,
                    constraints=session.inputs.constraints,
                    mpc_config=session.inputs.mpc_config,
                )
                result = self.run_configured(
                    request=HydroConfiguredSimulationRequest(
                        output_dir=temp_dir,
                        make_plots=False,
                        progress_interval=0,
                    ),
                    input_bundle=bundle,
                    output_mode="mixed",
                )

            files = result["files"]
            run_summary = result["json"]["run_summary"]
            station_power_series = self._extract_station_power_series_from_yaml(files["configured_outputs_yaml"])
            device_output_series = self._extract_device_output_series_from_yaml(files["configured_outputs_yaml"])
            return run_summary, station_power_series, device_output_series

    def _resolve_active_merged_event(self, session: HydroSimulationSession) -> Dict[str, Any]:
        step_runtime = getattr(session, "step_runtime", None)
        if step_runtime is not None and getattr(step_runtime, "merged_event", None):
            return copy.deepcopy(step_runtime.merged_event)
        if session.inputs is None:
            raise RuntimeError("当前会话缺少输入快照。")
        return session.inputs.event.model_dump(mode="json", by_alias=True, exclude_none=True)

    def _merge_event_with_power_plan(self, base_event: Dict[str, Any], planning_payload: Dict[str, Any]) -> Dict[str, Any]:
        planning_series = self._extract_station_power_items(planning_payload)
        if not planning_series:
            raise ValueError("发电需求时间序列文件中未找到 Station/output_power 时间序列。")

        merged_event = copy.deepcopy(base_event)
        object_time_series = list(merged_event.get("object_time_series", []) or [])
        object_time_series = [item for item in object_time_series if not self._is_station_power_item(item)]
        object_time_series.extend(copy.deepcopy(planning_series))
        merged_event["object_time_series"] = object_time_series
        return merged_event

    def _merge_event_with_updates(self, base_event: Dict[str, Any], event_payload: Any) -> Dict[str, Any]:
        update_items = self._get_object_time_series_items(event_payload)
        if not update_items:
            return copy.deepcopy(base_event)

        merged_event = copy.deepcopy(base_event)
        existing_items = list(merged_event.get("object_time_series", []) or [])
        event_object_type = self._get_event_object_type(event_payload)
        replace_matching_time_series = self._should_replace_matching_time_series(event_payload)
        index_by_key = {
            self._build_time_series_identity(item): idx
            for idx, item in enumerate(existing_items)
        }

        for raw_item in update_items:
            normalized_item = copy.deepcopy(raw_item)
            if event_object_type and not normalized_item.get("object_type"):
                normalized_item["object_type"] = event_object_type
            if replace_matching_time_series:
                existing_items = self._replace_matching_time_series_items(existing_items, normalized_item)
                index_by_key = {
                    self._build_time_series_identity(item): idx
                    for idx, item in enumerate(existing_items)
                }
            identity = self._build_time_series_identity(normalized_item)
            existing_index = index_by_key.get(identity)
            if existing_index is None:
                index_by_key[identity] = len(existing_items)
                existing_items.append(normalized_item)
            else:
                existing_items[existing_index] = self._merge_object_time_series_item(
                    existing_items[existing_index],
                    normalized_item,
                    replace_time_series=replace_matching_time_series,
                )

        merged_event["object_time_series"] = existing_items
        return merged_event

    def _get_object_time_series_items(self, payload: Any) -> List[Dict[str, Any]]:
        if payload is None:
            return []
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(payload, dict):
            items = payload.get("object_time_series")
            if not isinstance(items, list):
                items = payload.get("objectTimeSeries")
            return [item for item in (items or []) if isinstance(item, dict)]
        return []

    def _get_event_object_type(self, payload: Any) -> str | None:
        if payload is None:
            return None
        if hasattr(payload, "object_type"):
            return getattr(payload, "object_type")
        if isinstance(payload, dict):
            return payload.get("object_type") or payload.get("objectType")
        return None

    def _build_time_series_identity(self, item: Dict[str, Any]) -> tuple[Any, ...]:
        object_ids = item.get("object_ids") or []
        if item.get("object_id") is not None:
            object_ids = list(object_ids) + [item["object_id"]]
        normalized_object_ids = tuple(sorted(str(object_id) for object_id in object_ids if object_id is not None))
        return (
            item.get("object_type"),
            item.get("metrics_code"),
            normalized_object_ids,
            item.get("object_name") if not normalized_object_ids else None,
        )

    def _should_replace_matching_time_series(self, payload: Any) -> bool:
        event_source_type = None
        if hasattr(payload, "hydro_event_source_type"):
            event_source_type = getattr(payload, "hydro_event_source_type")
        elif isinstance(payload, dict):
            event_source_type = payload.get("hydro_event_source_type") or payload.get("hydroEventSourceType")
        return str(event_source_type) == "OUTFLOW_TIME_SERIES"

    def _replace_matching_time_series_items(
        self,
        existing_items: List[Dict[str, Any]],
        update_item: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        return [
            item
            for item in existing_items
            if not self._should_replace_existing_time_series_item(item, update_item)
        ]

    def _should_replace_existing_time_series_item(
        self,
        existing_item: Dict[str, Any],
        update_item: Dict[str, Any],
    ) -> bool:
        if existing_item.get("object_type") != update_item.get("object_type"):
            return False
        if existing_item.get("metrics_code") != update_item.get("metrics_code"):
            return False

        existing_ids = set(self._extract_identity_object_ids(existing_item))
        update_ids = set(self._extract_identity_object_ids(update_item))
        if existing_ids and update_ids:
            return bool(existing_ids & update_ids)
        return self._build_time_series_identity(existing_item) == self._build_time_series_identity(update_item)

    def _merge_object_time_series_item(
        self,
        existing_item: Dict[str, Any],
        update_item: Dict[str, Any],
        replace_time_series: bool = False,
    ) -> Dict[str, Any]:
        merged_item = copy.deepcopy(existing_item)
        for field in ("time_series_name", "object_id", "object_ids", "object_type", "object_name", "metrics_code"):
            if update_item.get(field) not in (None, []):
                merged_item[field] = copy.deepcopy(update_item[field])
        if replace_time_series:
            merged_item["time_series"] = copy.deepcopy(update_item.get("time_series", []) or [])
        else:
            merged_item["time_series"] = self._merge_time_series_rows(
                existing_item.get("time_series", []) or [],
                update_item.get("time_series", []) or [],
            )
        return merged_item

    def _merge_time_series_rows(
        self,
        existing_rows: List[Dict[str, Any]],
        update_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged_by_step: Dict[int, Dict[str, Any]] = {}
        extra_rows: List[Dict[str, Any]] = []

        for row in existing_rows:
            normalized_row = copy.deepcopy(row)
            step = normalized_row.get("step")
            if step is None:
                extra_rows.append(normalized_row)
                continue
            merged_by_step[int(step)] = normalized_row

        for row in update_rows:
            normalized_row = copy.deepcopy(row)
            step = normalized_row.get("step")
            if step is None:
                extra_rows.append(normalized_row)
                continue
            merged_by_step[int(step)] = normalized_row

        ordered_rows = [merged_by_step[step] for step in sorted(merged_by_step)]
        return ordered_rows + extra_rows

    def _overlay_current_step_metrics(
        self,
        merged_event: Dict[str, Any],
        current_step: int,
        current_step_metrics: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not current_step_metrics:
            return merged_event

        overlay_event = copy.deepcopy(merged_event)
        override_lookup: Dict[tuple[Any, ...], float] = {}
        for item in current_step_metrics:
            identity = self._build_metric_identity(item)
            if identity is None or item.get("value") is None:
                continue
            override_lookup[identity] = float(item["value"])

        if not override_lookup:
            return overlay_event

        for item in overlay_event.get("object_time_series", []) or []:
            override_value = self._resolve_override_value_for_time_series_item(item, override_lookup)
            if override_value is None:
                continue
            item["time_series"] = self._merge_time_series_rows(
                item.get("time_series", []) or [],
                [{"step": int(current_step), "value": float(override_value)}],
            )
        return overlay_event

    def _resolve_override_value_for_time_series_item(
        self,
        item: Dict[str, Any],
        override_lookup: Dict[tuple[Any, ...], float],
    ) -> float | None:
        metric_identity = self._build_metric_identity(item)
        if metric_identity in override_lookup:
            return override_lookup[metric_identity]

        object_ids = self._extract_identity_object_ids(item)
        if (
            item.get("object_type") == "Station"
            and item.get("metrics_code") == "output_power"
            and len(object_ids) > 1
        ):
            collected = [
                override_lookup[(item.get("object_type"), item.get("metrics_code"), (object_id,))]
                for object_id in object_ids
                if (item.get("object_type"), item.get("metrics_code"), (object_id,)) in override_lookup
            ]
            if collected:
                return float(sum(collected))
        return None

    def _build_metric_identity(self, item: Dict[str, Any]) -> tuple[str, str, tuple[int, ...]] | None:
        object_type = item.get("object_type")
        metrics_code = item.get("metrics_code")
        object_ids = self._extract_identity_object_ids(item)
        if not object_type or not metrics_code or not object_ids:
            return None
        return str(object_type), str(metrics_code), tuple(object_ids)

    def _extract_identity_object_ids(self, item: Dict[str, Any]) -> List[int]:
        object_ids = item.get("object_ids") or []
        if item.get("object_id") is not None:
            object_ids = list(object_ids) + [item["object_id"]]
        normalized: List[int] = []
        for object_id in object_ids:
            if object_id is None:
                continue
            try:
                normalized.append(int(object_id))
            except (TypeError, ValueError):
                continue
        return sorted(set(normalized))

    def _extract_station_power_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(payload.get("object_time_series"), list):
            items = payload["object_time_series"]
        elif isinstance(payload.get("objectTimeSeries"), list):
            items = payload["objectTimeSeries"]
        else:
            items = []
        return [item for item in items if self._is_station_power_item(item)]

    def _is_station_power_item(self, item: Dict[str, Any]) -> bool:
        return item.get("object_type") == "Station" and item.get("metrics_code") == "output_power"

    def _extract_station_power_series_from_yaml(self, yaml_path: str) -> List[Dict[str, Any]]:
        with open(yaml_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        station_power_plan_used = payload.get("station_power_plan_used") or []
        if station_power_plan_used:
            return [
                {
                    "node_id": int(item["node_id"]),
                    "station": item["station"],
                    "time_series": [
                        {"step": int(row["step"]), "value": self._normalize_output_value(row["value"])}
                        for row in item.get("time_series", [])
                    ],
                }
                for item in station_power_plan_used
            ]

        station_names = hydrosim_config.build_station_name_map()
        result = []
        for item in payload.get("object_time_series", []) or []:
            if item.get("object_type") != "Station" or item.get("metrics_code") != "output_power":
                continue
            object_ids = item.get("object_ids") or []
            if item.get("object_id") is not None:
                object_ids = list(object_ids) + [item["object_id"]]
            if len(object_ids) != 1:
                continue
            node_id = int(object_ids[0])
            result.append(
                {
                    "node_id": node_id,
                    "station": item.get("object_name") or station_names.get(node_id, str(node_id)),
                    "time_series": [
                        {"step": int(row["step"]), "value": self._normalize_output_value(row["value"])}
                        for row in item.get("time_series", [])
                    ],
                }
            )
        return result

    def _extract_device_output_series_from_yaml(self, yaml_path: str) -> List[Dict[str, Any]]:
        with open(yaml_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        result = []
        for item in payload.get("object_time_series", []) or []:
            object_type = item.get("object_type")
            metrics_code = item.get("metrics_code")
            if object_type not in {"Turbine", "Gate"}:
                continue
            if object_type == "Turbine" and metrics_code not in {"output_power", "water_flow"}:
                continue
            if object_type == "Gate" and metrics_code not in {"water_flow", "gate_opening"}:
                continue
            object_ids = item.get("object_ids") or []
            if item.get("object_id") is not None:
                object_ids = list(object_ids) + [item["object_id"]]
            if len(object_ids) != 1:
                continue
            result.append(
                {
                    "object_id": int(object_ids[0]),
                    "object_type": object_type,
                    "object_name": item.get("object_name") or f"device_{object_ids[0]}",
                    "metrics_code": metrics_code,
                    "node_id": item.get("node_id"),
                    "time_series": [
                        {"step": int(row["step"]), "value": self._normalize_output_value(row["value"])}
                        for row in item.get("time_series", [])
                    ],
                }
            )
        return result

    def _build_device_step_outputs_from_series(
        self,
        device_output_series: List[Dict[str, Any]],
        target_step: int,
    ) -> List[Dict[str, Any]]:
        outputs = []
        for device_series in device_output_series:
            series = device_series.get("time_series", [])
            if target_step < 0 or target_step >= len(series):
                raise IndexError(
                    f"step_index={target_step} 超出设备 {device_series['object_id']} 的时间序列范围。"
                )
            row = series[target_step]
            outputs.append(
                {
                    "object_id": int(device_series["object_id"]),
                    "object_type": str(device_series["object_type"]),
                    "object_name": str(device_series["object_name"]),
                    "metrics_code": str(device_series["metrics_code"]),
                    "node_id": device_series.get("node_id"),
                    "step": int(row["step"]),
                    "value": self._normalize_output_value(row["value"]),
                }
            )
        return outputs


def describe_simulation_capabilities() -> Dict[str, object]:
    return {
        "version": hydrosim_config.__version__,
        "station_count": len(hydrosim_config.POWER_CONFIGS),
        "station_names": hydrosim_config.list_station_names(),
        "modes": ["random_signal_simulation", "configured_simulation"],
        "outputs": [
            "formal_results_csv",
            "dispatch_min_p_json",
            "simulation_report_md",
            "configured_outputs_yaml",
            "run_summary_json",
        ],
        "api_interfaces": [
            "initialize",
            "inject_operating_conditions",
            "get_station_power_planning_series",
            "execute_step",
            "cancel",
            "get_session_info",
        ],
    }


def run_random_simulation(
    request: HydroRandomSimulationRequest | None = None,
    output_mode: HydroOutputMode = "mixed",
    service: HydroSimulationService | None = None,
    **kwargs,
) -> Dict[str, Any]:
    api = HydroSimulationApi(service=service)
    return api.run_random(request=request, output_mode=output_mode, **kwargs)


def run_configured_simulation(
    request: HydroConfiguredSimulationRequest | None = None,
    output_mode: HydroOutputMode = "mixed",
    service: HydroSimulationService | None = None,
    input_bundle: HydroSimulationInputBundle | dict[str, Any] | None = None,
) -> Dict[str, Any]:
    api = HydroSimulationApi(service=service)
    return api.run_configured(request=request, output_mode=output_mode, input_bundle=input_bundle)


