from __future__ import annotations

import csv
import datetime
import json
import math
import os
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import yaml

from . import runtime as default_runtime
from .types import (
    HydroSimulationArtifacts,
    HydroSimulationFileOutputs,
    HydroSimulationJsonOutputs,
)


class HydroSimulationResultFactory:
    """负责仿真结果的导出、汇总与结果对象构造。"""

    def __init__(self, runtime: Any | None = None) -> None:
        self.runtime = runtime or default_runtime
        self.version = self.runtime.__version__

    def export_dispatch_min_p(self, output_dir: str, multi_stair: Any) -> str:
        dispatch_min_p = multi_stair.dispatch_min_p_report()
        print("=" * 72)
        print("调度最小单位P（重点）")
        print("=" * 72)
        for row in dispatch_min_p:
            print(
                f"- {row['station']}: "
                f"站间最小单位P={row['inter_station_min_p_mw']:.2f} MW, "
                f"站内最小单位P={row['intra_station_min_p_mw']:.2f} MW"
            )
        min_p_path = os.path.join(output_dir, f"dispatch_min_p_v{self.version.split('.')[0]}.json")
        with open(min_p_path, "w", encoding="utf-8") as handle:
            json.dump(dispatch_min_p, handle, ensure_ascii=False, indent=2)
        print(f"最小单位P配置文件: {min_p_path}")
        return min_p_path

    def stage_zone_summary(self, multi_reservoir: Any) -> List[Dict]:
        summary: List[Dict] = []
        for i, res in enumerate(multi_reservoir.Capacity_Stairs):
            counts = {"green": 0, "yellow": 0, "red": 0}
            for stage in res.history["current_stage"]:
                state = multi_reservoir.stage_state(i, stage=float(stage))
                counts[state["zone"]] += 1
            summary.append(
                {
                    "station": res.name,
                    "green_points": counts["green"],
                    "yellow_points": counts["yellow"],
                    "red_points": counts["red"],
                    "total_points": sum(counts.values()),
                }
            )
        return summary

    def export_formal_results_csv(
        self,
        output_dir: str,
        flows_in: np.ndarray,
        power_cmd: np.ndarray,
        warm_steps: int,
        multi_stair: Any,
        multi_reservoir: Any,
    ) -> str:
        if len(flows_in) != len(power_cmd):
            raise ValueError("flows_in 与 power_cmd 长度不一致。")
        if warm_steps < 0 or warm_steps >= len(flows_in):
            raise ValueError("warm_steps 超出信号范围。")
        if multi_stair.num_stairs != len(multi_reservoir.Capacity_Stairs):
            raise ValueError("电站数与水库数不一致。")

        formal_steps = len(flows_in) - warm_steps
        if formal_steps <= 0:
            raise ValueError("正式仿真步数必须 > 0。")

        for i in range(multi_stair.num_stairs):
            sta = multi_stair.multi_stair[i]
            res = multi_reservoir.Capacity_Stairs[i]
            if len(sta.history["current_power"]) != formal_steps:
                raise ValueError(f"{sta.name}: 电站历史步数与正式仿真步数不一致。")
            if len(res.history["current_outflow_discharge"]) != formal_steps:
                raise ValueError(f"{res.name}: 水库历史步数与正式仿真步数不一致。")
            for unit in sta.multi_station:
                if len(unit.history["current_power"]) != formal_steps:
                    raise ValueError(f"{sta.name}/{unit.unit_name}: 机组历史步数与正式仿真步数不一致。")

        station_infos = []
        for i, station in enumerate(multi_stair.multi_stair):
            station_token = f"st{i + 1}_{self._csv_token(station.name)}"
            station_infos.append(
                {
                    "station": station,
                    "reservoir": multi_reservoir.Capacity_Stairs[i],
                    "station_token": station_token,
                    "station_p_hist": station.history["current_power"],
                    "station_q_hist": station.history["flow"],
                    "spill_hist": multi_reservoir.Capacity_Stairs[i].history["current_outflow_discharge"],
                    "stage_hist": multi_reservoir.Capacity_Stairs[i].history["current_stage"],
                    "units": [
                        {
                            "unit_token": f"u{j + 1}_{self._csv_token(unit.unit_name)}",
                            "p_hist": unit.history["current_power"],
                            "q_hist": unit.history["flow"],
                            "n_hist": unit.history["efficiency"],
                        }
                        for j, unit in enumerate(station.multi_station)
                    ],
                }
            )

        csv_path = os.path.join(output_dir, f"formal_results_v{self.version.split('.')[0]}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            header = ["formal_step", "global_step", "upstream_inflow_m3s", "total_dispatch_cmd_mw"]

            for info in station_infos:
                station_token = info["station_token"]
                header.extend(
                    [
                        f"{station_token}_station_p_mw",
                        f"{station_token}_station_q_m3s",
                        f"{station_token}_spill_qout_m3s",
                        f"{station_token}_reservoir_stage_m",
                        f"{station_token}_stage_delta_m",
                        f"{station_token}_stage_zone",
                        f"{station_token}_stage_direction",
                    ]
                )

            for info in station_infos:
                station_token = info["station_token"]
                for unit_info in info["units"]:
                    unit_token = unit_info["unit_token"]
                    header.extend(
                        [
                            f"{station_token}_{unit_token}_p_mw",
                            f"{station_token}_{unit_token}_q_m3s",
                            f"{station_token}_{unit_token}_n_efficiency",
                        ]
                    )

            writer.writerow(header)

            for k in range(formal_steps):
                global_idx = warm_steps + k
                row = [k, global_idx, float(flows_in[global_idx]), float(power_cmd[global_idx])]

                for station_idx, info in enumerate(station_infos):
                    zone_state = multi_reservoir.stage_state(station_idx, stage=float(info["stage_hist"][k]))
                    row.extend(
                        [
                            float(info["station_p_hist"][k]),
                            float(info["station_q_hist"][k]),
                            float(info["spill_hist"][k]),
                            float(zone_state["stage"]),
                            float(zone_state["delta"]),
                            zone_state["zone"],
                            float(zone_state["direction"]),
                        ]
                    )

                for info in station_infos:
                    for unit_info in info["units"]:
                        row.extend(
                            [
                                float(unit_info["p_hist"][k]),
                                float(unit_info["q_hist"][k]),
                                float(unit_info["n_hist"][k]),
                            ]
                        )

                writer.writerow(row)

        return csv_path

    def export_configured_outputs_yaml(
        self,
        output_dir: str,
        event: Dict,
        constraints: Dict,
        steps: np.ndarray,
        warm_steps: int,
        flows_in: np.ndarray,
        power_cmd: np.ndarray,
        station_power_plan: Dict[int, np.ndarray],
        multi_stair: Any,
        multi_reservoir: Any,
        sample_interval: int = 15,
    ) -> str:
        formal_steps = steps[warm_steps:]
        control_domains = constraints.get("control_domains", []) or []
        station_names = self.runtime._station_name_by_node()

        series_items: List[Dict] = []
        seen_station_keys: set[Tuple[Tuple[int, ...], str]] = set()
        for item in event.get("object_time_series", []):
            if item.get("object_type") != "Station":
                continue
            ids = tuple(node_id for node_id in self.runtime._object_ids(item) if node_id in self.runtime.NODE_TO_INDEX)
            metric = str(item.get("metrics_code", ""))
            if not ids or not metric:
                continue
            seen_station_keys.add((ids, metric))
            if metric == "power" and len(ids) > 1:
                values = np.zeros(len(formal_steps), dtype=float)
                for node_id in ids:
                    values += np.asarray(multi_stair.multi_stair[self.runtime.NODE_TO_INDEX[node_id]].history["current_power"], dtype=float)
            else:
                values = np.zeros(len(formal_steps), dtype=float)
                for node_id in ids:
                    values += np.asarray(
                        self._station_output_series(node_id, metric, flows_in, power_cmd, warm_steps, multi_stair, multi_reservoir),
                        dtype=float,
                    )
            series_items.append(
                {
                    "time_series_name": item.get("time_series_name", f"result_{metric}"),
                    "object_ids": list(ids),
                    "object_type": "Station",
                    "object_name": item.get("object_name") or "+".join(station_names[node_id] for node_id in ids),
                    "metrics_code": metric,
                    "source": "simulation_result",
                    "time_series": self._make_time_series_rows(formal_steps, values, sample_interval),
                }
            )

        for node_id in self.runtime.STATION_NODE_IDS:
            for metric in ("water_level", "water_flow", "power"):
                key = ((node_id,), metric)
                if key in seen_station_keys:
                    continue
                values = self._station_output_series(node_id, metric, flows_in, power_cmd, warm_steps, multi_stair, multi_reservoir)
                series_items.append(
                    {
                        "time_series_name": f"{station_names[node_id]}_{metric}_simulation_result",
                        "object_ids": [node_id],
                        "object_type": "Station",
                        "object_name": station_names[node_id],
                        "metrics_code": metric,
                        "source": "simulation_result",
                        "time_series": self._make_time_series_rows(formal_steps, values, sample_interval),
                    }
                )

        seen_devices: set[Tuple[int, str]] = set()
        for row in control_domains:
            if row.get("device_id") is None:
                continue
            device_id = int(row["device_id"])
            control_type = str(row.get("type", ""))
            metric = "power" if control_type == "Turbine" else "gate_opening"
            key = (device_id, metric)
            if key in seen_devices:
                continue
            seen_devices.add(key)
            values = self._control_domain_device_series(device_id, metric, control_type, control_domains, multi_stair, multi_reservoir)
            if not values:
                continue
            series_items.append(
                {
                    "time_series_name": f"device_{device_id}_{metric}_simulation_result",
                    "object_ids": [device_id],
                    "object_type": control_type,
                    "object_name": f"device_{device_id}",
                    "metrics_code": metric,
                    "node_id": int(row.get("node_id")),
                    "source": "simulation_result",
                    "time_series": self._make_time_series_rows(formal_steps, values, sample_interval),
                }
            )

        result = {
            "hydro_event_type": "SIMULATION_RESULT_UPDATED",
            "hydro_event_id": f"{event.get('hydro_event_id', 'UNKNOWN')}_V16_RESULT",
            "hydro_event_name": f"{event.get('hydro_event_name', 'hydro_event')}_V16仿真结果",
            "version": self.version,
            "step_unit": "minute",
            "formal_step_start": int(formal_steps[0]) if len(formal_steps) else 0,
            "formal_step_end": int(formal_steps[-1]) if len(formal_steps) else 0,
            "object_time_series": series_items,
            "station_power_plan_used": [
                {
                    "node_id": node_id,
                    "station": station_names[node_id],
                    "time_series": self._make_time_series_rows(formal_steps, values[warm_steps:], sample_interval),
                }
                for node_id, values in station_power_plan.items()
            ],
            "valid": True,
        }

        path = os.path.join(output_dir, "configured_outputs_v16.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(result, handle, allow_unicode=True, sort_keys=False)
        return path

    def export_run_summary_json_v16(
        self,
        output_dir: str,
        event_path: str,
        mpc_config_path: str,
        initial_states_path: str,
        constraints_path: str,
        sim_steps: int,
        warm_steps: int,
        elapsed_seconds: float,
        csv_path: str,
        yaml_path: str,
        stage_zone_summary: Sequence[Dict],
    ) -> str:
        summary = {
            "version": self.version,
            "mode": "configured_time_series",
            "inputs": {
                "event_json": os.path.abspath(event_path),
                "mpc_config_yaml": os.path.abspath(mpc_config_path),
                "initial_states_yaml": os.path.abspath(initial_states_path),
                "constraints_targets_yaml": os.path.abspath(constraints_path),
            },
            "sim_steps": int(sim_steps),
            "warm_steps": int(warm_steps),
            "elapsed_seconds": float(elapsed_seconds),
            "outputs": {
                "formal_results_csv": os.path.abspath(csv_path),
                "configured_outputs_yaml": os.path.abspath(yaml_path),
            },
            "stage_zone_summary": list(stage_zone_summary),
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        path = os.path.join(output_dir, "run_summary_v16.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        return path

    def export_run_summary_json(
        self,
        output_dir: str,
        sim_steps: int,
        warm_steps: int,
        flow_seed: int,
        power_seed: int,
        flow_range: Tuple[float, float],
        power_range: Tuple[float, float],
        make_plots: bool,
        elapsed_seconds: float,
        csv_path: str,
        min_p_path: str,
        report_path: str,
        stage_zone_summary: Sequence[Dict],
    ) -> str:
        summary = {
            "version": self.version,
            "sim_steps": int(sim_steps),
            "warm_steps": int(warm_steps),
            "flow_seed": int(flow_seed),
            "power_seed": int(power_seed),
            "flow_range": [float(flow_range[0]), float(flow_range[1])],
            "power_range": [float(power_range[0]), float(power_range[1])],
            "make_plots": bool(make_plots),
            "elapsed_seconds": float(elapsed_seconds),
            "outputs": {
                "formal_results_csv": os.path.abspath(csv_path),
                "dispatch_min_p_json": os.path.abspath(min_p_path),
                "simulation_report_md": os.path.abspath(report_path),
            },
            "output_dir": os.path.abspath(output_dir),
            "stage_zone_summary": list(stage_zone_summary),
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        path = os.path.join(output_dir, f"run_summary_v{self.version.split('.')[0]}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        return path

    def export_simulation_report_md(
        self,
        output_dir: str,
        sim_steps: int,
        warm_steps: int,
        flow_seed: int,
        power_seed: int,
        flow_range: Tuple[float, float],
        power_range: Tuple[float, float],
        make_plots: bool,
        elapsed_seconds: float,
        csv_path: str,
        min_p_path: str,
        stage_zone_summary: Sequence[Dict],
        multi_stair: Any,
        multi_reservoir: Any,
    ) -> str:
        report_path = os.path.join(output_dir, f"simulation_report_v{self.version.split('.')[0]}.md")
        generated_at = datetime.datetime.now().isoformat(timespec="seconds")
        total_zone_points = sum(int(row["total_points"]) for row in stage_zone_summary)
        total_red = sum(int(row["red_points"]) for row in stage_zone_summary)
        total_yellow = sum(int(row["yellow_points"]) for row in stage_zone_summary)
        total_green = sum(int(row["green_points"]) for row in stage_zone_summary)

        lines = [
            f"# HydroSim V{self.version.split('.')[0]} 仿真汇总报告",
            "",
            "## 运行信息",
            "",
            f"- 版本：V{self.version}",
            f"- 生成时间：{generated_at}",
            f"- 预热步数：{warm_steps}",
            f"- 正式仿真步数：{sim_steps}",
            f"- 上游来流范围：{flow_range[0]:.2f} ~ {flow_range[1]:.2f} m^3/s",
            f"- 总出力指令范围：{power_range[0]:.2f} ~ {power_range[1]:.2f} MW",
            f"- 来流随机种子：{flow_seed}",
            f"- 出力随机种子：{power_seed}",
            f"- 是否生成图像：{'是' if make_plots else '否'}",
            f"- 总耗时：{elapsed_seconds:.2f} s",
            "",
            "## 输出文件",
            "",
            f"- 正式结果 CSV：`{os.path.abspath(csv_path)}`",
            f"- 调度最小单位配置：`{os.path.abspath(min_p_path)}`",
            f"- 本报告：`{os.path.abspath(report_path)}`",
            "",
            "## 分区情况汇总",
            "",
            "| 电站/水库 | Green 点数 | Yellow 点数 | Red 点数 | Green 占比 | Yellow 占比 | Red 占比 | 总点数 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]

        for row in stage_zone_summary:
            total = int(row["total_points"])
            green = int(row["green_points"])
            yellow = int(row["yellow_points"])
            red = int(row["red_points"])
            lines.append(
                f"| {row['station']} | {green} | {yellow} | {red} | "
                f"{self._format_pct(green, total)} | {self._format_pct(yellow, total)} | {self._format_pct(red, total)} | {total} |"
            )

        lines.extend(
            [
                "",
                f"- 总 Green 点数：{total_green} / {total_zone_points} ({self._format_pct(total_green, total_zone_points)})",
                f"- 总 Yellow 点数：{total_yellow} / {total_zone_points} ({self._format_pct(total_yellow, total_zone_points)})",
                f"- 总 Red 点数：{total_red} / {total_zone_points} ({self._format_pct(total_red, total_zone_points)})",
                "",
                "## 电站出力与流量指标",
                "",
                "| 电站 | 出力最小值(MW) | 出力最大值(MW) | 出力平均值(MW) | 末步出力(MW) | 发电流量平均值(m^3/s) |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )

        for station in multi_stair.multi_stair:
            power = self._series_stats(station.history["current_power"])
            flow = self._series_stats(station.history["flow"])
            lines.append(
                f"| {station.name} | {power['min']:.3f} | {power['max']:.3f} | {power['avg']:.3f} | "
                f"{power['end']:.3f} | {flow['avg']:.3f} |"
            )

        guard_history = multi_stair.history["low_stage_guard"]
        guard_active = sum(1 for item in guard_history if item.get("active"))
        max_unserved = max((float(item.get("unserved_mw", 0.0)) for item in guard_history), default=0.0)
        lines.extend(
            [
                "",
                "## 低水位保护情况",
                "",
                f"- 低水位保护触发步数：{guard_active}",
                f"- 最大未满足出力：{max_unserved:.3f} MW",
                "",
            ]
        )

        with open(report_path, "w", encoding="utf-8-sig") as handle:
            handle.write("\n".join(lines))
        return report_path

    def build_random_artifacts(
        self,
        output_dir: str,
        formal_results_csv: str,
        min_p_path: str,
        report_path: str,
        summary_path: str,
        multi_stair: Any,
    ) -> HydroSimulationArtifacts:
        return HydroSimulationArtifacts(
            files=HydroSimulationFileOutputs(
                output_dir=os.path.abspath(output_dir),
                formal_results_csv=os.path.abspath(formal_results_csv),
                dispatch_min_p_json=os.path.abspath(min_p_path),
                simulation_report_md=os.path.abspath(report_path),
                run_summary_json=os.path.abspath(summary_path),
            ),
            json=HydroSimulationJsonOutputs(
                run_summary=self._read_json_file(summary_path),
                dispatch_min_p=self._read_json_file(min_p_path),
                extra={"unit_outputs": self.build_unit_output_data(multi_stair)},
            ),
        )

    def build_configured_artifacts(
        self,
        output_dir: str,
        formal_results_csv: str,
        configured_outputs_yaml: str,
        summary_path: str,
        multi_stair: Any,
    ) -> HydroSimulationArtifacts:
        return HydroSimulationArtifacts(
            files=HydroSimulationFileOutputs(
                output_dir=os.path.abspath(output_dir),
                formal_results_csv=os.path.abspath(formal_results_csv),
                configured_outputs_yaml=os.path.abspath(configured_outputs_yaml),
                run_summary_json=os.path.abspath(summary_path),
            ),
            json=HydroSimulationJsonOutputs(
                run_summary=self._read_json_file(summary_path),
                extra={"unit_outputs": self.build_unit_output_data(multi_stair)},
            ),
        )

    def build_unit_output_data(self, multi_stair: Any) -> Dict[str, Any]:
        stations = []
        for station in multi_stair.multi_stair:
            units = []
            for unit in station.multi_station:
                units.append(
                    {
                        "unit_id": int(unit.unit_id),
                        "unit_name": str(unit.unit_name),
                        "time": [int(step) for step in unit.history["time"]],
                        "current_power": [float(value) for value in unit.history["current_power"]],
                        "target_power": [float(value) for value in unit.history["target_power"]],
                    }
                )
            stations.append(
                {
                    "station_id": int(station.id),
                    "station_name": str(station.name),
                    "units": units,
                }
            )
        return {"stations": stations}

    def _station_output_series(
        self,
        node_id: int,
        metric: str,
        flows_in: np.ndarray,
        power_cmd: np.ndarray,
        warm_steps: int,
        multi_stair: Any,
        multi_reservoir: Any,
    ) -> Sequence[float]:
        idx = self.runtime.NODE_TO_INDEX[node_id]
        if metric == "water_level":
            return multi_reservoir.Capacity_Stairs[idx].history["current_stage"]
        if metric == "water_flow":
            if idx == 0:
                return flows_in[warm_steps:]
            return multi_reservoir.Capacity_Stairs[idx].history["current_inflow"]
        if metric == "power":
            return multi_stair.multi_stair[idx].history["current_power"]
        if metric == "outflow":
            return multi_reservoir.Capacity_Stairs[idx].history["current_outflow"]
        raise ValueError(f"不支持的 Station 指标: {metric}")

    def _control_domain_device_series(
        self,
        device_id: int,
        metric: str,
        control_type: str,
        control_domains: Sequence[Dict],
        multi_stair: Any,
        multi_reservoir: Any,
    ) -> Sequence[float]:
        node_id = self.runtime._infer_station_node_for_device(device_id)
        if node_id is None:
            return []
        station_idx = self.runtime.NODE_TO_INDEX[node_id]

        if control_type == "Turbine" and metric in ("power", "turbine_power"):
            turbine_ids = [
                int(row["device_id"])
                for row in control_domains
                if int(row.get("node_id", -1)) == node_id and row.get("type") == "Turbine"
            ]
            unique_ids = []
            for turbine_id in turbine_ids:
                if turbine_id not in unique_ids:
                    unique_ids.append(turbine_id)
            if device_id not in unique_ids:
                return []
            unit_idx = unique_ids.index(device_id)
            units = multi_stair.multi_stair[station_idx].multi_station
            if unit_idx >= len(units):
                return []
            return units[unit_idx].history["current_power"]

        if control_type == "Gate" and metric in ("gate_opening", "opening"):
            gate_ids = [
                int(row["device_id"])
                for row in control_domains
                if int(row.get("node_id", -1)) == node_id and row.get("type") == "Gate"
            ]
            unique_ids = []
            for gate_id in gate_ids:
                if gate_id not in unique_ids:
                    unique_ids.append(gate_id)
            if not unique_ids or device_id not in unique_ids:
                return []
            reservoir = multi_reservoir.Capacity_Stairs[station_idx]
            max_opening = 5.0
            for row in control_domains:
                if int(row.get("device_id", -1)) == device_id:
                    max_opening = float(row.get("max_value", max_opening))
                    break
            spill = np.asarray(reservoir.history["current_outflow_discharge"], dtype=float)
            per_gate_q = spill / max(len(unique_ids), 1)
            opening = np.clip(
                per_gate_q / max(reservoir.max_spill_q / max(len(unique_ids), 1), 1e-9) * max_opening,
                0.0,
                max_opening,
            )
            return opening.tolist()

        return []

    def _make_time_series_rows(self, steps: Sequence[int], values: Sequence[float], sample_interval: int) -> List[Dict]:
        if sample_interval <= 0:
            sample_interval = 1
        rows = []
        for pos, (step, value) in enumerate(zip(steps, values)):
            if pos % sample_interval == 0 or pos == len(steps) - 1:
                rows.append({"step": int(step), "value": float(value)})
        return rows

    def _read_json_file(self, path: str) -> Any:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _csv_token(self, name: str) -> str:
        token = str(name).strip().replace(" ", "_")
        for ch in ',;/\\:*?"<>|':
            token = token.replace(ch, "_")
        return token or "unnamed"

    def _format_pct(self, count: int, total: int) -> str:
        if total <= 0:
            return "0.00%"
        return f"{count / total * 100.0:.2f}%"

    def _series_stats(self, values: Sequence[float]) -> Dict[str, float]:
        arr = np.asarray(values, dtype=float)
        if arr.size == 0:
            return {"min": math.nan, "max": math.nan, "avg": math.nan, "end": math.nan}
        return {
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "avg": float(np.mean(arr)),
            "end": float(arr[-1]),
        }
