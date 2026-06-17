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

from hydrosim import config as hydrosim_config
from hydrosim import (
    HydroConfiguredSimulationRequest,
    HydroOutputMode,
    HydroRandomSimulationRequest,
    HydroSimulationArtifacts,
    HydroSimulationService,
)

__all__ = [
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

        session.latest_power_planning_file = str(Path(time_series_power_planning_file).resolve())
        session.latest_station_power_series = station_power_series
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
        time_series_power_planning_file: str | None = None,
    ) -> Dict[str, Any]:
        """每步执行接口。

        用法：
        - 如果已生成规划结果，则按顺序返回下一步各站点出力
        - 如果传入 `step_index`，则返回指定步
        - 如果传入 `time_series_power_planning_file`，会先生成最新规划结果再返回步进结果
        """

        session = self._require_session()
        if time_series_power_planning_file is not None:
            self.get_station_power_planning_series(time_series_power_planning_file)
            session = self._require_session()
        if session.cancelled:
            raise RuntimeError("当前会话已取消，不能继续执行步进。")
        if not session.latest_station_power_series:
            raise RuntimeError("当前会话尚未生成规划结果，请先调用获取规划出力时间序列接口。")

        target_step = session.current_step_index if step_index is None else int(step_index)
        station_step_outputs = []
        total_steps = 0
        for station in session.latest_station_power_series:
            series = station.get("time_series", [])
            total_steps = max(total_steps, len(series))
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

        if step_index is None:
            session.current_step_index = target_step + 1

        return {
            "message": "步进执行成功。",
            "session": session.to_dict(),
            "current_step_index": target_step,
            "has_next_step": target_step + 1 < total_steps,
            "station_step_outputs": station_step_outputs,
        }

    def cancel(self) -> Dict[str, Any]:
        """取消接口。

        调用后会将当前会话标记为已取消，并清空最近一次规划结果。
        """

        session = self._require_session()
        session.cancelled = True
        session.latest_station_power_series = []
        session.latest_power_planning_file = None
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
