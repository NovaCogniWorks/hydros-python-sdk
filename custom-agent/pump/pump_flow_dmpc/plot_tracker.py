"""独立的下层执行结果绘图跟踪器。

与 ``custom-agent/pump/scheduling/plot_tracker.py`` 解耦，只记录并可视化
``pump_flow_dmpc`` 边缘控制算法每次 ``solve`` 产生的实际决策，不读取调度
闭环仿真对象，也不写入 scheduling 的输出目录。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型提示
    from hydros_agent_sdk.control_algorithms import (
        ControlAlgorithmInput,
        ControlAlgorithmOutput,
    )
    from .types import PumpFlowDmpcArguments
    from .odd_dmpc.types import ControlAction


logger = logging.getLogger(__name__)


class PumpFlowDmpcExecutionTracker:
    """记录并绘制泵站流量 DMPC 下层控制器的逐次执行结果。"""

    DEFAULT_OUTPUT_SUBDIR = Path("output") / "edge_execution"

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        *,
        save_step_plots: bool = True,
        save_summary_excel: bool = True,
    ) -> None:
        if output_dir is None:
            output_dir = (
                Path(__file__).resolve().parent / self.DEFAULT_OUTPUT_SUBDIR
            )
        self.output_dir = Path(output_dir)
        self.steps_dir = self.output_dir / "steps"
        self.save_step_plots = save_step_plots
        self.save_summary_excel = save_summary_excel

        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.save_step_plots:
            self.steps_dir.mkdir(parents=True, exist_ok=True)

        self._records: List[Dict[str, Any]] = []
        self._stations: Dict[int, List[int]] = {}

    # ------------------------------------------------------------------
    # 记录入口
    # ------------------------------------------------------------------
    def record_decision(
        self,
        *,
        input_data: "ControlAlgorithmInput",
        arguments: "PumpFlowDmpcArguments",
        action: "ControlAction",
        output: "ControlAlgorithmOutput",
    ) -> None:
        """记录一次下层控制决策并可选地输出本步图表。"""

        request_id = self._first_not_none(
            getattr(getattr(input_data, "context", None), "request_id", None),
            getattr(output, "request_id", None),
        ) or ""
        step_index = getattr(getattr(input_data, "context", None), "step_index", None)
        station_id = self._to_int(
            self._first_not_none(
                getattr(arguments, "station_id", None),
                getattr(action, "station_id", None),
            )
        )
        if station_id is None:
            logger.warning(
                "pump flow DMPC execution tracker: cannot resolve station_id, skip record"
            )
            return

        target_flow = self._first_series_value(
            getattr(arguments, "reference_flow", None)
        )

        record: Dict[str, Any] = {
            "request_id": str(request_id),
            "step_index": self._to_int(step_index),
            "order": len(self._records),
            "station_id": station_id,
            "target_flow": self._to_float(target_flow),
            "selected_flow": self._to_float(getattr(action, "selected_flow", None)),
            "mode": str(getattr(action, "mode", "") or ""),
            "current_flow": self._to_float(getattr(arguments, "current_flow", None)),
            "current_head": self._to_float(getattr(arguments, "current_head", None)),
            "current_front_level": self._to_float(
                getattr(arguments, "current_front_level", None)
            ),
            "current_back_level": self._to_float(
                getattr(arguments, "current_back_level", None)
            ),
            "fit_score": self._to_float(getattr(action, "fit_score", None)),
            "objective": self._to_float(getattr(action, "objective", None)),
            "predicted_flow_error": self._to_float(
                getattr(action, "predicted_flow_error", None)
            ),
            "predicted_level_error": self._to_float(
                getattr(action, "predicted_level_error", None)
            ),
            "predicted_back_level": self._to_float(
                getattr(action, "predicted_back_level", None)
            ),
            "predicted_front_level": self._to_float(
                getattr(action, "predicted_front_level", None)
            ),
            "predicted_head": self._to_float(
                getattr(action, "predicted_head", None)
            ),
            "unit_status": self._normalize_int_map(
                getattr(action, "unit_status", None)
            ),
            "unit_openings": self._normalize_float_map(
                getattr(action, "unit_openings", None)
            ),
            "unit_flows": self._normalize_float_map(
                getattr(action, "unit_flows", None)
            ),
            "predicted_efficiencies": self._to_float_list(
                getattr(action, "predicted_efficiencies", None)
            ),
            "predicted_unit_efficiencies": self._normalize_float_list_map(
                getattr(action, "predicted_unit_efficiencies", None)
            ),
            "actuator_targets": self._extract_actuator_targets(output),
        }

        self._records.append(record)
        self._stations.setdefault(station_id, []).append(record["order"])

        if self.save_step_plots:
            try:
                self._plot_step(record)
            except Exception:
                logger.exception(
                    "pump flow DMPC execution tracker: step plot failed requestId=%s step=%s",
                    record["request_id"],
                    record["step_index"],
                )

    # ------------------------------------------------------------------
    # 汇总输出
    # ------------------------------------------------------------------
    def finalize(self) -> None:
        """生成全部历史记录的汇总图与 Excel，失败不影响控制流程。"""

        if not self._records:
            logger.info("pump flow DMPC execution tracker: no records to finalize")
            return

        try:
            for station_id in sorted(self._stations):
                self._plot_station_summary(station_id)
        except Exception:
            logger.exception(
                "pump flow DMPC execution tracker: summary plot failed"
            )

        if self.save_summary_excel:
            try:
                self._export_excel()
            except Exception:
                logger.exception(
                    "pump flow DMPC execution tracker: excel export failed"
                )

    # ------------------------------------------------------------------
    # 数据抽取辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _first_not_none(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    @staticmethod
    def _first_series_value(series: Optional[List[float]]) -> float:
        if not series:
            return 0.0
        try:
            return float(series[0])
        except (TypeError, ValueError, IndexError):
            return 0.0

    @staticmethod
    def _to_float(value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _to_float_list(cls, values: Any) -> List[float]:
        if not values:
            return []
        if isinstance(values, (list, tuple)):
            return [cls._to_float(v) for v in values]
        return [cls._to_float(values)]

    @staticmethod
    def _normalize_int_map(values: Any) -> Dict[int, int]:
        result: Dict[int, int] = {}
        if not isinstance(values, dict):
            return result
        for key, value in values.items():
            try:
                result[int(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _normalize_float_map(values: Any) -> Dict[int, float]:
        result: Dict[int, float] = {}
        if not isinstance(values, dict):
            return result
        for key, value in values.items():
            try:
                result[int(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return result

    @classmethod
    def _normalize_float_list_map(
        cls, values: Any
    ) -> Dict[int, List[float]]:
        result: Dict[int, List[float]] = {}
        if not isinstance(values, dict):
            return result
        for key, value in values.items():
            try:
                unit_id = int(key)
            except (TypeError, ValueError):
                continue
            result[unit_id] = cls._to_float_list(value)
        return result

    @staticmethod
    def _extract_actuator_targets(output: "ControlAlgorithmOutput") -> List[Dict[str, Any]]:
        targets: List[Dict[str, Any]] = []
        for target in getattr(output, "actuator_targets", None) or []:
            target_values = getattr(target, "target_values", None) or {}
            targets.append(
                {
                    "object_id": getattr(target, "object_id", None),
                    "available": bool(getattr(target, "available", True)),
                    "blade_angle": (
                        target_values.get("blade_angle")
                        if isinstance(target_values, dict)
                        else None
                    ),
                }
            )
        return targets

    # ------------------------------------------------------------------
    # 绘图
    # ------------------------------------------------------------------
    def _record_axis(self, records: List[Dict[str, Any]]) -> List[int]:
        return list(range(len(records)))

    def _step_label(self, record: Dict[str, Any]) -> str:
        step = record.get("step_index")
        if step is None:
            return f"order {record.get('order')}"
        return f"step {step}"

    def _plot_step(self, record: Dict[str, Any]) -> None:
        station_id = record["station_id"]
        units = sorted(
            set(record["unit_openings"]) | set(record["unit_status"]) | set(record["unit_flows"])
        )
        fig, (ax_angle, ax_flow) = plt.subplots(
            2, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [2, 1]}
        )
        fig.suptitle(
            f"Pump flow DMPC edge execution | station {station_id} | "
            f"{self._step_label(record)} | mode {record['mode']}",
            fontsize=14,
        )

        x = list(range(len(units)))
        angles = [record["unit_openings"].get(u, 0.0) for u in units]
        colors = [
            "#2c7fb8" if record["unit_status"].get(u, 0) == 1 else "#d0d0d0"
            for u in units
        ]
        ax_angle.bar(x, angles, color=colors)
        ax_angle.set_xticks(x)
        ax_angle.set_xticklabels([f"U{u}" for u in units])
        ax_angle.set_ylabel("Blade angle (deg)")
        ax_angle.set_title("Commanded blade angle")

        flows = [record["unit_flows"].get(u, 0.0) for u in units]
        ax_flow.bar(x, flows, color=colors)
        ax_flow.set_xticks(x)
        ax_flow.set_xticklabels([f"U{u}" for u in units])
        ax_flow.set_ylabel("Unit flow (m3/s)")
        ax_flow.set_title("Commanded unit flow")

        fig.text(
            0.01,
            0.02,
            (
                f"target={record['target_flow']:.2f} m3/s | "
                f"selected={record['selected_flow']:.2f} m3/s | "
                f"head={record['current_head']:.2f} m | "
                f"fit={record['fit_score']:.3f} | objective={record['objective']:.3f} | "
                f"flow_err={record['predicted_flow_error']:.3f}"
            ),
            fontsize=9,
        )
        fig.tight_layout(rect=[0, 0.05, 1, 0.97])
        filename = self._step_filename(record)
        fig.savefig(filename)
        plt.close(fig)

    def _step_filename(self, record: Dict[str, Any]) -> Path:
        step = record.get("step_index")
        step_text = f"{step:04d}" if isinstance(step, int) else f"o{record['order']:04d}"
        return self.steps_dir / f"step_{step_text}_station_{record['station_id']}.png"

    def _plot_station_summary(self, station_id: int) -> None:
        records = [self._records[i] for i in self._stations[station_id]]
        if not records:
            return

        x = self._record_axis(records)
        tick_labels = [self._step_label(r) for r in records]

        fig, axes = plt.subplots(3, 2, figsize=(16, 15))
        fig.suptitle(
            f"Pump flow DMPC edge execution summary | station {station_id}",
            fontsize=15,
        )

        # 1. 流量：目标 vs 下层命令 vs 当前观测
        ax = axes[0, 0]
        ax.plot(x, [r["target_flow"] for r in records], "o--", label="Target flow")
        ax.plot(x, [r["selected_flow"] for r in records], "s-", label="Selected flow")
        if any(r["current_flow"] for r in records):
            ax.plot(x, [r["current_flow"] for r in records], "x:", label="Current flow")
        ax.set_xticks(x)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=7)
        ax.set_ylabel("Flow (m3/s)")
        ax.set_title("Flow command vs target")
        ax.legend()
        ax.grid(True, alpha=0.3)

        # 2. 叶片角命令
        ax = axes[0, 1]
        self._plot_unit_lines(
            ax, records, x, tick_labels, "unit_openings", "Blade angle (deg)"
        )
        ax.set_title("Commanded blade angle per unit")
        ax.grid(True, alpha=0.3)

        # 3. 机组启停
        ax = axes[1, 0]
        self._plot_unit_lines(
            ax, records, x, tick_labels, "unit_status", "Unit status"
        )
        ax.set_title("Commanded unit on/off status")
        ax.grid(True, alpha=0.3)

        # 4. 机组流量
        ax = axes[1, 1]
        self._plot_unit_lines(
            ax, records, x, tick_labels, "unit_flows", "Unit flow (m3/s)"
        )
        ax.set_title("Commanded unit flow")
        ax.grid(True, alpha=0.3)

        # 5. 质量指标
        ax = axes[2, 0]
        ax.plot(x, [r["fit_score"] for r in records], "o-", label="fit_score")
        ax.plot(x, [r["objective"] for r in records], "s-", label="objective")
        ax.plot(
            x,
            [r["predicted_flow_error"] for r in records],
            "^-",
            label="predicted_flow_error",
        )
        ax.set_xticks(x)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=7)
        ax.set_title("Decision quality metrics")
        ax.legend()
        ax.grid(True, alpha=0.3)

        # 6. 预测效率（如果有）
        ax = axes[2, 1]
        efficiency_series = self._collect_unit_efficiencies(records)
        if efficiency_series:
            for unit_id in sorted(efficiency_series):
                ax.plot(
                    x,
                    efficiency_series[unit_id],
                    marker=".",
                    label=f"U{unit_id}",
                )
            ax.set_title("Predicted unit efficiency")
            ax.legend()
        else:
            ax.text(
                0.5,
                0.5,
                "No efficiency data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_title("Predicted unit efficiency")
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        output_file = self.output_dir / f"summary_station_{station_id}.png"
        fig.savefig(output_file)
        plt.close(fig)

    def _plot_unit_lines(
        self,
        ax,
        records: List[Dict[str, Any]],
        x: List[int],
        tick_labels: List[str],
        field: str,
        ylabel: str,
    ) -> None:
        unit_ids = sorted(
            {unit_id for r in records for unit_id in r[field]}
        )
        for unit_id in unit_ids:
            values = [r[field].get(unit_id, 0.0) for r in records]
            ax.plot(x, values, marker=".", label=f"U{unit_id}")
        ax.set_xticks(x)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=7)
        ax.set_ylabel(ylabel)
        if len(unit_ids) <= 8:
            ax.legend(fontsize=7)

    def _collect_unit_efficiencies(
        self, records: List[Dict[str, Any]]
    ) -> Dict[int, List[float]]:
        """汇总各机组的首步预测效率序列，缺失值按 0 补齐。"""

        unit_ids = {
            unit_id
            for record in records
            for unit_id in record["predicted_unit_efficiencies"]
        }
        result: Dict[int, List[float]] = {}
        if unit_ids:
            for record in records:
                predicted_unit = record["predicted_unit_efficiencies"]
                for unit_id in unit_ids:
                    series = predicted_unit.get(unit_id, [])
                    result.setdefault(unit_id, []).append(
                        series[0] if series else 0.0
                    )
            return result

        # 只有扁平序列时，绘制一条站点代表效率曲线。
        if any(record["predicted_efficiencies"] for record in records):
            result[0] = [
                record["predicted_efficiencies"][0]
                if record["predicted_efficiencies"]
                else 0.0
                for record in records
            ]
        return result

    # ------------------------------------------------------------------
    # Excel 导出
    # ------------------------------------------------------------------
    def _export_excel(self) -> None:
        summary_rows: List[Dict[str, Any]] = []
        unit_rows: List[Dict[str, Any]] = []

        for record in self._records:
            summary_rows.append(
                {
                    "request_id": record["request_id"],
                    "step_index": record["step_index"],
                    "station_id": record["station_id"],
                    "mode": record["mode"],
                    "target_flow": record["target_flow"],
                    "selected_flow": record["selected_flow"],
                    "current_flow": record["current_flow"],
                    "current_head": record["current_head"],
                    "current_front_level": record["current_front_level"],
                    "current_back_level": record["current_back_level"],
                    "fit_score": record["fit_score"],
                    "objective": record["objective"],
                    "predicted_flow_error": record["predicted_flow_error"],
                    "predicted_level_error": record["predicted_level_error"],
                }
            )
            unit_ids = sorted(
                set(record["unit_openings"])
                | set(record["unit_status"])
                | set(record["unit_flows"])
            )
            for unit_id in unit_ids:
                unit_rows.append(
                    {
                        "request_id": record["request_id"],
                        "step_index": record["step_index"],
                        "station_id": record["station_id"],
                        "unit_id": unit_id,
                        "mode": record["mode"],
                        "blade_angle": record["unit_openings"].get(unit_id, 0.0),
                        "status": record["unit_status"].get(unit_id, 0),
                        "unit_flow": record["unit_flows"].get(unit_id, 0.0),
                    }
                )

        output_file = self.output_dir / "edge_execution_summary.xlsx"
        try:
            with pd.ExcelWriter(output_file) as writer:
                pd.DataFrame(summary_rows).to_excel(
                    writer, sheet_name="Execution_Summary", index=False
                )
                pd.DataFrame(unit_rows).to_excel(
                    writer, sheet_name="Unit_Commands", index=False
                )
            logger.info(
                "pump flow DMPC execution tracker: excel exported to %s",
                output_file,
            )
        except Exception:
            logger.exception(
                "pump flow DMPC execution tracker: xlsx export failed, fallback to csv"
            )
            pd.DataFrame(summary_rows).to_csv(
                self.output_dir / "edge_execution_summary.csv", index=False
            )
            pd.DataFrame(unit_rows).to_csv(
                self.output_dir / "unit_commands.csv", index=False
            )
