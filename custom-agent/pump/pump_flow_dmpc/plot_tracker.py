"""泵站流量 DMPC 下层执行结果绘图跟踪器（与 scheduling 同风格）。

本模块复用 ``custom-agent/pump/scheduling/plot_tracker.py`` 的绘图逻辑，
把每次边缘控制器的 ``ControlAction`` 适配成 scheduling 绘图所需的数据形状，
因此生成的单步图、汇总图与 scheduling 的图片输出保持一致。

- 不改动 scheduling 代码。
- 默认输出到 ``output/agent_steps``（与 scheduling 相同），可通过
  ``output_dir`` / ``--plot-output-dir`` / 环境变量改为其它目录，避免覆盖。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import queue
import threading
from types import SimpleNamespace
from typing import Any, Dict, Optional, TYPE_CHECKING

from .odd_dmpc.types import ControlAction, SystemConfig
from .types import PumpFlowDmpcArguments

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型提示
    from hydros_agent_sdk.control_algorithms import (
        ControlAlgorithmInput,
        ControlAlgorithmOutput,
    )


logger = logging.getLogger(__name__)

_SCHEDULING_DIR = Path(__file__).resolve().parents[1] / "scheduling"
if str(_SCHEDULING_DIR) not in sys.path:
    sys.path.insert(0, str(_SCHEDULING_DIR))

# 后台线程画图必须使用无 GUI 后端，避免 TkAgg 在非主线程报错。
os.environ["MPLBACKEND"] = "Agg"

try:
    from plot_tracker import PlotHistoryTracker as SchedulingPlotHistoryTracker
except Exception:  # pragma: no cover - 依赖缺失时由上层降级处理
    SchedulingPlotHistoryTracker = None
    logger.exception("cannot import scheduling PlotHistoryTracker")


class PumpFlowDmpcExecutionTracker:
    """适配边缘求解结果，并调用 scheduling 的绘图跟踪器输出同风格图片。"""

    DEFAULT_OUTPUT_DIR = Path("output") / "agent_steps"

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        *,
        save_step_plots: bool = True,
        save_summary_excel: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir is not None else self.DEFAULT_OUTPUT_DIR
        self.save_step_plots = save_step_plots
        self.save_summary_excel = save_summary_excel

        self._scheduling_tracker = None
        self._system_config: Optional[SystemConfig] = None
        self._latest_arguments: Dict[int, PumpFlowDmpcArguments] = {}
        self._latest_actions: Dict[int, ControlAction] = {}
        self._order = 0

        self._queue = queue.Queue()
        self._worker = threading.Thread(
            target=self._run_worker,
            name="pump-flow-dmpc-plot-worker",
            daemon=True,
        )
        self._worker.start()
        self._finalized = False

    # ------------------------------------------------------------------
    # 记录入口
    # ------------------------------------------------------------------
    def record_decision(
        self,
        *,
        input_data: "ControlAlgorithmInput",
        arguments: PumpFlowDmpcArguments,
        action: ControlAction,
        output: "ControlAlgorithmOutput",
        system_config: Optional[SystemConfig] = None,
    ) -> None:
        """记录单站决策并绘图（向后兼容入口）。"""

        self.record_decisions(
            [(input_data, arguments, action, output)],
            system_config=system_config,
        )

    def record_decisions(
        self,
        decisions: list,
        *,
        system_config: Optional[SystemConfig] = None,
    ) -> None:
        """一次记录多个泵站决策；绘图在后台线程异步执行。"""

        self._queue.put(("record", list(decisions), system_config))

    def finalize(self) -> None:
        """等待后台绘图完成并生成汇总图与 Excel。"""

        if self._finalized:
            return
        self._finalized = True
        self._queue.put(("finalize", None, None))
        self._queue.join()

    # ------------------------------------------------------------------
    # 后台工作线程
    # ------------------------------------------------------------------
    def _run_worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                kind = job[0]
                if kind == "record":
                    _, decisions, system_config = job
                    self._record_sync(decisions, system_config=system_config)
                elif kind == "finalize":
                    self._finalize_sync()
                    break
            except Exception:
                logger.exception(
                    "pump flow DMPC execution tracker: background plot worker failed"
                )
            finally:
                self._queue.task_done()

    def _record_sync(
        self,
        decisions: list,
        *,
        system_config: Optional[SystemConfig] = None,
    ) -> None:
        if system_config is not None:
            self._system_config = system_config

        request_id = ""
        recorded_station_id = None
        for item in decisions:
            input_data, arguments, action, output = item
            station_id = self._station_id(arguments, action)
            if station_id is None:
                logger.warning(
                    "pump flow DMPC execution tracker: cannot resolve station_id, skip record"
                )
                continue
            self._latest_arguments[station_id] = arguments
            self._latest_actions[station_id] = action
            recorded_station_id = station_id
            request_id = request_id or getattr(
                getattr(input_data, "context", None), "request_id", ""
            )

        if self._system_config is None:
            return

        if self._scheduling_tracker is None:
            self._init_scheduling_tracker()

        step_index = self._order
        self._order += 1

        if not self.save_step_plots:
            return

        try:
            self._plot_step(step_index)
        except Exception:
            logger.exception(
                "pump flow DMPC execution tracker: step plot failed requestId=%s station=%s",
                request_id,
                recorded_station_id,
            )

    def _finalize_sync(self) -> None:
        if self._scheduling_tracker is None:
            logger.info("pump flow DMPC execution tracker: no history to finalize")
            return

        if not self.save_summary_excel:
            return

        try:
            self._scheduling_tracker.generate_summary_plot()
        except Exception:
            logger.exception(
                "pump flow DMPC execution tracker: summary plot failed"
            )

    # ------------------------------------------------------------------
    # 适配与构造
    # ------------------------------------------------------------------
    def _init_scheduling_tracker(self) -> None:
        if SchedulingPlotHistoryTracker is None:
            raise RuntimeError("scheduling PlotHistoryTracker unavailable")

        tracker = SchedulingPlotHistoryTracker(
            system_config=self._system_config,
            demand_plan=None,
            output_dir=self.output_dir,
        )
        tracker.step_predictions = []
        self._scheduling_tracker = tracker

    def _plot_step(self, step_index: int) -> None:
        cfg = self._system_config
        station_ids = cfg.station_ids
        pool_ids = cfg.pool_ids

        actions: Dict[int, ControlAction] = {}
        decisions: Dict[int, SimpleNamespace] = {}
        station_flows: Dict[int, float] = {}
        station_back_levels: Dict[int, float] = {}
        station_front_levels: Dict[int, float] = {}
        station_heads: Dict[int, float] = {}
        upper_flow: Dict[int, list] = {}
        upper_back: Dict[int, list] = {}
        upper_front: Dict[int, list] = {}
        transfer_bundles: Dict[int, SimpleNamespace] = {}

        for sid in station_ids:
            station = cfg.station_by_id[sid]
            action = self._latest_actions.get(sid) or self._default_action(sid, station)
            arguments = self._latest_arguments.get(sid) or self._default_arguments(sid)

            actions[sid] = action
            decisions[sid] = SimpleNamespace(
                flow_error=self._float(getattr(action, "predicted_flow_error", None)),
                level_error=self._float(getattr(action, "predicted_level_error", None)),
            )

            flow = self._float(getattr(arguments, "current_flow", None))
            if flow == 0.0:
                flow = self._float(getattr(action, "selected_flow", None))
            back = self._float(getattr(arguments, "current_back_level", None))
            front = self._float(getattr(arguments, "current_front_level", None))
            head = self._float(getattr(arguments, "current_head", None))

            station_flows[sid] = flow
            station_back_levels[sid] = back
            station_front_levels[sid] = front
            station_heads[sid] = head

            upper_flow[sid] = self._series(getattr(arguments, "reference_flow", None), flow)
            upper_back[sid] = self._series(
                getattr(arguments, "reference_back_level", None), back
            )
            upper_front[sid] = self._series(
                getattr(arguments, "reference_front_level", None), front
            )
            transfer_bundles[sid] = SimpleNamespace(
                disturbance_estimate={pid: 0.0 for pid in pool_ids}
            )

        observation = SimpleNamespace(
            station_flows=station_flows,
            station_back_levels=station_back_levels,
            station_front_levels=station_front_levels,
            station_heads=station_heads,
            pool_levels={pid: 0.0 for pid in pool_ids},
        )
        upper_plan = SimpleNamespace(
            flow_refs=upper_flow,
            station_back_levels=upper_back,
            station_front_levels=upper_front,
        )

        self._scheduling_tracker.update_and_plot(
            step_index=int(step_index),
            current_time_hours=float(step_index),
            lower_step_hours=float(getattr(cfg, "dt_hours", 1.0) or 1.0),
            upper_plan=upper_plan,
            actions=actions,
            decisions=decisions,
            observation=observation,
            transfer_bundles=transfer_bundles,
        )

    def _default_action(self, station_id: int, station) -> ControlAction:
        unit_ids = [unit.id for unit in getattr(station, "units", [])]
        return ControlAction(
            station_id=station_id,
            mode="ODD1",
            selected_flow=0.0,
            unit_status={unit_id: 0 for unit_id in unit_ids},
            unit_openings={unit_id: 0.0 for unit_id in unit_ids},
            unit_flows={unit_id: 0.0 for unit_id in unit_ids},
            fit_score=0.0,
            objective=0.0,
            predicted_flow_error=0.0,
            predicted_level_error=0.0,
        )

    def _default_arguments(self, station_id: int) -> PumpFlowDmpcArguments:
        return PumpFlowDmpcArguments(
            station_id=station_id,
            mode="ODD1",
            config_path="",
            reference_flow=[0.0],
            reference_front_level=[0.0],
            reference_back_level=[0.0],
            reference_head=[0.0],
        )

    @staticmethod
    def _station_id(arguments: PumpFlowDmpcArguments, action: ControlAction) -> Optional[int]:
        for value in (
            getattr(arguments, "station_id", None),
            getattr(action, "station_id", None),
        ):
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _float(value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _series(cls, values: Any, fallback: float) -> list:
        if isinstance(values, (list, tuple)) and values:
            return [cls._float(v) for v in values]
        return [fallback]
