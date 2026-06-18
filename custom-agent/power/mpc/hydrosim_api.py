from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_snake

from hydrosim import config as hydrosim_config
from hydrosim import (
    HydroConfiguredSimulationRequest,
    HydroOutputMode,
    HydroRandomSimulationRequest,
    HydroSimulationArtifacts,
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
    time_series_file: str
    mpc_config_file: str
    initial_states_file: str
    constraints_file: str
    latest_power_planning_file: str | None = None
    latest_station_power_series: List[Dict[str, Any]] = field(default_factory=list)
    latest_device_output_series: List[Dict[str, Any]] = field(default_factory=list)
    step_runtime: "HydroSimulationStepRuntime | None" = None
    current_step_index: int = 0
    cancelled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "time_series_file": self.time_series_file,
            "mpc_config_file": self.mpc_config_file,
            "initial_states_file": self.initial_states_file,
            "constraints_file": self.constraints_file,
            "latest_power_planning_file": self.latest_power_planning_file,
            "current_step_index": self.current_step_index,
            "cancelled": self.cancelled,
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
        self._session: HydroSimulationSession | None = None

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
        **kwargs,
    ) -> Dict[str, Any]:
        """执行配置驱动仿真。"""
        return self.service.run_configured(request=request, output_mode=output_mode, **kwargs)

    def initialize(
        self,
        time_series_file: str,
        mpc_config_file: str = "mpc_config.yaml",
        initial_states_file: str = "initial_states.yaml",
        constraints_file: str = "constrains_targets.yaml",
    ) -> Dict[str, Any]:
        """算法初始化接口。

        入参：
        - `time_series_file`：基础工况时间序列文件
        - `mpc_config_file`：MPC 配置文件
        - `initial_states_file`：初始状态文件
        - `constraints_file`：约束条件文件

        返回：
        - 会话 ID
        - 初始化后的文件路径
        - 基础时间轴长度
        - 电站能力摘要
        """

        event = self._load_json_file(time_series_file, "基础时间序列文件")
        self._load_yaml_file(mpc_config_file, "MPC 配置文件")
        self._load_yaml_file(initial_states_file, "初始状态文件")
        self._load_yaml_file(constraints_file, "约束文件")

        steps = self.service.core.runtime._time_axis_from_event(event)
        self._session = HydroSimulationSession(
            session_id=uuid.uuid4().hex,
            time_series_file=str(Path(time_series_file).resolve()),
            mpc_config_file=str(Path(mpc_config_file).resolve()),
            initial_states_file=str(Path(initial_states_file).resolve()),
            constraints_file=str(Path(constraints_file).resolve()),
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
        time_series_file: str | None = None,
        mpc_config_file: str | None = None,
        initial_states_file: str | None = None,
        constraints_file: str | None = None,
    ) -> Dict[str, Any]:
        """注入工况接口。

        用于在已初始化会话中替换基础工况文件或约束配置。
        调用后会清空上一次规划结果，并将步进游标重置为 0。
        """

        session = self._require_session()
        if time_series_file is not None:
            self._load_json_file(time_series_file, "基础时间序列文件")
            session.time_series_file = str(Path(time_series_file).resolve())
        if mpc_config_file is not None:
            self._load_yaml_file(mpc_config_file, "MPC 配置文件")
            session.mpc_config_file = str(Path(mpc_config_file).resolve())
        if initial_states_file is not None:
            self._load_yaml_file(initial_states_file, "初始状态文件")
            session.initial_states_file = str(Path(initial_states_file).resolve())
        if constraints_file is not None:
            self._load_yaml_file(constraints_file, "约束文件")
            session.constraints_file = str(Path(constraints_file).resolve())

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

    def get_station_power_planning_series(self, time_series_power_planning_file: str) -> Dict[str, Any]:
        """获取规划出力时间序列接口。

        入参：
        - `time_series_power_planning_file`：发电需求时间序列文件

        返回：
        - 各个站点的出力时间序列
        - 对应的运行摘要
        - 当前会话信息
        """

        session = self._require_session()
        base_event = self._load_json_file(session.time_series_file, "基础时间序列文件")
        planning_payload = self._load_json_file(time_series_power_planning_file, "发电需求时间序列文件")
        merged_event = self._merge_event_with_power_plan(base_event, planning_payload)

        with tempfile.TemporaryDirectory(prefix="hydrosim_api_") as temp_dir:
            merged_event_path = Path(temp_dir) / "merged_time_series_power_planning.json"
            with open(merged_event_path, "w", encoding="utf-8") as handle:
                json.dump(merged_event, handle, ensure_ascii=False, indent=2)

            with contextlib.redirect_stdout(io.StringIO()):
                result = self.run_configured(
                    time_series_file=str(merged_event_path),
                    mpc_config_file=session.mpc_config_file,
                    initial_states_file=session.initial_states_file,
                    constraints_file=session.constraints_file,
                    output_mode="mixed",
                    output_dir=temp_dir,
                    make_plots=False,
                    progress_interval=0,
                )

            files = result["files"]
            run_summary = result["json"]["run_summary"]
            station_power_series = self._extract_station_power_series_from_yaml(files["configured_outputs_yaml"])
            device_output_series = self._extract_device_output_series_from_yaml(files["configured_outputs_yaml"])

        session.latest_power_planning_file = str(Path(time_series_power_planning_file).resolve())
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
                "metrics_code": "power",
                "value": float(planning_values_by_node[node_id]),
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
                    "power": float(row["value"]),
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
            if object_type != "Station" or metrics_code != "power":
                raise ValueError("current_step_power_planning_values 仅支持 Station/power 规划出力数据。")
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
        initial_states = self._load_yaml_file(session.initial_states_file, "初始状态文件")
        constraints = self._load_yaml_file(session.constraints_file, "约束文件")
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
                    "power": float(station.history["current_power"][-1]),
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
                        "value": float(series[-1]),
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

    def _load_json_file(self, path: str, label: str) -> Dict[str, Any]:
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            raise FileNotFoundError(f"{label}不存在: {path_obj}")
        with open(path_obj, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_yaml_file(self, path: str, label: str) -> Dict[str, Any]:
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            raise FileNotFoundError(f"{label}不存在: {path_obj}")
        with open(path_obj, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _merge_event_with_power_plan(self, base_event: Dict[str, Any], planning_payload: Dict[str, Any]) -> Dict[str, Any]:
        planning_series = self._extract_station_power_items(planning_payload)
        if not planning_series:
            raise ValueError("发电需求时间序列文件中未找到 Station/power 时间序列。")

        merged_event = copy.deepcopy(base_event)
        object_time_series = list(merged_event.get("object_time_series", []) or [])
        object_time_series = [item for item in object_time_series if not self._is_station_power_item(item)]
        object_time_series.extend(copy.deepcopy(planning_series))
        merged_event["object_time_series"] = object_time_series
        return merged_event

    def _extract_station_power_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(payload.get("object_time_series"), list):
            items = payload["object_time_series"]
        elif isinstance(payload.get("objectTimeSeries"), list):
            items = payload["objectTimeSeries"]
        else:
            items = []
        return [item for item in items if self._is_station_power_item(item)]

    def _is_station_power_item(self, item: Dict[str, Any]) -> bool:
        return item.get("object_type") == "Station" and item.get("metrics_code") == "power"

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
                        {"step": int(row["step"]), "value": float(row["value"])}
                        for row in item.get("time_series", [])
                    ],
                }
                for item in station_power_plan_used
            ]

        station_names = hydrosim_config.build_station_name_map()
        result = []
        for item in payload.get("object_time_series", []) or []:
            if item.get("object_type") != "Station" or item.get("metrics_code") != "power":
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
                        {"step": int(row["step"]), "value": float(row["value"])}
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
            if metrics_code not in {"power", "water_flow", "gate_opening"}:
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
                        {"step": int(row["step"]), "value": float(row["value"])}
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
                    "value": float(row["value"]),
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
    **kwargs,
) -> Dict[str, Any]:
    api = HydroSimulationApi(service=service)
    return api.run_configured(request=request, output_mode=output_mode, **kwargs)
