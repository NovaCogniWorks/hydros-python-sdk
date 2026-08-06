"""Console presentation for lower pump-flow DMPC decisions."""

from __future__ import annotations

from typing import Callable, List, Optional

from hydros_agent_sdk.control_algorithms import (
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
)

from .odd_dmpc.types import ControlAction
from .types import PumpFlowDmpcArguments


class PumpFlowDmpcConsoleReporter:
    """Render one lower-control decision as grouped tab-separated tables."""

    def __init__(self, printer: Callable[..., None] = print) -> None:
        self._printer = printer

    def report_success(
        self,
        input_data: ControlAlgorithmInput,
        arguments: PumpFlowDmpcArguments,
        action: ControlAction,
        output: ControlAlgorithmOutput,
    ) -> None:
        lines = [
            "========== 下层泵站流量控制 ==========",
            self._reference_table(arguments),
            self._station_result_table(input_data, arguments, action, output),
            self._unit_result_table(action),
            "========================================",
        ]
        self._printer("\n".join(lines), flush=True)

    def report_failure(
        self,
        input_data: ControlAlgorithmInput,
        output: ControlAlgorithmOutput,
    ) -> None:
        station_id = input_data.context.target_object_id
        lines = [
            "========== 下层泵站流量控制失败 ==========",
            "请求ID\t泵站\t状态\t错误码\t错误信息",
            "\t".join(
                [
                    self._cell(output.request_id),
                    self._station_label(station_id),
                    self._cell(output.status.value),
                    self._cell(output.error_code),
                    self._cell(output.error_message),
                ]
            ),
            "==========================================",
        ]
        self._printer("\n".join(lines), flush=True)

    def _reference_table(self, arguments: PumpFlowDmpcArguments) -> str:
        lines = [
            "[上层参考序列]",
            "时域步\t目标流量\t前池水位\t后池水位\t扬程",
        ]
        horizon = max(
            len(arguments.reference_flow),
            len(arguments.reference_front_level),
            len(arguments.reference_back_level),
            len(arguments.reference_head),
        )
        for index in range(horizon):
            lines.append(
                "\t".join(
                    [
                        f"H{index + 1}",
                        self._series_value(arguments.reference_flow, index),
                        self._series_value(arguments.reference_front_level, index),
                        self._series_value(arguments.reference_back_level, index),
                        self._series_value(arguments.reference_head, index),
                    ]
                )
            )
        return "\n".join(lines)

    def _station_result_table(
        self,
        input_data: ControlAlgorithmInput,
        arguments: PumpFlowDmpcArguments,
        action: ControlAction,
        output: ControlAlgorithmOutput,
    ) -> str:
        return "\n".join(
            [
                "[站级求解结果]",
                "请求ID\t泵站\t模式\t目标流量\t选定流量\t流量误差\t拟合度\t目标函数\t状态",
                "\t".join(
                    [
                        self._cell(input_data.context.request_id),
                        self._station_label(arguments.station_id),
                        self._cell(action.mode),
                        self._number(self._first(arguments.reference_flow)),
                        self._number(action.selected_flow),
                        self._number(action.predicted_flow_error),
                        self._number(action.fit_score, digits=4),
                        self._number(action.objective, digits=4),
                        self._cell(output.status.value),
                    ]
                ),
            ]
        )

    def _unit_result_table(self, action: ControlAction) -> str:
        lines = [
            "[机组控制结果]",
            "机组\t状态\t叶片角\t分配流量\t效率",
        ]
        unit_ids = sorted(
            set(action.unit_status)
            | set(action.unit_openings)
            | set(action.unit_flows)
        )
        for unit_id in unit_ids:
            status = int(action.unit_status.get(unit_id, 0))
            efficiency = self._first_unit_efficiency(action, unit_id)
            lines.append(
                "\t".join(
                    [
                        str(unit_id),
                        "运行" if status == 1 else "停机",
                        self._number(action.unit_openings.get(unit_id)),
                        self._number(action.unit_flows.get(unit_id)),
                        self._number(efficiency, digits=4),
                    ]
                )
            )
        if not unit_ids:
            lines.append("-\t-\t-\t-\t-")
        return "\n".join(lines)

    @classmethod
    def _series_value(cls, values: List[float], index: int) -> str:
        if index >= len(values):
            return "-"
        return cls._number(values[index])

    @staticmethod
    def _first(values: List[float]) -> Optional[float]:
        return values[0] if values else None

    @staticmethod
    def _first_unit_efficiency(
        action: ControlAction,
        unit_id: int,
    ) -> Optional[float]:
        values = action.predicted_unit_efficiencies.get(unit_id, [])
        return values[0] if values else None

    @staticmethod
    def _station_label(station_id: Optional[int]) -> str:
        return f"S{station_id}" if station_id is not None else "-"

    @staticmethod
    def _cell(value: object) -> str:
        if value is None:
            return "-"
        return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _number(value: Optional[float], digits: int = 2) -> str:
        if value is None:
            return "-"
        return f"{float(value):.{digits}f}"
