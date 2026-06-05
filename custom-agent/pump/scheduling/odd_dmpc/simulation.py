from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from .environment import (
    RemoteHydraulicEnvironment,
    _chain_pairs,
    hidden_disturbance_at_step,
    simulate_basin_trajectory,
    _level_keys,
    _ordered_station_ids,
)
from .flow_service import FlowDepartService
from .local_controller import LocalController, StationControlContext
from .observers import DisturbanceObserverBank
from .odd_supervisor import ODDSupervisor
from .station_model import PumpStationModel
from .thread_client import RemoteThreadClient
from .types import LowerFeedback, RuntimeParameters, StationMemory, SystemConfig, TransferBundle
from .upper_scheduler import UpperScheduler


@dataclass
class ClosedLoopSimulation:
    system_config: SystemConfig
    demand_plan: pd.DataFrame
    runtime: RuntimeParameters
    hours: int = 72
    thread_client: Optional[RemoteThreadClient] = None

    def __post_init__(self) -> None:
        self.output_dir = Path(self.runtime.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.steps_dir = self.output_dir / "steps"
        if self.runtime.save_step_plots:
            self.steps_dir.mkdir(parents=True, exist_ok=True)
        self._logged_model_keys = set()
        self.flow_service = FlowDepartService(
            self.system_config,
            config_path=self.system_config.source_config_path,
        )
        self.environment = RemoteHydraulicEnvironment(
            self.system_config,
            self.demand_plan,
            self.runtime,
            client=self.thread_client,
        )
        self.initial_observation = self.environment.reset()
        self._log_initialization_summary()
        self._log(
            "扰动场景: "
            f"{self.environment.hidden_disturbance_scenario}，"
            f"可选={sorted(self.environment.hidden_disturbance_scenarios.keys())}"
        )
        self.observers = DisturbanceObserverBank(self.system_config, self.runtime)
        self.upper_scheduler = UpperScheduler(
            self.system_config,
            self.demand_plan,
            self.runtime,
            self.flow_service,
            self.environment.boundary_level_plan,
        )
        self.supervisor = ODDSupervisor(self.runtime)
        self.local_controller = LocalController(self.system_config, self.runtime, self.flow_service)
        self._default_available_units_map = {
            station.id: [unit.id for unit in station.units]
            for station in self.system_config.stations
        }
        self.unit_availability_scenarios = self._normalize_unit_availability_scenarios()
        self.unit_availability_scenario = self._resolve_active_unit_availability_scenario()
        self.available_units_map = {
            station_id: unit_ids[:]
            for station_id, unit_ids in self._default_available_units_map.items()
        }
        self._apply_unit_availability(hour=0, initialize=True)
        self.station_flow_history = {
            station.id: [(0.0, float(self.initial_observation.station_flows[station.id]))]
            for station in self.system_config.stations
        }
        for station in self.system_config.stations:
            self._log_station_setup(station)
        self.station_memories = self._initialize_station_memories()
        self._log("初始化完成")

    def _log(self, message: str) -> None:
        if self.runtime.console_verbose:
            print(message, flush=True)

    def _fmt(self, value: float) -> str:
        return f"{float(value):.{self.runtime.console_float_precision}f}"

    def _station_label(self, station_id: int) -> str:
        station = self.system_config.station_by_id[station_id]
        return f"S{station_id} {station.remote_name or station.name}"

    def _format_unit_state(
        self,
        unit_id: int,
        status: int,
        flow: float,
        opening: float,
        efficiency: Optional[float] = None,
    ) -> str:
        status_text = "开机" if int(status) == 1 else "停机"
        parts = [
            f"{unit_id}号机组",
            f"状态={status_text}",
            f"流量={self._fmt(flow)}",
            f"工况={self._fmt(opening)}",
        ]
        if efficiency is not None:
            parts.append(f"效率={self._fmt(efficiency)}")
        return "，".join(parts)

    def _translate_reason(self, reason: str) -> str:
        mapping = {
            "needs reconfiguration": "需要重构",
            "ODD2 fit below threshold": "ODD2拟合度低于阈值，切换重构",
            "attempt angle tuning": "先执行ODD2叶片角优化",
            "ODD3 threshold exceeded": "超过ODD3阈值，直接重构",
            "steady-state hold": "稳态保持",
            "fit above threshold": "拟合度满足要求",
            "fit below threshold": "拟合度低于阈值",
            "availability update": "机组可用性变化",
            "scheduled outage": "计划检修/停机",
        }
        return mapping.get(reason, reason)

    def _step_label(self, hour: int, lower_index: int = 0, lower_total: int = 1) -> str:
        del lower_index, lower_total
        return f"{hour:03d}"

    def _fmt_station_state(
        self,
        flow: float,
        back_level: float,
        front_level: float,
        head: Optional[float] = None,
    ) -> str:
        current_head = float(head if head is not None else back_level - front_level)
        return (
            f"Q={self._fmt(flow)}, "
            f"Zback={self._fmt(back_level)}, "
            f"Zfront={self._fmt(front_level)}, "
            f"H={self._fmt(current_head)}"
        )

    def _power_mw(self, flow: float, head: float, efficiency: Optional[float]) -> float:
        if efficiency is None or flow <= 0.0 or head <= 0.0:
            return 0.0
        efficiency_fraction = float(efficiency) / 100.0 if float(efficiency) > 1.0 else float(efficiency)
        if efficiency_fraction <= 0.0:
            return 0.0
        power_w = float(self.system_config.rho) * float(self.system_config.g) * float(flow) * float(head) / efficiency_fraction
        return float(power_w / 1.0e6)

    def _actual_unit_metrics(self, snapshot, station_id: int) -> Tuple[Dict[int, Dict[str, float]], float, float]:
        station_rows: Dict[int, Dict[str, float]] = {}
        weighted_efficiency = 0.0
        total_flow = 0.0
        total_power_mw = 0.0
        for unit in self.system_config.station_by_id[station_id].units:
            status = int(snapshot.unit_status[station_id].get(unit.id, 0))
            opening = float(snapshot.unit_openings[station_id].get(unit.id, 0.0))
            flow = float(snapshot.unit_flows[station_id].get(unit.id, 0.0))
            front_level = float(snapshot.unit_front_levels[station_id].get(unit.id, 0.0))
            back_level = float(snapshot.unit_back_levels[station_id].get(unit.id, 0.0))
            head = back_level - front_level
            efficiency = None
            power_mw = 0.0
            if status == 1 and flow > 0.0:
                efficiency = self.flow_service.estimate_unit_efficiency(
                    station_id=station_id,
                    unit_id=unit.id,
                    flow=flow,
                    head=head,
                )
                if efficiency is not None:
                    weighted_efficiency += float(efficiency) * flow
                    total_flow += flow
                    power_mw = self._power_mw(flow, head, efficiency)
                    total_power_mw += power_mw
            station_rows[unit.id] = {
                "status": status,
                "opening": opening,
                "flow": flow,
                "front_level": front_level,
                "back_level": back_level,
                "head": head,
                "efficiency": float(efficiency) if efficiency is not None else 0.0,
                "power_mw": float(power_mw),
            }
        station_efficiency = weighted_efficiency / total_flow if total_flow > 0.0 else 0.0
        return station_rows, float(station_efficiency), float(total_power_mw)

    def _log_initialization_summary(self) -> None:
        state = self.environment.get_internal_state()
        create_response = state.get("create_response") or {}
        snapshot = self.environment.current_snapshot
        if snapshot is None:
            return
        self._log("========== 远程仿真环境初始化 ==========")
        self._log(
            f"创建结果: message={create_response.get('message', '')}，"
            f"uuid={snapshot.thread_uuid}"
        )
        boundary_text = "，".join(
            f"{name}={self._fmt(snapshot.boundary_levels[name])}"
            for name in snapshot.boundary_levels
        )
        self._log(f"边界水位: {boundary_text}")
        level_keys = _level_keys(self.system_config)
        pool_text = "，".join(
            f"{level_keys[pool_id]}={self._fmt(snapshot.basin_levels.get(level_keys[pool_id], 0.0))}"
            for pool_id in self.system_config.pool_ids
            if pool_id < len(level_keys)
        )
        self._log(f"渠池代表水位: {pool_text}")
        self._log(
            "渠池动态蓄量面积(按远程断面 profile 识别，单位m²): "
            + "，".join(
                f"{level_keys[pool_id]}={self._fmt(self.environment.pool_areas.get(pool_id, 0.0))}"
                for pool_id in self.system_config.pool_ids
                if pool_id < len(level_keys)
            )
        )
        self._log(
            "对应水体体积(单位m³): "
            + "，".join(
                f"{level_keys[pool_id]}={self._fmt(snapshot.basin_volumes.get(pool_id, 0.0))}"
                for pool_id in self.system_config.pool_ids
            )
        )
        self._log(
            "断面折算结果: "
            + "；".join(
                f"{level_keys[pool_id]}平均水深={self._fmt(snapshot.basin_profiles[pool_id].representative_depth)}，"
                f"原始河表面积={self._fmt(snapshot.basin_profiles[pool_id].raw_surface_area)}"
                for pool_id in self.system_config.pool_ids
                if pool_id in snapshot.basin_profiles and pool_id < len(level_keys)
            )
        )
        for station in self.system_config.stations:
            station_id = station.id
            unit_rows, station_efficiency, station_power_mw = self._actual_unit_metrics(snapshot, station_id)
            self._log(
                f"{self._station_label(station_id)}: "
                f"总流量={self._fmt(snapshot.station_total_flows[station_id])}，"
                f"站前={self._fmt(snapshot.station_front_levels[station_id])}，"
                f"站后={self._fmt(snapshot.station_back_levels[station_id])}，"
                f"站效率={self._fmt(station_efficiency)}，"
                f"站功率={self._fmt(station_power_mw)}MW"
            )
            for unit in station.units:
                row = unit_rows[unit.id]
                self._log("  " + self._format_unit_state(
                    unit_id=unit.id,
                    status=int(row["status"]),
                    flow=float(row["flow"]),
                    opening=float(row["opening"]),
                    efficiency=float(row["efficiency"]),
                ))

    def _log_station_setup(self, station) -> None:
        unit_ids = self.available_units_map[station.id]
        observation = self.initial_observation
        self._log(
            f"{self._station_label(station.id)}已接入，"
            f"可用机组={unit_ids}，"
            f"初始总流量={self._fmt(observation.station_flows[station.id])}，"
            f"站前={self._fmt(observation.station_front_levels[station.id])}，"
            f"站后={self._fmt(observation.station_back_levels[station.id])}"
        )

    def _normalize_unit_availability_scenarios(self) -> Dict[str, Dict[int, List[Dict[str, object]]]]:
        scenarios: Dict[str, Dict[int, List[Dict[str, object]]]] = {
            "baseline": {station.id: [] for station in self.system_config.stations}
        }
        raw_scenarios = self.runtime.unit_availability_scenarios or {}
        valid_unit_ids = {
            station.id: {unit.id for unit in station.units}
            for station in self.system_config.stations
        }
        for scenario_name, station_payload in raw_scenarios.items():
            if not isinstance(station_payload, Mapping):
                raise ValueError(f"Invalid unit availability scenario payload: {scenario_name}")
            normalized_station_payload: Dict[int, List[Dict[str, object]]] = {
                station.id: [] for station in self.system_config.stations
            }
            for station in self.system_config.stations:
                raw_events = station_payload.get(str(station.id), station_payload.get(station.id, []))
                normalized_events: List[Dict[str, object]] = []
                for raw_event in raw_events:
                    start_hour = int(raw_event["start_hour"])
                    end_hour = int(raw_event["end_hour"])
                    available_unit_ids = sorted(int(unit_id) for unit_id in raw_event["available_unit_ids"])
                    if end_hour <= start_hour:
                        raise ValueError(
                            f"Invalid unit availability window for station {station.id}: "
                            f"{start_hour} -> {end_hour}"
                        )
                    if not available_unit_ids:
                        raise ValueError(f"Station {station.id} cannot have an empty available unit set")
                    invalid_ids = set(available_unit_ids) - valid_unit_ids[station.id]
                    if invalid_ids:
                        raise ValueError(
                            f"Invalid available unit ids for station {station.id}: {sorted(invalid_ids)}"
                        )
                    normalized_events.append(
                        {
                            "start_hour": start_hour,
                            "end_hour": end_hour,
                            "available_unit_ids": available_unit_ids,
                            "reason": str(raw_event.get("reason", "scheduled outage")),
                        }
                    )
                normalized_events.sort(key=lambda item: (int(item["start_hour"]), int(item["end_hour"])))
                normalized_station_payload[station.id] = normalized_events
            scenarios[str(scenario_name).lower()] = normalized_station_payload
        return scenarios

    def _resolve_active_unit_availability_scenario(self) -> str:
        if not self.runtime.unit_availability_enabled:
            return "baseline"
        scenario = str(self.runtime.unit_availability_active_scenario).lower()
        if scenario not in self.unit_availability_scenarios:
            raise ValueError(f"Unsupported unit availability scenario: {self.runtime.unit_availability_active_scenario}")
        self._log(
            f"机组可用性场景: {scenario}，"
            f"可选={sorted(self.unit_availability_scenarios.keys())}"
        )
        return scenario

    def _resolve_available_units_for_hour(self, station_id: int, hour: int) -> Tuple[List[int], str]:
        default_ids = self._default_available_units_map[station_id][:]
        if not self.runtime.unit_availability_enabled:
            return default_ids, ""
        active_events = self.unit_availability_scenarios[self.unit_availability_scenario].get(station_id, [])
        for event in active_events:
            if int(event["start_hour"]) <= hour < int(event["end_hour"]):
                return list(event["available_unit_ids"]), str(event.get("reason", "scheduled outage"))
        return default_ids, ""

    def _sync_station_memory_availability(self, station_id: int, available_unit_ids: List[int]) -> None:
        memory = self.station_memories[station_id]
        available_set = set(available_unit_ids)
        previous_status = memory.unit_status.copy()
        previous_openings = memory.unit_openings.copy()
        previous_adjust_age = memory.time_since_adjust.copy()
        previous_switch_age = memory.time_since_switch.copy()

        memory.unit_status = {
            unit_id: int(previous_status.get(unit_id, 0))
            for unit_id in available_unit_ids
        }
        memory.unit_openings = {
            unit_id: float(previous_openings.get(unit_id, 0.0))
            for unit_id in available_unit_ids
        }
        memory.time_since_adjust = {
            unit_id: int(previous_adjust_age.get(unit_id, self.runtime.station_memory_init_age))
            for unit_id in available_unit_ids
        }
        memory.time_since_switch = {
            unit_id: int(previous_switch_age.get(unit_id, self.runtime.station_memory_init_age))
            for unit_id in available_unit_ids
        }
        memory.active_unit_ids = [
            unit_id
            for unit_id in memory.active_unit_ids
            if unit_id in available_set and int(memory.unit_status.get(unit_id, 0)) == 1
        ]

    def _apply_unit_availability(
        self,
        hour: int,
        initialize: bool = False,
    ) -> Tuple[Dict[int, bool], Dict[int, str]]:
        changed: Dict[int, bool] = {}
        reasons: Dict[int, str] = {}
        for station in self.system_config.stations:
            available_ids, reason = self._resolve_available_units_for_hour(station.id, hour)
            previous_ids = self.available_units_map.get(station.id, self._default_available_units_map[station.id])
            changed_now = (tuple(previous_ids) != tuple(available_ids)) and not initialize
            self.available_units_map[station.id] = available_ids
            changed[station.id] = changed_now
            reasons[station.id] = reason
            if changed_now:
                self._sync_station_memory_availability(station.id, available_ids)
                self._log(
                    f"第{self._step_label(hour)}步，{self._station_label(station.id)}机组可用集更新为{available_ids}，"
                    f"原因={reason or '机组可用性变化'}"
                )
        return changed, reasons

    def _log_step_start(
        self,
        step_label: str,
        observation,
        disturbance_estimate: Dict[int, float],
        cumulative_last_station_flow: float,
    ) -> None:
        del disturbance_estimate, cumulative_last_station_flow
        self._log("")
        self._log(f"========== 第 {step_label} 步 | 线程 {observation.thread_uuid} ==========")

    def _log_upper_plan(self, step_label: str, upper_plan, cumulative_last_station_flow: float) -> None:
        total_target_volume = self.system_config.target_avg_flow_last_station * self.system_config.horizon_hours
        remaining_total_target = max(total_target_volume - cumulative_last_station_flow, 0.0)
        self._log("[上层MPC]")
        self._log(
            f"  末站剩余调水目标={self._fmt(remaining_total_target)}，"
            f"当前末站指令均值={self._fmt(upper_plan.target_last_station_flow)}，"
            f"当前末站模型起始流量={self._fmt(upper_plan.metadata.get('remaining_target_avg_flow_effective', 0.0))}，"
            f"剩余平均目标={self._fmt(upper_plan.metadata.get('remaining_target_avg_flow', 0.0))}，"
            f"重构站数={int(upper_plan.metadata.get('reconfigured_station_count', 0.0))}"
        )
        for station_id in self.system_config.station_ids:
            self._log(
                f"  {self._station_label(station_id)} | "
                f"{self._fmt_station_state(upper_plan.flow_refs[station_id][0], upper_plan.station_back_levels[station_id][0], upper_plan.station_front_levels[station_id][0], upper_plan.station_heads[station_id][0])} | "
                f"模型起始Q={self._fmt(upper_plan.effective_flow_refs[station_id][0])} | "
                f"预测效率={self._fmt(upper_plan.efficiency_refs[station_id][0])}"
            )

    def _log_station_decision(self, step_label: str, station, decision, action, flow_min: float, flow_max: float) -> None:
        del step_label, station, decision, action, flow_min, flow_max

    def _warn_out_of_range(self, step_label: str, observation, next_observation) -> None:
        """逐站检查实际扬程和实际流量是否超出缓存表范围，超出时打印 ⚠ 警告。

        - 扬程使用 observation（控制决策时的扬程），容差为 head_search_tolerance。
        - 流量使用 next_observation（实际执行后的站流量）。
        """
        tol = float(self.runtime.head_search_tolerance)
        for station_id in self.system_config.station_ids:
            available_ids = list(self.available_units_map.get(station_id) or [])
            if not available_ids:
                continue
            station_model = self.flow_service.get_station_model(station_id, available_ids)
            actual_head = float(observation.station_heads[station_id])
            actual_flow = float(next_observation.station_flows[station_id])
            chk = station_model.check_operating_point(
                head=actual_head,
                flow=actual_flow,
                head_tolerance=tol,
            )
            if chk["head_ok"] and chk["flow_ok"]:
                continue
            parts = []
            if not chk["head_ok"]:
                direction = "超上界" if chk["head_excess"] > 0 else "低于下界"
                parts.append(
                    f"扬程={self._fmt(actual_head)}m {direction}"
                    f" ({self._fmt(abs(chk['head_excess']))}m)"
                    f" 表格范围=[{self._fmt(chk['h_min'])},{self._fmt(chk['h_max'])}]m"
                    f" 容差±{self._fmt(tol)}m"
                )
            if not chk["flow_ok"]:
                direction = "超上界" if chk["flow_excess"] > 0 else "低于下界"
                parts.append(
                    f"流量={self._fmt(actual_flow)}m³/s {direction}"
                    f" ({self._fmt(abs(chk['flow_excess']))}m³/s)"
                    f" 表格范围=[{self._fmt(chk['q_min'])},{self._fmt(chk['q_max'])}]m³/s"
                )
            label = self._station_label(station_id)
            self._log(f"  ⚠ [第{step_label}步 {label}] 工况超出缓存表范围: {'; '.join(parts)}")

    def _log_step_result(
        self,
        step_label: str,
        upper_plan,
        transfer_bundles,
        lower_prediction_plan,
        lower_prediction,
        next_observation,
        decisions,
        actions,
        cumulative_last_station_flow: float,
        step_hours: float,
        actual_hidden_disturbance: Dict[int, float],
        visible_disturbance: Dict[int, float],
        actual_upper_flow_errors: Dict[int, float],
        actual_lower_flow_errors: Dict[int, float],
        actual_execution_errors: Dict[int, float],
    ) -> None:
        del step_label
        predicted_station_levels = lower_prediction["station_levels"][1]
        total_target_volume = self.system_config.target_avg_flow_last_station * self.system_config.horizon_hours
        delivered_after_step = cumulative_last_station_flow + next_observation.station_flows[self.system_config.last_station_id] * step_hours / max(self.system_config.dt_hours, 1e-9)
        remaining_total_target = max(total_target_volume - delivered_after_step, 0.0)
        self._log("[下层MPC]")
        for station in self.system_config.stations:
            station_id = station.id
            transfer_bundle = transfer_bundles[station_id]
            predicted_flow = lower_prediction_plan[station_id][0]
            predicted_back = (
                float(actions[station_id].predicted_back_level)
                if actions[station_id].predicted_back_level is not None
                else predicted_station_levels["station_back_levels"][station_id]
            )
            predicted_front = (
                float(actions[station_id].predicted_front_level)
                if actions[station_id].predicted_front_level is not None
                else predicted_station_levels["station_front_levels"][station_id]
            )
            predicted_head = (
                float(actions[station_id].predicted_head)
                if actions[station_id].predicted_head is not None
                else predicted_station_levels["station_heads"][station_id]
            )
            actual_flow = next_observation.station_flows[station_id]
            actual_back = next_observation.station_back_levels[station_id]
            actual_front = next_observation.station_front_levels[station_id]
            actual_head = next_observation.station_heads[station_id]
            ref_flow = transfer_bundle.reference_flow[0]
            ref_back = transfer_bundle.reference_back_level[0]
            ref_front = transfer_bundle.reference_front_level[0]
            unit_targets = []
            for unit in station.units:
                unit_targets.append(
                    self._format_unit_state(
                        unit_id=unit.id,
                        status=int(actions[station_id].unit_status.get(unit.id, 0)),
                        flow=float(actions[station_id].unit_flows.get(unit.id, 0.0)),
                        opening=float(actions[station_id].unit_openings.get(unit.id, 0.0)),
                    )
                )
            self._log(
                f"  {self._station_label(station_id)} | 模式={actions[station_id].mode} | "
                f"目标={self._fmt_station_state(ref_flow, ref_back, ref_front)} | "
                f"下层预测={self._fmt_station_state(predicted_flow, predicted_back, predicted_front, predicted_head)} | "
                f"预测偏差: dQ={self._fmt(predicted_flow - ref_flow)}，"
                f"dZ后={self._fmt(predicted_back - ref_back)}，"
                f"dZ前={self._fmt(predicted_front - ref_front)} | "
                f"原因={self._translate_reason(decisions[station_id].reason)}"
            )
            self._log("    机组目标: " + "；".join(unit_targets))
        self._log("[实际执行]")
        self._log(
            f"  末站累计调水量={self._fmt(delivered_after_step)}，"
            f"末站剩余目标={self._fmt(remaining_total_target)}，"
            f"渠池1扰动={self._fmt(actual_hidden_disturbance[1])}，"
            f"渠池2扰动={self._fmt(actual_hidden_disturbance[2])}，"
            f"观察器估计=({self._fmt(visible_disturbance[1])}, {self._fmt(visible_disturbance[2])})，"
            f"执行误差=({self._fmt(actual_execution_errors[1])}, {self._fmt(actual_execution_errors[2])}, {self._fmt(actual_execution_errors[3])})"
        )
        snapshot = self.environment.current_snapshot
        if snapshot is None:
            return
        for station in self.system_config.stations:
            station_id = station.id
            transfer_bundle = transfer_bundles[station_id]
            actual_unit_rows, station_efficiency, station_power_mw = self._actual_unit_metrics(snapshot, station_id)
            self._log(
                f"  {self._station_label(station_id)} | "
                f"{self._fmt_station_state(next_observation.station_flows[station_id], next_observation.station_back_levels[station_id], next_observation.station_front_levels[station_id], next_observation.station_heads[station_id])} | "
                f"上层偏差: dQ={self._fmt(actual_upper_flow_errors[station_id])}，"
                f"dZ后={self._fmt(next_observation.station_back_levels[station_id] - transfer_bundle.reference_back_level[0])}，"
                f"dZ前={self._fmt(next_observation.station_front_levels[station_id] - transfer_bundle.reference_front_level[0])} | "
                f"下层偏差={self._fmt(actual_lower_flow_errors[station_id])} | "
                f"执行误差={self._fmt(actual_execution_errors[station_id])} | "
                f"站效率={self._fmt(station_efficiency)} | "
                f"站功率={self._fmt(station_power_mw)}MW"
            )
            for unit in station.units:
                row = actual_unit_rows[unit.id]
                self._log("    " + self._format_unit_state(
                    unit_id=unit.id,
                    status=int(row["status"]),
                    flow=float(row["flow"]),
                    opening=float(row["opening"]),
                    efficiency=float(row["efficiency"]),
                ))

    def _build_station_model(self, station_id: int, available_ids: List[int]) -> PumpStationModel:
        key = (station_id, tuple(sorted(available_ids)))
        model = self.flow_service.get_station_model(station_id, available_ids)
        self._logged_model_keys.add(key)
        return model

    def _initialize_station_memories(self):
        observation = self.initial_observation
        snapshot = self.environment.current_snapshot
        if snapshot is None:
            raise RuntimeError("Environment snapshot unavailable during initialization")
        memories = {}
        for station in self.system_config.stations:
            model = self._build_station_model(station.id, self.available_units_map[station.id])
            available_ids = self.available_units_map[station.id]
            unit_status = {
                unit_id: int(snapshot.unit_status[station.id].get(unit_id, 0))
                for unit_id in available_ids
            }
            unit_openings = {
                unit_id: float(snapshot.unit_openings[station.id].get(unit_id, 0.0))
                for unit_id in available_ids
            }
            memories[station.id] = StationMemory(
                active_unit_ids=[unit_id for unit_id, status in unit_status.items() if status == 1],
                unit_openings=unit_openings,
                unit_status=unit_status,
                time_since_adjust={unit_id: self.runtime.station_memory_init_age for unit_id in available_ids},
                time_since_switch={unit_id: self.runtime.station_memory_init_age for unit_id in available_ids},
                last_selected_flow=float(observation.station_flows[station.id]),
                mode="ODD1",
            )
            self._log(
                f"{self._station_label(station.id)}记忆初始化完成，"
                f"开机机组={memories[station.id].active_unit_ids}，"
                f"上一时刻流量={self._fmt(memories[station.id].last_selected_flow)}"
            )
        return memories

    def _make_lower_feedback(self, actions, decisions, plans, reconfigured_stations) -> LowerFeedback:
        feasible_flow_ranges = {}
        execution_errors = {}
        for station_id, plan in plans.items():
            feasible_flow_ranges[station_id] = [float(plan["flow_min"]), float(plan["flow_max"])]
            execution_errors[station_id] = float(plan["execution_error"])
        return LowerFeedback(
            available_units_map={station_id: ids[:] for station_id, ids in self.available_units_map.items()},
            feasible_flow_ranges=feasible_flow_ranges,
            current_modes={station_id: action.mode for station_id, action in actions.items()},
            plan_execution_errors=execution_errors,
            reconfigured_stations={station_id: bool(reconfigured_stations.get(station_id, False)) for station_id in actions},
        )

    def _update_station_memory(self, station_id: int, action, snapshot) -> None:
        memory = self.station_memories[station_id]
        available_ids = self.available_units_map[station_id]
        actual_openings = {
            unit_id: float(snapshot.unit_openings[station_id].get(unit_id, 0.0))
            for unit_id in available_ids
        }
        actual_status = {
            unit_id: int(snapshot.unit_status[station_id].get(unit_id, 0))
            for unit_id in available_ids
        }
        for unit_id in available_ids:
            memory.time_since_adjust[unit_id] = memory.time_since_adjust.get(unit_id, 0) + 1
            memory.time_since_switch[unit_id] = memory.time_since_switch.get(unit_id, 0) + 1

            old_open = float(memory.unit_openings.get(unit_id, 0.0))
            new_open = float(actual_openings.get(unit_id, 0.0))
            if abs(new_open - old_open) > self.runtime.opening_change_threshold:
                memory.time_since_adjust[unit_id] = 0

            old_status = int(memory.unit_status.get(unit_id, 0))
            new_status = int(actual_status.get(unit_id, 0))
            if old_status != new_status:
                memory.time_since_switch[unit_id] = 0

        memory.unit_openings = actual_openings
        memory.unit_status = actual_status
        memory.active_unit_ids = [unit_id for unit_id, status in actual_status.items() if status == 1]
        memory.last_selected_flow = float(snapshot.station_total_flows[station_id])
        memory.mode = action.mode

    def _build_transfer_bundle(
        self,
        station_id: int,
        upper_plan,
        station_memory,
        disturbance_estimate: Dict[int, float],
    ) -> TransferBundle:
        horizon = self.runtime.control_horizon_lower
        reference_flow: List[float] = []
        reference_back_level: List[float] = []
        reference_front_level: List[float] = []
        reference_head: List[float] = []

        for step_idx in range(horizon):
            ref_index = min(step_idx, upper_plan.horizon - 1)
            reference_flow.append(float(upper_plan.flow_refs[station_id][ref_index]))
            reference_back_level.append(float(upper_plan.station_back_levels[station_id][ref_index]))
            reference_front_level.append(float(upper_plan.station_front_levels[station_id][ref_index]))
            reference_head.append(float(upper_plan.station_heads[station_id][ref_index]))

        return TransferBundle(
            station_id=station_id,
            reference_flow=reference_flow,
            reference_back_level=reference_back_level,
            reference_front_level=reference_front_level,
            reference_head=reference_head,
            active_unit_ids=station_memory.active_unit_ids[:],
            time_since_adjust=station_memory.time_since_adjust.copy(),
            time_since_switch=station_memory.time_since_switch.copy(),
            disturbance_estimate=disturbance_estimate.copy(),
        )

    def _run_control_step(
        self,
        hour: int,
        observation,
        upper_plan,
        disturbance_forecast: Dict[int, List[float]],
        cumulative_last_station_flow: float,
        forced_reconfiguration: Dict[int, bool],
        availability_reasons: Dict[int, str],
    ) -> Dict[str, object]:
        step_label = self._step_label(hour)
        step_hours = float(self.system_config.dt_hours)
        actions = {}
        decisions = {}
        plan_meta = {}
        upstream_selected_flows: Dict[int, float] = {}
        transfer_bundles = {
            station_id: self._build_transfer_bundle(
                station_id=station_id,
                upper_plan=upper_plan,
                station_memory=self.station_memories[station_id],
                disturbance_estimate={pool_id: float(series[0]) for pool_id, series in disturbance_forecast.items()},
            )
            for station_id in self.system_config.station_ids
        }

        for station_id in self.system_config.station_ids:
            station_model = self._build_station_model(station_id, self.available_units_map[station_id])
            station_memory = self.station_memories[station_id]
            reference_state = {
                "flow": float(upper_plan.flow_refs[station_id][0]),
                "back_level": float(upper_plan.station_back_levels[station_id][0]),
                "front_level": float(upper_plan.station_front_levels[station_id][0]),
            }
            decision = self.supervisor.select_mode(
                station_id=station_id,
                env_snapshot=observation,
                upper_plan=upper_plan,
                station_model=station_model,
                station_memory=station_memory,
                available_unit_ids=self.available_units_map[station_id],
                force_reconfiguration=bool(forced_reconfiguration.get(station_id, False)),
                reference_flow=reference_state["flow"],
                reference_back=reference_state["back_level"],
                reference_front=reference_state["front_level"],
            )
            decisions[station_id] = decision

            transfer_bundle = transfer_bundles[station_id]
            ctx = StationControlContext(
                station_id=station_id,
                station_model=station_model,
                available_unit_ids=self.available_units_map[station_id],
                basin_levels=observation.basin_levels.copy(),
                basin_profiles=observation.basin_profiles.copy(),
                pool_areas=observation.pool_areas.copy(),
                anchor_basin_levels=observation.anchor_basin_levels.copy(),
                boundary_nominal_flows=observation.boundary_nominal_flows.copy(),
                current_back_level=observation.station_back_levels[station_id],
                current_front_level=observation.station_front_levels[station_id],
                current_head=observation.station_heads[station_id],
                upper_flow_refs={sid: bundle.reference_flow for sid, bundle in transfer_bundles.items()},
                flow_history={sid: self.station_flow_history[sid][:] for sid in self.station_flow_history},
                boundary_level_plan=self.environment.boundary_level_plan,
                start_time_hours=float(observation.time_hours),
                step_hours=step_hours,
                demand_plan=self.demand_plan,
            )
            action = self.local_controller.solve(
                mode=decision.mode,
                station_ctx=ctx,
                upstream_prediction=upstream_selected_flows,
                disturbance_forecast=disturbance_forecast,
                transfer_bundle=transfer_bundle,
                station_memory=station_memory,
            )
            decisions[station_id].fit_score = float(action.fit_score)
            if decision.mode == "ODD2" and action.fit_score < self.runtime.odd2_fit_threshold:
                action = self.local_controller.solve(
                    mode="ODD3",
                    station_ctx=ctx,
                    upstream_prediction=upstream_selected_flows,
                    disturbance_forecast=disturbance_forecast,
                    transfer_bundle=transfer_bundle,
                    station_memory=station_memory,
                )
                decisions[station_id] = self.supervisor.select_mode(
                    station_id=station_id,
                    env_snapshot=observation,
                    upper_plan=upper_plan,
                    station_model=station_model,
                    station_memory=station_memory,
                    available_unit_ids=self.available_units_map[station_id],
                    force_reconfiguration=True,
                    reference_flow=reference_state["flow"],
                    reference_back=reference_state["back_level"],
                    reference_front=reference_state["front_level"],
                )
                decisions[station_id].mode = "ODD3"
                decisions[station_id].reason = "ODD2 fit below threshold"
                decisions[station_id].fit_score = float(action.fit_score)

            actions[station_id] = action
            upstream_selected_flows[station_id] = action.selected_flow
            flow_min, flow_max = station_model.feasible_flow_range(observation.station_heads[station_id])
            plan_meta[station_id] = {
                "flow_min": flow_min,
                "flow_max": flow_max,
                "execution_error": action.selected_flow - transfer_bundle.reference_flow[0],
                "availability_changed": bool(forced_reconfiguration.get(station_id, False)),
                "availability_reason": str(availability_reasons.get(station_id, "")),
            }
            self._log_station_decision(step_label, self.system_config.station_by_id[station_id], decision, action, flow_min, flow_max)

        # ── 第三步闭环：ODD3 发生时同步更新上层计划 ──────────────────────────────
        # 收集所有站的实际可行流量范围
        current_feasible_ranges = {
            sid: [plan_meta[sid]["flow_min"], plan_meta[sid]["flow_max"]]
            for sid in self.system_config.station_ids
        }
        odd3_stations = [
            sid for sid in self.system_config.station_ids
            if decisions[sid].mode == "ODD3"
        ]
        if odd3_stations:
            # 有站进入 ODD3 → 用最新可行范围重建 lower_feedback 并重新求解上层
            replanning_feedback = LowerFeedback(
                available_units_map={sid: ids[:] for sid, ids in self.available_units_map.items()},
                feasible_flow_ranges=current_feasible_ranges,
                current_modes={sid: decisions[sid].mode for sid in self.system_config.station_ids},
                plan_execution_errors={
                    sid: float(plan_meta[sid]["execution_error"])
                    for sid in self.system_config.station_ids
                },
                reconfigured_stations=forced_reconfiguration,
            )
            self._log(
                f"{step_label} ODD3 触发同步重规划，受影响站: "
                f"{[self._station_label(sid) for sid in odd3_stations]}"
            )
            upper_plan = self.upper_scheduler.solve(
                now=hour,
                env_snapshot=observation,
                demand_state={"delivered_last_station_total": cumulative_last_station_flow},
                available_units_map=self.available_units_map,
                disturbance_forecast=disturbance_forecast,
                lower_feedback=replanning_feedback,
            )
            # 用新计划重建 transfer_bundles
            transfer_bundles = {
                station_id: self._build_transfer_bundle(
                    station_id=station_id,
                    upper_plan=upper_plan,
                    station_memory=self.station_memories[station_id],
                    disturbance_estimate={
                        pool_id: float(series[0]) for pool_id, series in disturbance_forecast.items()
                    },
                )
                for station_id in self.system_config.station_ids
            }
            # 仅对 ODD3 站重新运行下层控制（其他站已完成，不重复计算）
            upstream_selected_flows = {}
            for station_id in self.system_config.station_ids:
                if station_id in odd3_stations:
                    station_model = self._build_station_model(station_id, self.available_units_map[station_id])
                    station_memory = self.station_memories[station_id]
                    ctx_replan = StationControlContext(
                        station_id=station_id,
                        station_model=station_model,
                        available_unit_ids=self.available_units_map[station_id],
                        basin_levels=observation.basin_levels.copy(),
                        basin_profiles=observation.basin_profiles.copy(),
                        pool_areas=observation.pool_areas.copy(),
                        anchor_basin_levels=observation.anchor_basin_levels.copy(),
                        boundary_nominal_flows=observation.boundary_nominal_flows.copy(),
                        current_back_level=observation.station_back_levels[station_id],
                        current_front_level=observation.station_front_levels[station_id],
                        current_head=observation.station_heads[station_id],
                        upper_flow_refs={sid: bundle.reference_flow for sid, bundle in transfer_bundles.items()},
                        flow_history={sid: self.station_flow_history[sid][:] for sid in self.station_flow_history},
                        boundary_level_plan=self.environment.boundary_level_plan,
                        start_time_hours=float(observation.time_hours),
                        step_hours=step_hours,
                        demand_plan=self.demand_plan,
                    )
                    new_action = self.local_controller.solve(
                        mode="ODD3",
                        station_ctx=ctx_replan,
                        upstream_prediction=upstream_selected_flows,
                        disturbance_forecast=disturbance_forecast,
                        transfer_bundle=transfer_bundles[station_id],
                        station_memory=station_memory,
                    )
                    actions[station_id] = new_action
                    flow_min_r, flow_max_r = station_model.feasible_flow_range(observation.station_heads[station_id])
                    plan_meta[station_id]["execution_error"] = new_action.selected_flow - transfer_bundles[station_id].reference_flow[0]
                    self._log(
                        f"  {self._station_label(station_id)} 重规划后选定流量={self._fmt(new_action.selected_flow)}"
                    )
                upstream_selected_flows[station_id] = actions[station_id].selected_flow
        # ── 闭环重规划结束 ─────────────────────────────────────────────────────────

        lower_prediction_plan = {}
        for station_id in self.system_config.station_ids:
            reference_flow = transfer_bundles[station_id].reference_flow
            lower_prediction_plan[station_id] = [actions[station_id].selected_flow] + reference_flow[1:]

        lower_prediction = simulate_basin_trajectory(
            system_config=self.system_config,
            runtime=self.runtime,
            initial_levels=observation.basin_levels,
            flow_plan=lower_prediction_plan,
            demand_plan=self.demand_plan,
            boundary_level_plan=self.environment.boundary_level_plan,
            disturbance_forecast=disturbance_forecast,
            start_hour=float(observation.time_hours),
            step_hours=step_hours,
            boundary_nominal_flows=observation.boundary_nominal_flows,
            anchor_basin_levels=observation.anchor_basin_levels,
            pool_areas=observation.pool_areas,
            pool_profiles=observation.basin_profiles,
        )

        next_observation = self.environment.step(
            {station_id: actions[station_id] for station_id in self.system_config.station_ids},
            current_hour=float(observation.time_hours),
        )
        self._warn_out_of_range(step_label, observation, next_observation)
        demand_row = self.demand_plan.iloc[min(max(int(np.floor(float(observation.time_hours) + 1e-9)), 0), len(self.demand_plan) - 1)]

        actual_upper_flow_errors = {
            station_id: float(next_observation.station_flows[station_id] - transfer_bundles[station_id].reference_flow[0])
            for station_id in self.system_config.station_ids
        }
        actual_lower_flow_errors = {
            station_id: float(next_observation.station_flows[station_id] - actions[station_id].selected_flow)
            for station_id in self.system_config.station_ids
        }
        actual_execution_errors = {
            station_id: float(actual_lower_flow_errors[station_id])
            for station_id in self.system_config.station_ids
        }
        self.observers.update(
            prev_basin_levels=observation.basin_levels,
            next_basin_levels=next_observation.basin_levels,
            actual_flows={station_id: next_observation.station_flows[station_id] for station_id in self.system_config.station_ids},
            demand_row=demand_row,
            prev_basin_volumes=observation.basin_volumes,
            next_basin_volumes=next_observation.basin_volumes,
            prev_basin_profiles=observation.basin_profiles,
            next_basin_profiles=next_observation.basin_profiles,
            defer_visibility=False,
            step_hours=step_hours,
            pool_areas=observation.pool_areas,
        )
        actual_hidden_disturbance = self.environment.last_hidden_disturbance.copy()
        visible_disturbance = self.observers.get_estimate()

        lower_feedback = self._make_lower_feedback(actions, decisions, plan_meta, forced_reconfiguration)
        self._log_step_result(
            step_label,
            upper_plan,
            transfer_bundles,
            lower_prediction_plan,
            lower_prediction,
            next_observation,
            decisions,
            actions,
            cumulative_last_station_flow,
            step_hours,
            actual_hidden_disturbance,
            visible_disturbance,
            actual_upper_flow_errors,
            actual_lower_flow_errors,
            actual_execution_errors,
        )
        return {
            "step_label": step_label,
            "current_time_hours": float(observation.time_hours),
            "actions": actions,
            "decisions": decisions,
            "plan_meta": plan_meta,
            "lower_prediction_plan": lower_prediction_plan,
            "lower_prediction": lower_prediction,
            "transfer_bundles": transfer_bundles,
            "next_observation": next_observation,
            "actual_hidden_disturbance": actual_hidden_disturbance,
            "visible_disturbance": visible_disturbance,
            "actual_upper_flow_errors": actual_upper_flow_errors,
            "actual_lower_flow_errors": actual_lower_flow_errors,
            "actual_execution_errors": actual_execution_errors,
            "lower_feedback": lower_feedback,
        }

    def run(self) -> Dict[str, pd.DataFrame]:
        self._log(f"开始闭环仿真，总步数={self.hours}")
        records: List[Dict[str, object]] = []
        unit_records: List[Dict[str, object]] = []
        cumulative_last_station_flow = 0.0
        hist_flows = {station_id: [] for station_id in self.system_config.station_ids}
        hist_back_levels = {station_id: [] for station_id in self.system_config.station_ids}
        hist_front_levels = {station_id: [] for station_id in self.system_config.station_ids}
        hist_pool_levels = {pool_id: [] for pool_id in self.system_config.pool_ids}
        hist_disturbances = {pool_id: [] for pool_id in self.system_config.pool_ids}
        hist_upper_flow_errors = {station_id: [] for station_id in self.system_config.station_ids}
        hist_lower_flow_errors = {station_id: [] for station_id in self.system_config.station_ids}
        hist_efficiencies = {station_id: [] for station_id in self.system_config.station_ids}
        hist_errors = {station_id: [] for station_id in self.system_config.station_ids}
        hist_odd_flow_errors = {station_id: [] for station_id in self.system_config.station_ids}
        hist_odd_level_errors = {station_id: [] for station_id in self.system_config.station_ids}
        hist_unit_status: List[Dict[int, Dict[str, Dict[str, float]]]] = []
        hist_time_hours: List[float] = []
        lower_feedback = LowerFeedback(
            available_units_map={station_id: ids[:] for station_id, ids in self.available_units_map.items()},
            feasible_flow_ranges={station.id: [0.0, 0.0] for station in self.system_config.stations},
            current_modes={station.id: "ODD1" for station in self.system_config.stations},
            plan_execution_errors={station.id: 0.0 for station in self.system_config.stations},
            reconfigured_stations={station.id: False for station in self.system_config.stations},
        )

        for hour in range(self.hours):
            self.observers.flush_pending()
            availability_changed, availability_reasons = self._apply_unit_availability(hour)
            lower_feedback = LowerFeedback(
                available_units_map={station_id: ids[:] for station_id, ids in self.available_units_map.items()},
                feasible_flow_ranges=lower_feedback.feasible_flow_ranges,
                current_modes=lower_feedback.current_modes,
                plan_execution_errors=lower_feedback.plan_execution_errors,
                reconfigured_stations=availability_changed,
            )
            observation = self.environment.observe()
            disturbance_estimate = self.observers.get_estimate()
            disturbance_forecast = self.observers.get_forecast(
                horizon=max(self.system_config.horizon_hours - hour, self.runtime.control_horizon_lower),
                step_hours=float(self.system_config.dt_hours),
            )
            self._log_step_start(self._step_label(hour), observation, disturbance_estimate, cumulative_last_station_flow)
            upper_plan = self.upper_scheduler.solve(
                now=hour,
                env_snapshot=observation,
                demand_state={"delivered_last_station_total": cumulative_last_station_flow},
                available_units_map=lower_feedback.available_units_map,
                disturbance_forecast=disturbance_forecast,
                lower_feedback=lower_feedback,
            )
            self._log_upper_plan(self._step_label(hour), upper_plan, cumulative_last_station_flow)
            cycle = self._run_control_step(
                hour=hour,
                observation=observation,
                upper_plan=upper_plan,
                disturbance_forecast=disturbance_forecast,
                cumulative_last_station_flow=cumulative_last_station_flow,
                forced_reconfiguration=availability_changed,
                availability_reasons=availability_reasons,
            )
            lower_feedback = cycle["lower_feedback"]
            actions = cycle["actions"]
            decisions = cycle["decisions"]
            current_time_hours = float(cycle["current_time_hours"])
            next_observation = cycle["next_observation"]
            visible_disturbance = cycle["visible_disturbance"]
            actual_upper_flow_errors = cycle["actual_upper_flow_errors"]
            actual_lower_flow_errors = cycle["actual_lower_flow_errors"]
            actual_hidden_disturbance = cycle["actual_hidden_disturbance"]
            actual_execution_errors = cycle["actual_execution_errors"]
            lower_prediction_plan = cycle["lower_prediction_plan"]
            lower_prediction = cycle["lower_prediction"]
            transfer_bundles = cycle["transfer_bundles"]
            step_hours = float(self.system_config.dt_hours)
            snapshot = self.environment.current_snapshot
            if snapshot is None:
                raise RuntimeError("Environment snapshot missing after step execution")
            lower_feedback.plan_execution_errors = {
                station_id: float(actual_execution_errors[station_id])
                for station_id in self.system_config.station_ids
            }

            for station_id, action in actions.items():
                history = self.station_flow_history[station_id]
                if history and abs(history[-1][0] - current_time_hours) <= 1e-9:
                    history[-1] = (current_time_hours, float(next_observation.station_flows[station_id]))
                else:
                    history.append((current_time_hours, float(next_observation.station_flows[station_id])))

            hist_time_hours.append(float(next_observation.time_hours))
            for station_id, action in actions.items():
                self._update_station_memory(station_id, action, snapshot)
                hist_flows[station_id].append(float(next_observation.station_flows[station_id]))
                hist_back_levels[station_id].append(float(next_observation.station_back_levels[station_id]))
                hist_front_levels[station_id].append(float(next_observation.station_front_levels[station_id]))
                _, station_efficiency, station_power_mw = self._actual_unit_metrics(snapshot, station_id)
                hist_efficiencies[station_id].append(float(station_efficiency))
                transfer_bundle = transfer_bundles[station_id]
                flow_error = abs(next_observation.station_flows[station_id] - transfer_bundle.reference_flow[0])
                level_error = max(
                    abs(next_observation.station_back_levels[station_id] - transfer_bundle.reference_back_level[0]),
                    abs(next_observation.station_front_levels[station_id] - transfer_bundle.reference_front_level[0]),
                )
                hist_errors[station_id].append(max(flow_error, level_error))
                hist_odd_flow_errors[station_id].append(float(decisions[station_id].flow_error))
                hist_odd_level_errors[station_id].append(float(decisions[station_id].level_error))

            for pool_id in self.system_config.pool_ids:
                hist_pool_levels[pool_id].append(next_observation.pool_levels[pool_id])
                hist_disturbances[pool_id].append(visible_disturbance.get(pool_id, 0.0))
            for station_id in self.system_config.station_ids:
                hist_upper_flow_errors[station_id].append(actual_upper_flow_errors[station_id])
                hist_lower_flow_errors[station_id].append(actual_lower_flow_errors[station_id])
            hist_unit_status.append(self._build_unit_status_snapshot(snapshot))

            cumulative_last_station_flow += next_observation.station_flows[self.system_config.last_station_id] * step_hours / max(self.system_config.dt_hours, 1e-9)
            for station_id in self.system_config.station_ids:
                transfer_bundle = transfer_bundles[station_id]
                station = self.system_config.station_by_id[station_id]
                records.append(
                    {
                        "hour": hour,
                        "time_hours": float(next_observation.time_hours),
                        "step_hours": float(step_hours),
                        "station_id": station_id,
                        "mode": actions[station_id].mode,
                        "decision_reason": decisions[station_id].reason,
                        "availability_changed": bool(availability_changed.get(station_id, False)),
                        "availability_reason": str(availability_reasons.get(station_id, "")),
                        "available_units": ",".join(str(unit_id) for unit_id in self.available_units_map[station_id]),
                        "ref_flow": transfer_bundle.reference_flow[0],
                        "ref_flow_effective": upper_plan.effective_flow_refs[station_id][0],
                        "selected_flow": actions[station_id].selected_flow,
                        "actual_flow": next_observation.station_flows[station_id],
                        "ref_back_level": transfer_bundle.reference_back_level[0],
                        "actual_back_level": next_observation.station_back_levels[station_id],
                        "ref_front_level": transfer_bundle.reference_front_level[0],
                        "actual_front_level": next_observation.station_front_levels[station_id],
                        "fit_score": actions[station_id].fit_score,
                        "objective": actions[station_id].objective,
                        "decision_flow_error": float(decisions[station_id].flow_error),
                        "decision_level_error": float(decisions[station_id].level_error),
                        "actual_upper_flow_error": actual_upper_flow_errors[station_id],
                        "actual_lower_flow_error": actual_lower_flow_errors[station_id],
                        "tracking_error_flow": next_observation.station_flows[station_id] - transfer_bundle.reference_flow[0],
                        "execution_error_flow": actual_execution_errors[station_id],
                        "efficiency": hist_efficiencies[station_id][-1],
                        "power_mw": float(station_power_mw),
                        "thread_uuid": next_observation.thread_uuid,
                    }
                )
                for pool_id in self.system_config.pool_ids:
                    records[-1][f"disturbance_estimate_pool_{pool_id}"] = float(visible_disturbance.get(pool_id, 0.0))
                    records[-1][f"hidden_pool_{pool_id}"] = float(actual_hidden_disturbance.get(pool_id, 0.0))
                bleeder_values = list(self.environment.last_bleeder_updates.values())
                for idx, pool_id in enumerate(self.system_config.pool_ids):
                    records[-1][f"bleeder_pool_{pool_id}"] = float(bleeder_values[idx]) if idx < len(bleeder_values) else 0.0
                    records[-1][f"remote_pool_{pool_id}"] = float(next_observation.pool_levels.get(pool_id, 0.0))
                action = actions[station_id]
                actual_unit_rows, _, _ = self._actual_unit_metrics(snapshot, station_id)
                for unit in station.units:
                    unit_actual = actual_unit_rows[unit.id]
                    unit_records.append(
                        {
                            "hour": hour,
                            "time_hours": float(next_observation.time_hours),
                            "step_hours": float(step_hours),
                            "station_id": station_id,
                            "station_name": station.name,
                            "unit_id": unit.id,
                            "unit_name": unit.name,
                            "available": int(unit.id in self.available_units_map[station_id]),
                            "availability_changed": bool(availability_changed.get(station_id, False)),
                            "availability_reason": str(availability_reasons.get(station_id, "")),
                            "mode": action.mode,
                            "status": int(snapshot.unit_status[station_id].get(unit.id, 0)),
                            "opening": float(snapshot.unit_openings[station_id].get(unit.id, 0.0)),
                            "unit_flow": float(snapshot.unit_flows[station_id].get(unit.id, 0.0)),
                            "front_level": float(unit_actual["front_level"]),
                            "back_level": float(unit_actual["back_level"]),
                            "head": float(unit_actual["head"]),
                            "unit_efficiency": float(unit_actual["efficiency"]),
                            "unit_power_mw": float(unit_actual["power_mw"]),
                        }
                    )

            if self.runtime.save_step_plots:
                self._plot_step(
                    step_index=len(hist_time_hours) - 1,
                    current_time_hours=float(observation.time_hours),
                    lower_step_hours=step_hours,
                    upper_plan=upper_plan,
                    lower_prediction_plan=lower_prediction_plan,
                    lower_prediction=lower_prediction,
                    hist_times=hist_time_hours,
                    hist_flows=hist_flows,
                    hist_back_levels=hist_back_levels,
                    hist_front_levels=hist_front_levels,
                    hist_pool_levels=hist_pool_levels,
                    hist_disturbances=hist_disturbances,
                    hist_upper_flow_errors=hist_upper_flow_errors,
                    hist_lower_flow_errors=hist_lower_flow_errors,
                    hist_efficiencies=hist_efficiencies,
                    hist_odd_flow_errors=hist_odd_flow_errors,
                    hist_odd_level_errors=hist_odd_level_errors,
                    actions=actions,
                    decisions=decisions,
                    hist_unit_status=hist_unit_status,
                )

        history = pd.DataFrame(records)
        unit_history = pd.DataFrame(unit_records)
        unit_summary = self._build_unit_summary(unit_history)
        summary = self._build_summary(history, unit_summary)
        system_summary = self._build_system_summary(history, unit_summary)
        self._log("闭环仿真完成，正在写出结果文件")
        self._write_outputs(history, summary, unit_history, unit_summary, system_summary)
        if not system_summary.empty:
            stats = system_summary.iloc[0]
            self._log(
                "最终统计: "
                f"末站总调水量={self._fmt(stats['actual_last_station_volume_m3'])}，"
                f"完成率={self._fmt(stats['delivery_completion_ratio'])}，"
                f"总平均功率={self._fmt(stats['mean_total_power_mw'])}MW，"
                f"全站总平均效率={self._fmt(stats['overall_mean_efficiency'])}，"
                f"实际叶片调节次数={int(stats['total_actual_blade_adjust_count'])}，"
                f"实际启机次数={int(stats['total_actual_startup_count'])}，"
                f"实际停机次数={int(stats['total_actual_shutdown_count'])}"
            )
        self._log("仿真结束")
        return {
            "history": history,
            "summary": summary,
            "unit_history": unit_history,
            "unit_summary": unit_summary,
            "system_summary": system_summary,
        }

    def _build_summary(self, history: pd.DataFrame, unit_summary: pd.DataFrame) -> pd.DataFrame:
        grouped = history.groupby("station_id").agg(
            mean_abs_flow_error=("actual_flow", lambda series: float((series - history.loc[series.index, "ref_flow"]).abs().mean())),
            mean_efficiency=("efficiency", "mean"),
            mean_power_mw=("power_mw", "mean"),
            mean_fit_score=("fit_score", "mean"),
            odd1_hours=("mode", lambda series: float(history.loc[series.index, "step_hours"][series == "ODD1"].sum())),
            odd2_hours=("mode", lambda series: float(history.loc[series.index, "step_hours"][series == "ODD2"].sum())),
            odd3_hours=("mode", lambda series: float(history.loc[series.index, "step_hours"][series == "ODD3"].sum())),
            odd1_count=("mode", lambda series: int((series == "ODD1").sum())),
            odd2_count=("mode", lambda series: int((series == "ODD2").sum())),
            odd3_count=("mode", lambda series: int((series == "ODD3").sum())),
            availability_change_count=("availability_changed", lambda series: int(series.sum())),
            transferred_flow_hour=("actual_flow", lambda series: float((series * history.loc[series.index, "step_hours"]).sum())),
        )
        grouped["transferred_volume_m3"] = grouped["transferred_flow_hour"] * 3600.0
        if not unit_summary.empty:
            unit_station = unit_summary.groupby("station_id", as_index=False).agg(
                total_actual_blade_adjust_count=("actual_blade_adjust_count", "sum"),
                total_actual_startup_count=("actual_startup_count", "sum"),
                total_actual_shutdown_count=("actual_shutdown_count", "sum"),
                total_active_unit_hours=("active_hours", "sum"),
            )
            unit_station["total_blade_adjust_count"] = unit_station["total_actual_blade_adjust_count"]
            unit_station["total_startup_count"] = unit_station["total_actual_startup_count"]
            unit_station["total_shutdown_count"] = unit_station["total_actual_shutdown_count"]
            grouped = grouped.reset_index().merge(unit_station, on="station_id", how="left")
        else:
            grouped = grouped.reset_index()
        return grouped.fillna(0.0)

    def _build_unit_summary(self, unit_history: pd.DataFrame) -> pd.DataFrame:
        if unit_history.empty:
            return pd.DataFrame(
                columns=[
                    "station_id",
                    "station_name",
                    "unit_id",
                    "unit_name",
                    "available_hours",
                    "actual_startup_count",
                    "actual_shutdown_count",
                    "actual_blade_adjust_count",
                    "actual_total_opening_change",
                    "startup_count",
                    "shutdown_count",
                    "blade_adjust_count",
                    "total_opening_change",
                    "active_hours",
                    "mean_opening_when_on",
                    "mean_unit_flow_when_on",
                    "mean_unit_efficiency_when_on",
                    "mean_unit_power_mw_when_on",
                ]
            )

        unit_history = unit_history.sort_values(["station_id", "unit_id", "time_hours"]).copy()
        unit_history["prev_status"] = unit_history.groupby(["station_id", "unit_id"])["status"].shift()
        unit_history["prev_opening"] = unit_history.groupby(["station_id", "unit_id"])["opening"].shift()
        unit_history["prev_status"] = unit_history["prev_status"].fillna(unit_history["status"])
        unit_history["prev_opening"] = unit_history["prev_opening"].fillna(unit_history["opening"])
        unit_history["actual_startup"] = ((unit_history["prev_status"] == 0) & (unit_history["status"] == 1)).astype(int)
        unit_history["actual_shutdown"] = ((unit_history["prev_status"] == 1) & (unit_history["status"] == 0)).astype(int)
        unit_history["actual_opening_delta"] = (unit_history["opening"] - unit_history["prev_opening"]).abs()
        unit_history["actual_blade_adjust"] = (
            unit_history["actual_opening_delta"] > self.runtime.opening_change_threshold
        ).astype(int)
        unit_history["startup"] = unit_history["actual_startup"]
        unit_history["shutdown"] = unit_history["actual_shutdown"]
        unit_history["opening_delta"] = unit_history["actual_opening_delta"]
        unit_history["blade_adjust"] = unit_history["actual_blade_adjust"]

        grouped = unit_history.groupby(["station_id", "station_name", "unit_id", "unit_name"]).agg(
            available_hours=("available", lambda series: float(unit_history.loc[series.index, "step_hours"][series == 1].sum())),
            actual_startup_count=("actual_startup", "sum"),
            actual_shutdown_count=("actual_shutdown", "sum"),
            actual_blade_adjust_count=("actual_blade_adjust", "sum"),
            actual_total_opening_change=("actual_opening_delta", "sum"),
            active_hours=("status", lambda series: float(unit_history.loc[series.index, "step_hours"][series == 1].sum())),
            mean_opening_when_on=("opening", lambda series: float(series[unit_history.loc[series.index, "status"] == 1].mean()) if (unit_history.loc[series.index, "status"] == 1).any() else 0.0),
            mean_unit_flow_when_on=("unit_flow", lambda series: float(series[unit_history.loc[series.index, "status"] == 1].mean()) if (unit_history.loc[series.index, "status"] == 1).any() else 0.0),
            mean_unit_efficiency_when_on=("unit_efficiency", lambda series: float(series[unit_history.loc[series.index, "status"] == 1].mean()) if (unit_history.loc[series.index, "status"] == 1).any() else 0.0),
            mean_unit_power_mw_when_on=("unit_power_mw", lambda series: float(series[unit_history.loc[series.index, "status"] == 1].mean()) if (unit_history.loc[series.index, "status"] == 1).any() else 0.0),
        )
        grouped = grouped.reset_index()
        grouped["startup_count"] = grouped["actual_startup_count"]
        grouped["shutdown_count"] = grouped["actual_shutdown_count"]
        grouped["blade_adjust_count"] = grouped["actual_blade_adjust_count"]
        grouped["total_opening_change"] = grouped["actual_total_opening_change"]
        return grouped

    def _build_system_summary(self, history: pd.DataFrame, unit_summary: pd.DataFrame) -> pd.DataFrame:
        if history.empty:
            return pd.DataFrame()

        last_station = history[history["station_id"] == 3]
        target_flow_hour = float(self.system_config.target_avg_flow_last_station) * float(self.hours)
        actual_flow_hour = float((last_station["actual_flow"] * last_station["step_hours"]).sum())
        target_volume = target_flow_hour * 3600.0
        actual_volume = actual_flow_hour * 3600.0
        total_blade_adjust = int(unit_summary["actual_blade_adjust_count"].sum()) if not unit_summary.empty else 0
        total_startup = int(unit_summary["actual_startup_count"].sum()) if not unit_summary.empty else 0
        total_shutdown = int(unit_summary["actual_shutdown_count"].sum()) if not unit_summary.empty else 0
        total_energy_mwh = float((history["power_mw"] * history["step_hours"]).sum()) if "power_mw" in history.columns else 0.0
        mean_total_power_mw = total_energy_mwh / max(float(self.hours), 1e-9)
        weighted_efficiency_denom = float((history["actual_flow"] * history["step_hours"]).sum())
        overall_mean_efficiency = (
            float((history["efficiency"] * history["actual_flow"] * history["step_hours"]).sum()) / weighted_efficiency_denom
            if weighted_efficiency_denom > 0.0
            else 0.0
        )

        summary_row = {
            "simulated_hours": float(self.hours),
            "target_last_station_flow_hour": target_flow_hour,
            "actual_last_station_flow_hour": actual_flow_hour,
            "target_last_station_volume_m3": target_volume,
            "actual_last_station_volume_m3": actual_volume,
            "delivery_completion_ratio": actual_flow_hour / max(target_flow_hour, 1e-9),
            "mean_total_power_mw": mean_total_power_mw,
            "total_energy_mwh": total_energy_mwh,
            "overall_mean_efficiency": overall_mean_efficiency,
            "total_actual_blade_adjust_count": total_blade_adjust,
            "total_actual_startup_count": total_startup,
            "total_actual_shutdown_count": total_shutdown,
            "total_blade_adjust_count": total_blade_adjust,
            "total_startup_count": total_startup,
            "total_shutdown_count": total_shutdown,
            "odd1_count_total": int((history["mode"] == "ODD1").sum()),
            "odd2_count_total": int((history["mode"] == "ODD2").sum()),
            "odd3_count_total": int((history["mode"] == "ODD3").sum()),
            "availability_change_count_total": int(history["availability_changed"].sum()),
        }
        return pd.DataFrame([summary_row])

    def _write_outputs(
        self,
        history: pd.DataFrame,
        summary: pd.DataFrame,
        unit_history: pd.DataFrame,
        unit_summary: pd.DataFrame,
        system_summary: pd.DataFrame,
    ) -> None:
        history_path = self.output_dir / "closed_loop_history.csv"
        summary_path = self.output_dir / "closed_loop_summary.csv"
        unit_history_path = self.output_dir / "unit_operation_history.csv"
        unit_summary_path = self.output_dir / "unit_operation_summary.csv"
        stats_excel_path = self.output_dir / "closed_loop_statistics.xlsx"
        history.to_csv(history_path, index=False)
        summary.to_csv(summary_path, index=False)
        unit_history.to_csv(unit_history_path, index=False)
        unit_summary.to_csv(unit_summary_path, index=False)
        with pd.ExcelWriter(stats_excel_path) as writer:
            system_summary.to_excel(writer, sheet_name="system_summary", index=False)
            summary.to_excel(writer, sheet_name="station_summary", index=False)
            unit_summary.to_excel(writer, sheet_name="unit_summary", index=False)
            history.to_excel(writer, sheet_name="station_history", index=False)
            unit_history.to_excel(writer, sheet_name="unit_history", index=False)
        self._plot_results(history)
        self._log(f"站级历史文件: {history_path}")
        self._log(f"站级汇总文件: {summary_path}")
        self._log(f"机组历史文件: {unit_history_path}")
        self._log(f"机组汇总文件: {unit_summary_path}")
        self._log(f"统计工作簿: {stats_excel_path}")
        self._log(f"总览图: {self.output_dir / 'closed_loop_overview.png'}")

    def _build_unit_status_snapshot(self, thread_snapshot) -> Dict[int, Dict[str, Dict[str, float]]]:
        snapshot_payload: Dict[int, Dict[str, Dict[str, float]]] = {}
        for station in self.system_config.stations:
            station_snapshot: Dict[str, Dict[str, float]] = {}
            for unit in station.units:
                station_snapshot[unit.name] = {
                    "Status": int(thread_snapshot.unit_status[station.id].get(unit.id, 0)),
                    "Opening": float(thread_snapshot.unit_openings[station.id].get(unit.id, 0.0)),
                }
            snapshot_payload[station.id] = station_snapshot
        return snapshot_payload

    def _predicted_series(self, predicted_values, history_values, n_points):
        if predicted_values:
            return predicted_values[:n_points]
        fallback = history_values[-1] if history_values else 0.0
        return [fallback] * n_points

    def _disturbance_reference_series(self):
        n_points = min(self.hours, len(self.demand_plan))
        times = np.arange(n_points, dtype=float)
        pool_ids = list(self.system_config.pool_ids)
        chain_pairs = _chain_pairs(self.system_config)
        demand_series = {}
        rain_series = {pool_id: [] for pool_id in pool_ids}
        for hour in range(n_points):
            hidden = hidden_disturbance_at_step(hour, self.environment.hidden_disturbance_plan, pool_ids)
            for pool_id in pool_ids:
                rain_series[pool_id].append(float(hidden.get(pool_id, 0.0)))
        for pair in chain_pairs:
            pool_id = int(pair["pool_id"])
            column = str(pair["demand_column"])
            if column in self.demand_plan.columns:
                demand_series[pool_id] = self.demand_plan[column].iloc[:n_points].to_numpy(dtype=float)
            else:
                demand_series[pool_id] = np.zeros(n_points, dtype=float)
        return times, demand_series, {pool_id: np.asarray(values, dtype=float) for pool_id, values in rain_series.items()}

    def _current_mode_summary(self, actions) -> str:
        return " | ".join(
            [f"S{station_id}: {actions[station_id].mode}" for station_id in self.system_config.station_ids]
        )

    def _unit_state_summary_lines(self, station_id: int, actions, hist_unit_status) -> List[str]:
        station = self.system_config.station_by_id[station_id]
        actual_snapshot = hist_unit_status[-1][station_id] if hist_unit_status else {}
        command_action = actions[station_id]
        lines = [f"S{station_id} Actual/Command"]
        for unit in station.units:
            actual_payload = actual_snapshot.get(unit.name, {"Status": 0, "Opening": 0.0})
            actual_status = "ON" if int(actual_payload.get("Status", 0)) == 1 else "OFF"
            command_status = "ON" if int(command_action.unit_status.get(unit.id, 0)) == 1 else "OFF"
            actual_opening = float(actual_payload.get("Opening", 0.0))
            command_opening = float(command_action.unit_openings.get(unit.id, 0.0))
            lines.append(
                f"P{unit.id} {actual_status} {self._fmt(actual_opening)} | "
                f"{command_status} {self._fmt(command_opening)}"
            )
        return lines

    def _plot_step(
        self,
        step_index: int,
        current_time_hours: float,
        lower_step_hours: float,
        upper_plan,
        lower_prediction_plan,
        lower_prediction,
        hist_times,
        hist_flows,
        hist_back_levels,
        hist_front_levels,
        hist_pool_levels,
        hist_disturbances,
        hist_upper_flow_errors,
        hist_lower_flow_errors,
        hist_efficiencies,
        hist_odd_flow_errors,
        hist_odd_level_errors,
        actions,
        decisions,
        hist_unit_status,
    ) -> None:
        import matplotlib.pyplot as plt
        station_ids = self.system_config.station_ids
        pool_ids = self.system_config.pool_ids
        n_stations = len(station_ids)
        segments = getattr(self.system_config.topology, 'channel_segments', []) if hasattr(self.system_config, 'topology') else []
        n_rows = n_stations + 1 + len(segments)
        fig = plt.figure(figsize=(34, 4.5 * n_rows + 5))
        gs = fig.add_gridspec(n_rows, 6)
        fig.suptitle(
            f"Step {step_index:03d} | Modes: {self._current_mode_summary(actions)}",
            fontsize=18,
            y=0.99,
        )
        times_hist = np.asarray(hist_times, dtype=float)
        plan_len = len(lower_prediction_plan[station_ids[0]]) if station_ids else 0
        upper_len = len(upper_plan.flow_refs[station_ids[0]]) if station_ids else 0
        times_plan = current_time_hours + np.arange(plan_len, dtype=float) * lower_step_hours
        times_upper = current_time_hours + np.arange(upper_len, dtype=float) * float(self.system_config.dt_hours)
        
        station_palette = plt.cm.tab10(np.linspace(0.2, 0.9, max(n_stations, 1)))
        cmap_cycle = [plt.cm.Blues, plt.cm.Greens, plt.cm.Reds, plt.cm.Purples, plt.cm.Oranges, plt.cm.Greys]
        station_palettes = {
            station.id: cmap_cycle[idx % len(cmap_cycle)](
                np.linspace(0.45, 0.9, len(station.units))
            )
            for idx, station in enumerate(self.system_config.stations)
        }
        
        for idx, station_id in enumerate(station_ids):
            color = station_palette[idx % len(station_palette)]
            station = self.system_config.station_by_id[station_id]
            action = actions[station_id]
            
            # 1. Flow
            ax_flow = fig.add_subplot(gs[idx, 0])
            ax_flow.plot(times_hist, hist_flows[station_id], color=color, linestyle="-", label="Actual Q")
            ax_flow.plot(times_plan, lower_prediction_plan[station_id], color=color, linestyle="--", alpha=0.5, label="Lower Pred")
            ax_flow.step(times_upper, upper_plan.flow_refs[station_id], color=color, linestyle=":", where="post", alpha=0.8, label="Upper Plan")
            ax_flow.set_title(f"S{station_id} Flow")
            ax_flow.set_ylabel("Flow (m3/s)")
            ax_flow.set_xlim([0, self.hours])
            ax_flow.legend(loc="upper right", fontsize=8)
            ax_flow.grid(True)
            
            # 2. Head
            ax_head = fig.add_subplot(gs[idx, 1])
            
            act_back_arr = np.array(hist_back_levels[station_id]) if hist_back_levels[station_id] else np.array([])
            act_front_arr = np.array(hist_front_levels[station_id]) if hist_front_levels[station_id] else np.array([])
            if act_back_arr.size > 0 and act_front_arr.size > 0:
                ax_head.plot(times_hist, act_back_arr - act_front_arr, color=color, linestyle="-", label="Actual Head")
                
            pred_back_arr = np.array(upper_plan.station_back_levels.get(station_id, []))
            pred_front_arr = np.array(upper_plan.station_front_levels.get(station_id, []))
            if pred_back_arr.size > 0 and pred_front_arr.size > 0:
                ax_head.step(times_upper, pred_back_arr - pred_front_arr, color=color, linestyle=":", alpha=0.8, where="post", label="Pred Head")
                
            ax_head.set_title(f"S{station_id} Head")
            ax_head.set_ylabel("Head (m)")
            ax_head.set_xlim([0, self.hours])
            ax_head.legend(loc="upper right", fontsize=8)
            ax_head.grid(True)
            
            # 3. Efficiency
            ax_eff = fig.add_subplot(gs[idx, 2])
            ax_eff.plot(times_hist, hist_efficiencies[station_id], color=color, linestyle="-", label="Efficiency %")
            ax_eff.plot(times_plan, self._predicted_series(action.predicted_efficiencies, hist_efficiencies[station_id], len(times_plan)), color=color, linestyle="--", alpha=0.5, label="Pred Eff")
            ax_eff.set_title(f"S{station_id} Efficiency")
            ax_eff.set_ylabel("Eff (%)")
            ax_eff.set_xlim([0, self.hours])
            ax_eff.set_ylim([0, 100])
            ax_eff.legend(loc="lower right", fontsize=8)
            ax_eff.grid(True)
            
            # 4. Blade Angles
            ax_angle = fig.add_subplot(gs[idx, 3])
            palette_st = station_palettes[station_id]
            for u_idx, unit in enumerate(station.units):
                actual_angles = [step_data[station_id][unit.name]["Opening"] for step_data in hist_unit_status]
                pred_angles = [float(action.unit_openings.get(unit.id, 0.0))] * len(times_plan)
                u_color = palette_st[u_idx]
                ax_angle.plot(times_hist, actual_angles, color=u_color, label=f"U{unit.id} Actual")
                ax_angle.plot(times_plan, pred_angles, "--", color=u_color, alpha=0.55)
            ax_angle.set_title(f"S{station_id} Blade Angles")
            ax_angle.set_ylabel("Angle")
            ax_angle.set_xlim([0, self.hours])
            ax_angle.legend(loc="upper right", ncol=2, fontsize=7)
            ax_angle.grid(True)
            
            # 5. ODD Domain
            ax_odd = fig.add_subplot(gs[idx, 4])
            odd3_boundary = max(float(self.runtime.odd3_flow_tolerance), float(self.runtime.odd1_flow_tolerance))
            ymax = max(
                odd3_boundary * 1.2,
                max(hist_odd_flow_errors[station_id]) if hist_odd_flow_errors[station_id] else odd3_boundary,
            )
            ax_odd.axhspan(0.0, self.runtime.odd1_flow_tolerance, color="#d9f2d9", alpha=0.55, label="ODD1")
            ax_odd.axhspan(self.runtime.odd1_flow_tolerance, odd3_boundary, color="#fff2cc", alpha=0.55, label="ODD2")
            ax_odd.axhspan(odd3_boundary, ymax, color="#fce5cd", alpha=0.55, label="ODD3")
            ax_odd.axhline(self.runtime.odd1_flow_tolerance, color="#6aa84f", linestyle=":")
            ax_odd.axhline(odd3_boundary, color="#bf9000", linestyle=":")
            
            ax_odd.plot(times_hist, hist_odd_flow_errors[station_id], color=color, linestyle="-", label="dQ Decision")
            if hist_odd_flow_errors[station_id]:
                ax_odd.scatter(times_hist[-1], hist_odd_flow_errors[station_id][-1], color=color, s=36, zorder=5)
            ax_odd.set_title(f"S{station_id} ODD Domain")
            ax_odd.set_ylabel("dQ (m3/s)")
            ax_odd.set_xlim([0, self.hours])
            ax_odd.set_ylim([0.0, ymax])
            ax_odd.legend(loc="upper right", fontsize=7)
            ax_odd.grid(True)
            
            # 6. Detailed Text Summary
            ax_text = fig.add_subplot(gs[idx, 5])
            ax_text.axis("off")
            
            up_q = self._fmt(upper_plan.flow_refs[station_id][0]) if len(upper_plan.flow_refs[station_id]) > 0 else "N/A"
            dn_q = self._fmt(lower_prediction_plan[station_id][0]) if len(lower_prediction_plan[station_id]) > 0 else "N/A"
            act_q = self._fmt(hist_flows[station_id][-1]) if hist_flows[station_id] else "N/A"
            act_eff = self._fmt(hist_efficiencies[station_id][-1]) if hist_efficiencies[station_id] else "N/A"
            dq = self._fmt(decisions[station_id].flow_error)
            dz = self._fmt(decisions[station_id].level_error)
            
            pred_back = upper_plan.station_back_levels[station_id][0] if station_id in upper_plan.station_back_levels and len(upper_plan.station_back_levels[station_id]) > 0 else None
            pred_front = upper_plan.station_front_levels[station_id][0] if station_id in upper_plan.station_front_levels and len(upper_plan.station_front_levels[station_id]) > 0 else None
            pred_h = self._fmt(pred_back - pred_front) if pred_back is not None and pred_front is not None else "N/A"
            
            act_back = hist_back_levels[station_id][-1] if hist_back_levels[station_id] else None
            act_front = hist_front_levels[station_id][-1] if hist_front_levels[station_id] else None
            act_h = self._fmt(act_back - act_front) if act_back is not None and act_front is not None else "N/A"
            
            text_lines = [
                f"S{station_id} Mode: {actions[station_id].mode}",
                f"Upper MPC  : Q={up_q}",
                f"Head(Pred/Act): {pred_h} / {act_h} m",
                f"Lower Pred : Q={dn_q}",
                f"Actual     : Q={act_q}, Eff={act_eff}%",
                f"Deviations : dQ={dq}, dZ={dz}",
                "-" * 30
            ]
            
            actual_snapshot = hist_unit_status[-1][station_id] if hist_unit_status else {}
            for unit in station.units:
                actual_payload = actual_snapshot.get(unit.name, {"Status": 0, "Opening": 0.0})
                actual_status = "ON" if int(actual_payload.get("Status", 0)) == 1 else "OFF"
                command_status = "ON" if int(action.unit_status.get(unit.id, 0)) == 1 else "OFF"
                actual_opening = float(actual_payload.get("Opening", 0.0))
                command_opening = float(action.unit_openings.get(unit.id, 0.0))
                
                text_lines.append(
                    f"U{unit.id}: {actual_status}({self._fmt(actual_opening):>5}) -> {command_status}({self._fmt(command_opening):>5})"
                )
                
            ax_text.text(
                0.02, 0.5,
                "\n".join(text_lines),
                transform=ax_text.transAxes,
                ha="left", va="center",
                fontsize=11, family="monospace",
                bbox={"boxstyle": "round", "facecolor": "#f8f9fa", "alpha": 0.9, "edgecolor": "#cccccc"}
            )
            
        ax_dist = fig.add_subplot(gs[n_stations, :])
        disturbance_times, demand_series, rain_series = self._disturbance_reference_series()
        disturbance_palette = plt.cm.tab20(np.linspace(0.1, 0.9, max(len(pool_ids), 1)))
        for p_idx, pool_id in enumerate(pool_ids):
            color = disturbance_palette[p_idx % len(disturbance_palette)]
            ax_dist.plot(times_hist, hist_disturbances[pool_id], color=color, linestyle="-", label=f"Pool{pool_id} Dist Est")
            ax_dist.plot(disturbance_times, demand_series.get(pool_id, np.zeros_like(disturbance_times)), color=color, alpha=0.6, label=f"Plan Pool{pool_id}")
            ax_dist.step(disturbance_times, rain_series.get(pool_id, np.zeros_like(disturbance_times)), where="post", color=color, linestyle="--", alpha=0.8, label=f"Rain Pool{pool_id}")
            
        series_for_limit = [
            *[np.asarray(hist_disturbances[pool_id]) for pool_id in pool_ids],
            *[np.asarray(demand_series.get(pool_id, np.zeros_like(disturbance_times))) for pool_id in pool_ids],
            *[np.asarray(rain_series.get(pool_id, np.zeros_like(disturbance_times))) for pool_id in pool_ids],
        ]
        non_empty = [series for series in series_for_limit if series.size]
        all_d = np.concatenate(non_empty) if non_empty else np.asarray([0.0])
        limit = max(np.max(np.abs(all_d)) * 1.1, 0.01)
        ax_dist.set_ylim([-limit, limit])
        ax_dist.set_title("System Disturbances (Estimates vs Plans)")
        ax_dist.set_ylabel("Disturbance")
        ax_dist.set_xlabel("Hour")
        ax_dist.set_xlim([0, self.hours])
        ax_dist.legend(loc="upper right", ncol=len(pool_ids), fontsize=8)
        ax_dist.grid(True)
        
        for p_idx, segment in enumerate(segments):
            ax_pool = fig.add_subplot(gs[n_stations + 1 + p_idx, :])
            up_st_id = segment.upstream_station_id
            dn_st_id = segment.downstream_station_id
            p_color = disturbance_palette[p_idx % len(disturbance_palette)] if len(disturbance_palette) > 0 else "blue"
            
            if up_st_id in hist_back_levels:
                ax_pool.plot(times_hist, hist_back_levels[up_st_id], color=p_color, linestyle="-", label=f"Actual Z_up (S{up_st_id} back)")
            if dn_st_id in hist_front_levels:
                ax_pool.plot(times_hist, hist_front_levels[dn_st_id], color=p_color, linestyle="--", alpha=0.7, label=f"Actual Z_dn (S{dn_st_id} front)")
                
            if up_st_id in upper_plan.station_back_levels and len(upper_plan.station_back_levels[up_st_id]) > 0:
                ax_pool.step(times_upper, upper_plan.station_back_levels[up_st_id], color=p_color, linestyle=":", alpha=0.6, where="post", label=f"Pred Z_up (S{up_st_id})")
            if dn_st_id in upper_plan.station_front_levels and len(upper_plan.station_front_levels[dn_st_id]) > 0:
                ax_pool.step(times_upper, upper_plan.station_front_levels[dn_st_id], color=p_color, linestyle="-.", alpha=0.6, where="post", label=f"Pred Z_dn (S{dn_st_id})")
                
            ax_pool.set_title(f"Pool {segment.id} Level (S{up_st_id} -> S{dn_st_id})")
            ax_pool.set_ylabel("Level (m)")
            ax_pool.set_xlim([0, self.hours])
            ax_pool.legend(loc="upper right", ncol=4, fontsize=8)
            ax_pool.grid(True)
        
        plt.tight_layout(rect=[0.0, 0.0, 1.0, 0.98])
        step_plot_path = self.steps_dir / f"step_{step_index:03d}.png"
        fig.savefig(step_plot_path, dpi=180)
        plt.close(fig)

    def _plot_results(self, history: pd.DataFrame) -> None:
        import matplotlib.pyplot as plt

        time_col = "time_hours" if "time_hours" in history.columns else "hour"
        station_ids = self.system_config.station_ids
        pool_ids = self.system_config.pool_ids
        observer_df = history[history["station_id"] == self.system_config.first_station_id]
        disturbance_times, demand_series, rain_series = self._disturbance_reference_series()
        
        station_palette = plt.cm.tab10(np.linspace(0.2, 0.9, max(len(station_ids), 1)))
        
        for idx_st, station_id in enumerate(station_ids):
            fig, axes = plt.subplots(4, 1, figsize=(12, 16), sharex=True)
            station_df = history[history["station_id"] == station_id]
            st_color = station_palette[idx_st % len(station_palette)]
            
            axes[0].plot(station_df[time_col], station_df["ref_flow"], linestyle="--", color=st_color, alpha=0.5, label=f"S{station_id} ref")
            axes[0].plot(station_df[time_col], station_df["actual_flow"], color=st_color, label=f"S{station_id} actual")
            
            axes[1].plot(station_df[time_col], station_df["actual_back_level"], color=st_color, label=f"S{station_id} back")
            axes[1].plot(station_df[time_col], station_df["actual_front_level"], linestyle="--", color=st_color, label=f"S{station_id} front")
            
            mode_map = {"ODD1": 1, "ODD2": 2, "ODD3": 3}
            axes[2].step(station_df[time_col], station_df["mode"].map(mode_map), where="post", color=st_color, label=f"S{station_id}")
            
            axes[3].plot(station_df[time_col], station_df["actual_upper_flow_error"], linestyle="-.", color=st_color, label=f"S{station_id} actual-upper")
            axes[3].plot(station_df[time_col], station_df["actual_lower_flow_error"], linestyle=":", color=st_color, label=f"S{station_id} actual-lower")
            
            palette = plt.cm.tab20(np.linspace(0.1, 0.9, max(len(pool_ids), 1)))
            for idx, pool_id in enumerate(pool_ids):
                color = palette[idx % len(palette)]
                column = f"disturbance_estimate_pool_{pool_id}"
                if column in observer_df.columns:
                    axes[3].plot(observer_df[time_col], observer_df[column], color=color, label=f"Observer pool {pool_id}")
                axes[3].plot(
                    disturbance_times,
                    demand_series.get(pool_id, np.zeros_like(disturbance_times)),
                    color=color,
                    alpha=0.8,
                    label=f"Plan pool {pool_id}",
                )
                axes[3].step(
                    disturbance_times,
                    rain_series.get(pool_id, np.zeros_like(disturbance_times)),
                    where="post",
                    color=color,
                    linestyle="--",
                    alpha=0.8,
                    label=f"Rain pool {pool_id}",
                )
            
            axes[0].set_title(f"Station {station_id} Overview")
            axes[0].set_ylabel("Flow")
            axes[1].set_ylabel("Level")
            axes[2].set_ylabel("Mode")
            axes[3].set_ylabel("Disturbance & Errors")
            axes[3].set_xlabel("Hour")
            
            for axis in axes:
                axis.grid(True, alpha=0.3)
                axis.legend(loc="best", fontsize=8)
                
            fig.tight_layout()
            fig.savefig(self.output_dir / f"closed_loop_overview_{station_id}.png", dpi=200)
            plt.close(fig)

    def _plot_step(
        self,
        step_index: int,
        current_time_hours: float,
        lower_step_hours: float,
        upper_plan,
        lower_prediction_plan,
        lower_prediction,
        hist_times,
        hist_flows,
        hist_back_levels,
        hist_front_levels,
        hist_pool_levels,
        hist_disturbances,
        hist_upper_flow_errors,
        hist_lower_flow_errors,
        hist_efficiencies,
        hist_odd_flow_errors,
        hist_odd_level_errors,
        actions,
        decisions,
        hist_unit_status,
    ) -> None:
        station_ids = self.system_config.station_ids
        pool_ids = self.system_config.pool_ids
        n_stations = len(station_ids)
        segments = getattr(self.system_config.topology, 'channel_segments', []) if hasattr(self.system_config, 'topology') else []
        n_rows = n_stations + 1 + len(segments)
        fig = plt.figure(figsize=(34, 4.5 * n_rows + 5))
        gs = fig.add_gridspec(n_rows, 6)
        fig.suptitle(
            f"Step {step_index:03d} | Modes: {self._current_mode_summary(actions)}",
            fontsize=18,
            y=0.99,
        )
        times_hist = np.asarray(hist_times, dtype=float)
        plan_len = len(lower_prediction_plan[station_ids[0]]) if station_ids else 0
        upper_len = len(upper_plan.flow_refs[station_ids[0]]) if station_ids else 0
        times_plan = current_time_hours + np.arange(plan_len, dtype=float) * lower_step_hours
        times_upper = current_time_hours + np.arange(upper_len, dtype=float) * float(self.system_config.dt_hours)
        
        station_palette = plt.cm.tab10(np.linspace(0.2, 0.9, max(n_stations, 1)))
        cmap_cycle = [plt.cm.Blues, plt.cm.Greens, plt.cm.Reds, plt.cm.Purples, plt.cm.Oranges, plt.cm.Greys]
        station_palettes = {
            station.id: cmap_cycle[idx % len(cmap_cycle)](
                np.linspace(0.45, 0.9, len(station.units))
            )
            for idx, station in enumerate(self.system_config.stations)
        }
        
        for idx, station_id in enumerate(station_ids):
            color = station_palette[idx % len(station_palette)]
            station = self.system_config.station_by_id[station_id]
            action = actions[station_id]
            
            # 1. Flow
            ax_flow = fig.add_subplot(gs[idx, 0])
            ax_flow.plot(times_hist, hist_flows[station_id], color=color, linestyle="-", label="Actual Q")
            ax_flow.plot(times_plan, lower_prediction_plan[station_id], color=color, linestyle="--", alpha=0.5, label="Lower Pred")
            ax_flow.step(times_upper, upper_plan.flow_refs[station_id], color=color, linestyle=":", where="post", alpha=0.8, label="Upper Plan")
            ax_flow.set_title(f"S{station_id} Flow")
            ax_flow.set_ylabel("Flow (m3/s)")
            ax_flow.set_xlim([0, self.hours])
            ax_flow.legend(loc="upper right", fontsize=8)
            ax_flow.grid(True)
            
            # 2. Head
            ax_head = fig.add_subplot(gs[idx, 1])
            
            act_back_arr = np.array(hist_back_levels[station_id]) if hist_back_levels[station_id] else np.array([])
            act_front_arr = np.array(hist_front_levels[station_id]) if hist_front_levels[station_id] else np.array([])
            if act_back_arr.size > 0 and act_front_arr.size > 0:
                ax_head.plot(times_hist, act_back_arr - act_front_arr, color=color, linestyle="-", label="Actual Head")
                
            pred_back_arr = np.array(upper_plan.station_back_levels.get(station_id, []))
            pred_front_arr = np.array(upper_plan.station_front_levels.get(station_id, []))
            if pred_back_arr.size > 0 and pred_front_arr.size > 0:
                ax_head.step(times_upper, pred_back_arr - pred_front_arr, color=color, linestyle=":", alpha=0.8, where="post", label="Pred Head")
                
            ax_head.set_title(f"S{station_id} Head")
            ax_head.set_ylabel("Head (m)")
            ax_head.set_xlim([0, self.hours])
            ax_head.legend(loc="upper right", fontsize=8)
            ax_head.grid(True)
            
            # 3. Efficiency
            ax_eff = fig.add_subplot(gs[idx, 2])
            ax_eff.plot(times_hist, hist_efficiencies[station_id], color=color, linestyle="-", label="Efficiency %")
            ax_eff.plot(times_plan, self._predicted_series(action.predicted_efficiencies, hist_efficiencies[station_id], len(times_plan)), color=color, linestyle="--", alpha=0.5, label="Pred Eff")
            ax_eff.set_title(f"S{station_id} Efficiency")
            ax_eff.set_ylabel("Eff (%)")
            ax_eff.set_xlim([0, self.hours])
            ax_eff.set_ylim([0, 100])
            ax_eff.legend(loc="lower right", fontsize=8)
            ax_eff.grid(True)
            
            # 4. Blade Angles
            ax_angle = fig.add_subplot(gs[idx, 3])
            palette_st = station_palettes[station_id]
            for u_idx, unit in enumerate(station.units):
                actual_angles = [step_data[station_id][unit.name]["Opening"] for step_data in hist_unit_status]
                pred_angles = [float(action.unit_openings.get(unit.id, 0.0))] * len(times_plan)
                u_color = palette_st[u_idx]
                ax_angle.plot(times_hist, actual_angles, color=u_color, label=f"U{unit.id} Actual")
                ax_angle.plot(times_plan, pred_angles, "--", color=u_color, alpha=0.55)
            ax_angle.set_title(f"S{station_id} Blade Angles")
            ax_angle.set_ylabel("Angle")
            ax_angle.set_xlim([0, self.hours])
            ax_angle.legend(loc="upper right", ncol=2, fontsize=7)
            ax_angle.grid(True)
            
            # 5. ODD Domain
            ax_odd = fig.add_subplot(gs[idx, 4])
            odd3_boundary = max(float(self.runtime.odd3_flow_tolerance), float(self.runtime.odd1_flow_tolerance))
            ymax = max(
                odd3_boundary * 1.2,
                max(hist_odd_flow_errors[station_id]) if hist_odd_flow_errors[station_id] else odd3_boundary,
            )
            ax_odd.axhspan(0.0, self.runtime.odd1_flow_tolerance, color="#d9f2d9", alpha=0.55, label="ODD1")
            ax_odd.axhspan(self.runtime.odd1_flow_tolerance, odd3_boundary, color="#fff2cc", alpha=0.55, label="ODD2")
            ax_odd.axhspan(odd3_boundary, ymax, color="#fce5cd", alpha=0.55, label="ODD3")
            ax_odd.axhline(self.runtime.odd1_flow_tolerance, color="#6aa84f", linestyle=":")
            ax_odd.axhline(odd3_boundary, color="#bf9000", linestyle=":")
            
            ax_odd.plot(times_hist, hist_odd_flow_errors[station_id], color=color, linestyle="-", label="dQ Decision")
            if hist_odd_flow_errors[station_id]:
                ax_odd.scatter(times_hist[-1], hist_odd_flow_errors[station_id][-1], color=color, s=36, zorder=5)
            ax_odd.set_title(f"S{station_id} ODD Domain")
            ax_odd.set_ylabel("dQ (m3/s)")
            ax_odd.set_xlim([0, self.hours])
            ax_odd.set_ylim([0.0, ymax])
            ax_odd.legend(loc="upper right", fontsize=7)
            ax_odd.grid(True)
            
            # 6. Detailed Text Summary
            ax_text = fig.add_subplot(gs[idx, 5])
            ax_text.axis("off")
            
            up_q = self._fmt(upper_plan.flow_refs[station_id][0]) if len(upper_plan.flow_refs[station_id]) > 0 else "N/A"
            dn_q = self._fmt(lower_prediction_plan[station_id][0]) if len(lower_prediction_plan[station_id]) > 0 else "N/A"
            act_q = self._fmt(hist_flows[station_id][-1]) if hist_flows[station_id] else "N/A"
            act_eff = self._fmt(hist_efficiencies[station_id][-1]) if hist_efficiencies[station_id] else "N/A"
            dq = self._fmt(decisions[station_id].flow_error)
            dz = self._fmt(decisions[station_id].level_error)
            
            pred_back = upper_plan.station_back_levels[station_id][0] if station_id in upper_plan.station_back_levels and len(upper_plan.station_back_levels[station_id]) > 0 else None
            pred_front = upper_plan.station_front_levels[station_id][0] if station_id in upper_plan.station_front_levels and len(upper_plan.station_front_levels[station_id]) > 0 else None
            pred_h = self._fmt(pred_back - pred_front) if pred_back is not None and pred_front is not None else "N/A"
            
            act_back = hist_back_levels[station_id][-1] if hist_back_levels[station_id] else None
            act_front = hist_front_levels[station_id][-1] if hist_front_levels[station_id] else None
            act_h = self._fmt(act_back - act_front) if act_back is not None and act_front is not None else "N/A"
            
            text_lines = [
                f"S{station_id} Mode: {actions[station_id].mode}",
                f"Upper MPC  : Q={up_q}",
                f"Head(Pred/Act): {pred_h} / {act_h} m",
                f"Lower Pred : Q={dn_q}",
                f"Actual     : Q={act_q}, Eff={act_eff}%",
                f"Deviations : dQ={dq}, dZ={dz}",
                "-" * 30
            ]
            
            actual_snapshot = hist_unit_status[-1][station_id] if hist_unit_status else {}
            for unit in station.units:
                actual_payload = actual_snapshot.get(unit.name, {"Status": 0, "Opening": 0.0})
                actual_status = "ON" if int(actual_payload.get("Status", 0)) == 1 else "OFF"
                command_status = "ON" if int(action.unit_status.get(unit.id, 0)) == 1 else "OFF"
                actual_opening = float(actual_payload.get("Opening", 0.0))
                command_opening = float(action.unit_openings.get(unit.id, 0.0))
                
                text_lines.append(
                    f"U{unit.id}: {actual_status}({self._fmt(actual_opening):>5}) -> {command_status}({self._fmt(command_opening):>5})"
                )
                
            ax_text.text(
                0.02, 0.5,
                "\n".join(text_lines),
                transform=ax_text.transAxes,
                ha="left", va="center",
                fontsize=11, family="monospace",
                bbox={"boxstyle": "round", "facecolor": "#f8f9fa", "alpha": 0.9, "edgecolor": "#cccccc"}
            )
            
        ax_dist = fig.add_subplot(gs[n_stations, :])
        disturbance_times, demand_series, rain_series = self._disturbance_reference_series()
        disturbance_palette = plt.cm.tab20(np.linspace(0.1, 0.9, max(len(pool_ids), 1)))
        for p_idx, pool_id in enumerate(pool_ids):
            color = disturbance_palette[p_idx % len(disturbance_palette)]
            ax_dist.plot(times_hist, hist_disturbances[pool_id], color=color, linestyle="-", label=f"Pool{pool_id} Dist Est")
            ax_dist.plot(disturbance_times, demand_series.get(pool_id, np.zeros_like(disturbance_times)), color=color, alpha=0.6, label=f"Plan Pool{pool_id}")
            ax_dist.step(disturbance_times, rain_series.get(pool_id, np.zeros_like(disturbance_times)), where="post", color=color, linestyle="--", alpha=0.8, label=f"Rain Pool{pool_id}")
            
        series_for_limit = [
            *[np.asarray(hist_disturbances[pool_id]) for pool_id in pool_ids],
            *[np.asarray(demand_series.get(pool_id, np.zeros_like(disturbance_times))) for pool_id in pool_ids],
            *[np.asarray(rain_series.get(pool_id, np.zeros_like(disturbance_times))) for pool_id in pool_ids],
        ]
        non_empty = [series for series in series_for_limit if series.size]
        all_d = np.concatenate(non_empty) if non_empty else np.asarray([0.0])
        limit = max(np.max(np.abs(all_d)) * 1.1, 0.01)
        ax_dist.set_ylim([-limit, limit])
        ax_dist.set_title("System Disturbances (Estimates vs Plans)")
        ax_dist.set_ylabel("Disturbance")
        ax_dist.set_xlabel("Hour")
        ax_dist.set_xlim([0, self.hours])
        ax_dist.legend(loc="upper right", ncol=len(pool_ids), fontsize=8)
        ax_dist.grid(True)
        
        for p_idx, segment in enumerate(segments):
            ax_pool = fig.add_subplot(gs[n_stations + 1 + p_idx, :])
            up_st_id = segment.upstream_station_id
            dn_st_id = segment.downstream_station_id
            p_color = disturbance_palette[p_idx % len(disturbance_palette)] if len(disturbance_palette) > 0 else "blue"
            
            if up_st_id in hist_back_levels:
                ax_pool.plot(times_hist, hist_back_levels[up_st_id], color=p_color, linestyle="-", label=f"Actual Z_up (S{up_st_id} back)")
            if dn_st_id in hist_front_levels:
                ax_pool.plot(times_hist, hist_front_levels[dn_st_id], color=p_color, linestyle="--", alpha=0.7, label=f"Actual Z_dn (S{dn_st_id} front)")
                
            if up_st_id in upper_plan.station_back_levels and len(upper_plan.station_back_levels[up_st_id]) > 0:
                ax_pool.step(times_upper, upper_plan.station_back_levels[up_st_id], color=p_color, linestyle=":", alpha=0.6, where="post", label=f"Pred Z_up (S{up_st_id})")
            if dn_st_id in upper_plan.station_front_levels and len(upper_plan.station_front_levels[dn_st_id]) > 0:
                ax_pool.step(times_upper, upper_plan.station_front_levels[dn_st_id], color=p_color, linestyle="-.", alpha=0.6, where="post", label=f"Pred Z_dn (S{dn_st_id})")
                
            ax_pool.set_title(f"Pool {segment.id} Level (S{up_st_id} -> S{dn_st_id})")
            ax_pool.set_ylabel("Level (m)")
            ax_pool.set_xlim([0, self.hours])
            ax_pool.legend(loc="upper right", ncol=4, fontsize=8)
            ax_pool.grid(True)
        
        plt.tight_layout(rect=[0.0, 0.0, 1.0, 0.98])
        step_plot_path = self.steps_dir / f"step_{step_index:03d}.png"
        fig.savefig(step_plot_path, dpi=180)
        plt.close(fig)

    def _plot_results(self, history: pd.DataFrame) -> None:
        time_col = "time_hours" if "time_hours" in history.columns else "hour"
        station_ids = self.system_config.station_ids
        pool_ids = self.system_config.pool_ids
        observer_df = history[history["station_id"] == self.system_config.first_station_id]
        disturbance_times, demand_series, rain_series = self._disturbance_reference_series()
        
        station_palette = plt.cm.tab10(np.linspace(0.2, 0.9, max(len(station_ids), 1)))
        
        for idx_st, station_id in enumerate(station_ids):
            fig, axes = plt.subplots(4, 1, figsize=(12, 16), sharex=True)
            station_df = history[history["station_id"] == station_id]
            st_color = station_palette[idx_st % len(station_palette)]
            
            axes[0].plot(station_df[time_col], station_df["ref_flow"], linestyle="--", color=st_color, alpha=0.5, label=f"S{station_id} ref")
            axes[0].plot(station_df[time_col], station_df["actual_flow"], color=st_color, label=f"S{station_id} actual")
            
            axes[1].plot(station_df[time_col], station_df["actual_back_level"], color=st_color, label=f"S{station_id} back")
            axes[1].plot(station_df[time_col], station_df["actual_front_level"], linestyle="--", color=st_color, label=f"S{station_id} front")
            
            mode_map = {"ODD1": 1, "ODD2": 2, "ODD3": 3}
            axes[2].step(station_df[time_col], station_df["mode"].map(mode_map), where="post", color=st_color, label=f"S{station_id}")
            
            axes[3].plot(station_df[time_col], station_df["actual_upper_flow_error"], linestyle="-.", color=st_color, label=f"S{station_id} actual-upper")
            axes[3].plot(station_df[time_col], station_df["actual_lower_flow_error"], linestyle=":", color=st_color, label=f"S{station_id} actual-lower")
            
            palette = plt.cm.tab20(np.linspace(0.1, 0.9, max(len(pool_ids), 1)))
            for idx, pool_id in enumerate(pool_ids):
                color = palette[idx % len(palette)]
                column = f"disturbance_estimate_pool_{pool_id}"
                if column in observer_df.columns:
                    axes[3].plot(observer_df[time_col], observer_df[column], color=color, label=f"Observer pool {pool_id}")
                axes[3].plot(
                    disturbance_times,
                    demand_series.get(pool_id, np.zeros_like(disturbance_times)),
                    color=color,
                    alpha=0.8,
                    label=f"Plan pool {pool_id}",
                )
                axes[3].step(
                    disturbance_times,
                    rain_series.get(pool_id, np.zeros_like(disturbance_times)),
                    where="post",
                    color=color,
                    linestyle="--",
                    alpha=0.8,
                    label=f"Rain pool {pool_id}",
                )
            
            axes[0].set_title(f"Station {station_id} Overview")
            axes[0].set_ylabel("Flow")
            axes[1].set_ylabel("Level")
            axes[2].set_ylabel("Mode")
            axes[3].set_ylabel("Disturbance & Errors")
            axes[3].set_xlabel("Hour")
            
            for axis in axes:
                axis.grid(True, alpha=0.3)
                axis.legend(loc="best", fontsize=8)
                
            fig.tight_layout()
            fig.savefig(self.output_dir / f"closed_loop_overview_{station_id}.png", dpi=200)
            plt.close(fig)
