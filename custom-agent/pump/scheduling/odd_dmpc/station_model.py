from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

from .types import StationConfig


@dataclass
class CandidateRow:
    flow: float
    head: float
    efficiency: float
    unit_status: Dict[int, int]
    unit_openings: Dict[int, float]
    unit_flows: Dict[int, float]
    unit_names: Dict[int, str]


class PumpStationModel:
    def __init__(self, station_config: StationConfig, optimal_flow_table: pd.DataFrame):
        self.id = station_config.id
        self.name = station_config.name
        self.config = station_config
        self.df = optimal_flow_table.copy()
        self.unit_name_by_id = station_config.unit_name_by_id
        self._normalized = self._normalize_table(self.df)
        self.q_vals: Optional[np.ndarray] = None
        self.h_vals: Optional[np.ndarray] = None
        self.eff_grid: Optional[np.ndarray] = None
        self.feasible_grid: Optional[np.ndarray] = None
        self.eff_interp: Optional[RegularGridInterpolator] = None
        self.flow_step: float = 1.0
        self._candidate_cache: Dict[Tuple[float, Tuple[int, ...], Tuple[int, ...], float], List[CandidateRow]] = {}
        self._curve_cache: Dict[Tuple[float, Tuple[int, ...], Tuple[int, ...], float], List[Tuple[float, float]]] = {}
        self._build_interpolator()

    def _cache_key(
        self,
        head: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> Tuple[float, Tuple[int, ...], Tuple[int, ...], float]:
        required_key = tuple(sorted(required_active_ids or ()))
        available_key = tuple(sorted(available_unit_ids or self.unit_name_by_id.keys()))
        return (round(float(head), 4), required_key, available_key, round(float(tolerance), 4))

    def _normalize_table(self, df: pd.DataFrame) -> pd.DataFrame:
        normalized = df.copy()
        normalized["总流量(m³/s)"] = pd.to_numeric(normalized["总流量(m³/s)"], errors="coerce")
        normalized["扬程(m)"] = pd.to_numeric(normalized["扬程(m)"], errors="coerce")
        normalized["平均效率(%)"] = pd.to_numeric(normalized["平均效率(%)"], errors="coerce")
        for unit_id, unit_name in self.unit_name_by_id.items():
            prefix = f"泵_{unit_name}"
            status_col = f"{prefix}_状态"
            if status_col not in normalized.columns:
                normalized[status_col] = 0
            else:
                normalized[status_col] = normalized[status_col].map(
                    lambda x: 1 if str(x).lower() == "true" else 0
                )
            for suffix in ["流量", "有用功(kW)", "效率(%)", "开度"]:
                column = f"{prefix}_{suffix}"
                if column not in normalized.columns:
                    normalized[column] = 0.0
                else:
                    normalized[column] = pd.to_numeric(
                        normalized[column], errors="coerce"
                    )
        return normalized

    def _build_interpolator(self) -> None:
        df_clean = self._normalized.dropna(subset=["总流量(m³/s)", "扬程(m)"])
        self.q_vals = np.sort(df_clean["总流量(m³/s)"].unique())
        self.h_vals = np.sort(df_clean["扬程(m)"].unique())
        positive_q_steps = np.diff(self.q_vals)
        positive_q_steps = positive_q_steps[positive_q_steps > 1e-6]
        if positive_q_steps.size:
            self.flow_step = float(np.min(positive_q_steps))
        eff_grid = np.full((len(self.h_vals), len(self.q_vals)), np.nan)
        feasible_grid = np.zeros_like(eff_grid, dtype=bool)

        for i, head in enumerate(self.h_vals):
            head_rows = df_clean[df_clean["扬程(m)"] == head]
            for j, flow in enumerate(self.q_vals):
                row = head_rows[head_rows["总流量(m³/s)"] == flow]
                if row.empty:
                    continue
                value = row.iloc[0]["平均效率(%)"]
                feasible = not pd.isna(value)
                feasible_grid[i, j] = feasible
                if feasible:
                    eff_grid[i, j] = float(value)

        fill_grid = eff_grid.copy()
        fill_grid[np.isnan(fill_grid)] = -1.0
        self.eff_grid = eff_grid
        self.feasible_grid = feasible_grid
        self.eff_interp = RegularGridInterpolator(
            (self.h_vals, self.q_vals),
            fill_grid,
            bounds_error=False,
            fill_value=-1.0,
        )

    def get_efficiency(self, head: float, flow: float) -> Optional[float]:
        if self.eff_interp is None:
            return None
        value = float(self.eff_interp((head, flow)))
        return value if value >= 0 else None

    def theoretical_curve(
        self,
        head: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> List[Tuple[float, float]]:
        cache_key = self._cache_key(head, required_active_ids, available_unit_ids, tolerance)
        cached = self._curve_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        best_by_flow: Dict[float, Tuple[Tuple[float, float], float]] = {}
        for candidate in self.candidate_rows(
            head=head,
            required_active_ids=required_active_ids,
            available_unit_ids=available_unit_ids,
            tolerance=tolerance,
        ):
            score = (abs(candidate.head - head), -candidate.efficiency)
            previous = best_by_flow.get(candidate.flow)
            if previous is None or score < previous[0]:
                best_by_flow[candidate.flow] = (score, candidate.efficiency)
        curve = [
            (float(flow), float(payload[1]))
            for flow, payload in sorted(best_by_flow.items(), key=lambda item: item[0])
        ]
        self._curve_cache[cache_key] = list(curve)
        return curve

    def feasible_flow_segments(
        self,
        head: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> List[Tuple[float, float]]:
        curve = self.theoretical_curve(
            head=head,
            required_active_ids=required_active_ids,
            available_unit_ids=available_unit_ids,
            tolerance=tolerance,
        )
        if not curve:
            return []
        max_gap = max(self.flow_step * 1.5, 1e-6)
        segments: List[Tuple[float, float]] = []
        segment_start = curve[0][0]
        prev_flow = curve[0][0]
        for flow, _ in curve[1:]:
            if flow - prev_flow > max_gap:
                segments.append((float(segment_start), float(prev_flow)))
                segment_start = flow
            prev_flow = flow
        segments.append((float(segment_start), float(prev_flow)))
        return segments

    def interpolate_efficiency(
        self,
        head: float,
        flow: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> Optional[float]:
        curve = self.theoretical_curve(
            head=head,
            required_active_ids=required_active_ids,
            available_unit_ids=available_unit_ids,
            tolerance=tolerance,
        )
        if not curve:
            return None
        max_gap = max(self.flow_step * 1.5, 1e-6)
        segment: List[Tuple[float, float]] = [curve[0]]
        for point in curve[1:]:
            if point[0] - segment[-1][0] > max_gap:
                if segment[0][0] - 1e-6 <= flow <= segment[-1][0] + 1e-6:
                    xs = [item[0] for item in segment]
                    ys = [item[1] for item in segment]
                    return float(np.interp(flow, xs, ys))
                segment = [point]
            else:
                segment.append(point)
        if segment[0][0] - 1e-6 <= flow <= segment[-1][0] + 1e-6:
            xs = [item[0] for item in segment]
            ys = [item[1] for item in segment]
            return float(np.interp(flow, xs, ys))
        return None

    def project_flow_to_feasible(
        self,
        head: float,
        target_flow: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> Optional[float]:
        segments = self.feasible_flow_segments(
            head=head,
            required_active_ids=required_active_ids,
            available_unit_ids=available_unit_ids,
            tolerance=tolerance,
        )
        if not segments:
            return None
        best_projection = None
        for flow_min, flow_max in segments:
            if flow_min - 1e-6 <= target_flow <= flow_max + 1e-6:
                return float(target_flow)
            projected = flow_min if target_flow < flow_min else flow_max
            distance = abs(projected - target_flow)
            if best_projection is None or distance < best_projection[0]:
                best_projection = (distance, float(projected))
        return None if best_projection is None else best_projection[1]

    def is_feasible(
        self,
        head: float,
        flow: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> bool:
        return self.interpolate_efficiency(
            head=head,
            flow=flow,
            required_active_ids=required_active_ids,
            available_unit_ids=available_unit_ids,
            tolerance=tolerance,
        ) is not None

    def feasible_flow_range(
        self,
        head: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> Tuple[float, float]:
        segments = self.feasible_flow_segments(
            head=head,
            required_active_ids=required_active_ids,
            available_unit_ids=available_unit_ids,
            tolerance=tolerance,
        )
        if not segments:
            return 0.0, 0.0
        return float(min(item[0] for item in segments)), float(max(item[1] for item in segments))

    def check_operating_point(
        self,
        head: float,
        flow: float,
        head_tolerance: float = 0.0,
    ) -> Dict[str, object]:
        """检查实际工况点 (head, flow) 是否在缓存表的 H/Q 覆盖范围内。

        Args:
            head: 实际扬程 (m)。
            flow: 实际流量 (m³/s)，传 0 表示只检查扬程。
            head_tolerance: 允许扬程超出表格范围的容差 (m)，与 head_search_tolerance 保持一致。

        Returns:
            dict 包含:
                head_ok (bool): 扬程在 [h_min - tol, h_max + tol] 内。
                flow_ok (bool): 流量在 [q_min, q_max] 内（flow=0 时视为 True）。
                h_min, h_max: 表格扬程覆盖范围。
                q_min, q_max: 表格流量覆盖范围。
                head_excess (float): 超出范围的量（正值表示超上界，负值超下界，0 表示在范围内）。
                flow_excess (float): 超出范围的量。
        """
        h_min = float(self.h_vals[0]) if self.h_vals is not None and len(self.h_vals) > 0 else 0.0
        h_max = float(self.h_vals[-1]) if self.h_vals is not None and len(self.h_vals) > 0 else 0.0
        q_min = float(self.q_vals[0]) if self.q_vals is not None and len(self.q_vals) > 0 else 0.0
        q_max = float(self.q_vals[-1]) if self.q_vals is not None and len(self.q_vals) > 0 else 0.0

        tol = float(head_tolerance)
        head_ok = (h_min - tol) <= float(head) <= (h_max + tol)
        if float(head) < h_min - tol:
            head_excess = float(head) - (h_min - tol)  # 负值：低于下界
        elif float(head) > h_max + tol:
            head_excess = float(head) - (h_max + tol)  # 正值：超过上界
        else:
            head_excess = 0.0

        if float(flow) <= 0.0:
            flow_ok = True
            flow_excess = 0.0
        else:
            flow_ok = q_min <= float(flow) <= q_max
            if float(flow) < q_min:
                flow_excess = float(flow) - q_min  # 负值：低于下界
            elif float(flow) > q_max:
                flow_excess = float(flow) - q_max  # 正值：超过上界
            else:
                flow_excess = 0.0

        return {
            "head_ok": head_ok,
            "flow_ok": flow_ok,
            "head": float(head),
            "flow": float(flow),
            "h_min": h_min,
            "h_max": h_max,
            "q_min": q_min,
            "q_max": q_max,
            "head_excess": head_excess,
            "flow_excess": flow_excess,
        }

    def global_feasible_flow_range(
        self,
        available_unit_ids: Optional[Iterable[int]] = None,
    ) -> Tuple[float, float]:
        available_set = set(available_unit_ids or self.unit_name_by_id.keys())
        feasible_flows: List[float] = []
        for _, row in self._normalized.iterrows():
            if pd.isna(row["平均效率(%)"]) or pd.isna(row["总流量(m³/s)"]):
                continue
            active_ids = {
                unit_id
                for unit_id, unit_name in self.unit_name_by_id.items()
                if int(row[f"泵_{unit_name}_状态"]) == 1
            }
            if active_ids and active_ids.issubset(available_set):
                feasible_flows.append(float(row["总流量(m³/s)"]))
        if not feasible_flows:
            return 0.0, 0.0
        return float(min(feasible_flows)), float(max(feasible_flows))

    def candidate_rows(
        self,
        head: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> List[CandidateRow]:
        cache_key = self._cache_key(head, required_active_ids, available_unit_ids, tolerance)
        cached = self._candidate_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        df = self._normalized
        required_set = set(required_active_ids or [])
        available_set = set(available_unit_ids or self.unit_name_by_id.keys())
        if not available_set:
            return []

        filtered = df[
            (df["扬程(m)"] >= head - tolerance) &
            (df["扬程(m)"] <= head + tolerance) &
            (~df["平均效率(%)"].isna())
        ]
        rows: List[CandidateRow] = []
        for _, row in filtered.iterrows():
            status_map = {
                unit_id: int(row[f"泵_{unit_name}_状态"])
                for unit_id, unit_name in self.unit_name_by_id.items()
                if unit_id in available_set
            }
            active_ids = {unit_id for unit_id, status in status_map.items() if status == 1}
            if required_set and active_ids != required_set:
                continue
            if not active_ids.issubset(available_set):
                continue
            rows.append(
                CandidateRow(
                    flow=float(row["总流量(m³/s)"]),
                    head=float(row["扬程(m)"]),
                    efficiency=float(row["平均效率(%)"]),
                    unit_status=status_map,
                    unit_openings={
                        unit_id: float(row[f"泵_{self.unit_name_by_id[unit_id]}_开度"])
                        if not np.isnan(row[f"泵_{self.unit_name_by_id[unit_id]}_开度"])
                        else 0.0
                        for unit_id in available_set
                    },
                    unit_flows={
                        unit_id: float(row[f"泵_{self.unit_name_by_id[unit_id]}_流量"])
                        if not np.isnan(row[f"泵_{self.unit_name_by_id[unit_id]}_流量"])
                        else 0.0
                        for unit_id in available_set
                    },
                    unit_names={unit_id: self.unit_name_by_id[unit_id] for unit_id in available_set},
                )
            )
        rows.sort(key=lambda item: (abs(item.head - head), -item.efficiency))
        self._candidate_cache[cache_key] = list(rows)
        return rows

    def best_row_for_target(
        self,
        target_flow: float,
        head: float,
        required_active_ids: Optional[Iterable[int]] = None,
        available_unit_ids: Optional[Iterable[int]] = None,
        tolerance: float = 0.35,
    ) -> Optional[CandidateRow]:
        candidates = self.candidate_rows(
            head=head,
            required_active_ids=required_active_ids,
            available_unit_ids=available_unit_ids,
            tolerance=tolerance,
        )
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (abs(item.flow - target_flow), abs(item.head - head), -item.efficiency),
        )
