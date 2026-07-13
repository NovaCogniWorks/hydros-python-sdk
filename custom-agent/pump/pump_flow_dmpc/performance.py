"""泵性能曲线访问抽象和 YAML 表格实现。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Dict, Mapping, Protocol, Sequence, Tuple, Union

import yaml

from .errors import PumpFlowDmpcError


class PumpPerformanceRepository(Protocol):
    """根据站点、机组、叶片角度和扬程预测机组流量。"""

    def predict_unit_flow(
        self,
        *,
        station_id: int,
        unit_id: int,
        blade_angle: float,
        water_head: float,
    ) -> float:
        """返回有限的预测流量，超出模型工况时抛出确定性错误。"""


@dataclass(frozen=True)
class PumpFlowCurvePoint:
    """泵性能表中的一个扬程、叶片角度、流量样本点。"""

    water_head: float
    blade_angle: float
    water_flow: float


class TabulatedPumpPerformanceRepository:
    """基于规则网格性能表的泵流量预测 repository。

    每台机组的曲线至少包含两个叶片角度样本。若提供多个扬程曲线，先在
    每条曲线上按叶片角度插值，再按扬程线性插值。模型范围外的请求会明确
    失败，避免算法对未知工况做静默外推。
    """

    def __init__(
        self,
        curves: Mapping[Tuple[int, int], Sequence[PumpFlowCurvePoint]],
    ) -> None:
        self._curves = {
            key: self._index_curves(points)
            for key, points in curves.items()
        }

    @classmethod
    def from_yaml(
        cls,
        path: Union[str, Path],
    ) -> "TabulatedPumpPerformanceRepository":
        """从部署侧 YAML 加载泵性能表。"""

        config_path = Path(path)
        try:
            payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PumpFlowDmpcError(
                "PERFORMANCE_CONFIG_UNAVAILABLE",
                "cannot read pump performance config: %s" % config_path,
            ) from exc
        except yaml.YAMLError as exc:
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "invalid pump performance YAML: %s" % config_path,
            ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("stations"), dict):
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "pump performance config requires a stations mapping",
            )

        curves: Dict[Tuple[int, int], Sequence[PumpFlowCurvePoint]] = {}
        for station_key, station_payload in payload["stations"].items():
            if not isinstance(station_payload, dict) or not isinstance(station_payload.get("units"), dict):
                raise PumpFlowDmpcError(
                    "INVALID_PERFORMANCE_CONFIG",
                    "station %s requires a units mapping" % station_key,
                )
            station_id = cls._positive_integer(station_key, "station id")
            for unit_key, unit_payload in station_payload["units"].items():
                if not isinstance(unit_payload, dict) or not isinstance(unit_payload.get("curve"), list):
                    raise PumpFlowDmpcError(
                        "INVALID_PERFORMANCE_CONFIG",
                        "station %s unit %s requires a curve list" % (station_key, unit_key),
                    )
                unit_id = cls._positive_integer(unit_key, "unit id")
                curves[(station_id, unit_id)] = tuple(
                    cls._curve_point(item, station_id, unit_id)
                    for item in unit_payload["curve"]
                )
        return cls(curves)

    def predict_unit_flow(
        self,
        *,
        station_id: int,
        unit_id: int,
        blade_angle: float,
        water_head: float,
    ) -> float:
        self._finite(blade_angle, "blade_angle")
        self._finite(water_head, "water_head")
        curves_by_head = self._curves.get((station_id, unit_id))
        if curves_by_head is None:
            raise PumpFlowDmpcError(
                "MISSING_UNIT_PERFORMANCE_MODEL",
                "missing performance model for station %s unit %s" % (station_id, unit_id),
            )

        lower_head, upper_head = self._bounding_heads(curves_by_head, water_head)
        lower_flow = self._interpolate_angle(
            curves_by_head[lower_head], blade_angle, station_id, unit_id
        )
        if lower_head == upper_head:
            return lower_flow
        upper_flow = self._interpolate_angle(
            curves_by_head[upper_head], blade_angle, station_id, unit_id
        )
        ratio = (water_head - lower_head) / (upper_head - lower_head)
        predicted = lower_flow + ratio * (upper_flow - lower_flow)
        self._finite(predicted, "predicted water_flow")
        return predicted

    @classmethod
    def _index_curves(
        cls,
        points: Sequence[PumpFlowCurvePoint],
    ) -> Mapping[float, Tuple[PumpFlowCurvePoint, ...]]:
        if not points:
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "pump performance curve must not be empty",
            )
        grouped: Dict[float, list[PumpFlowCurvePoint]] = {}
        for point in points:
            cls._finite(point.water_head, "water_head")
            cls._finite(point.blade_angle, "blade_angle")
            cls._finite(point.water_flow, "water_flow")
            grouped.setdefault(point.water_head, []).append(point)

        indexed: Dict[float, Tuple[PumpFlowCurvePoint, ...]] = {}
        for head, head_points in grouped.items():
            ordered = tuple(sorted(head_points, key=lambda item: item.blade_angle))
            if len(ordered) < 2:
                raise PumpFlowDmpcError(
                    "INVALID_PERFORMANCE_CONFIG",
                    "head %s requires at least two blade-angle samples" % head,
                )
            if any(
                left.blade_angle == right.blade_angle
                for left, right in zip(ordered, ordered[1:])
            ):
                raise PumpFlowDmpcError(
                    "INVALID_PERFORMANCE_CONFIG",
                    "duplicate blade-angle sample at head %s" % head,
                )
            indexed[head] = ordered
        return indexed

    @staticmethod
    def _bounding_heads(
        curves_by_head: Mapping[float, Tuple[PumpFlowCurvePoint, ...]],
        water_head: float,
    ) -> Tuple[float, float]:
        heads = tuple(sorted(curves_by_head))
        if water_head < heads[0] or water_head > heads[-1]:
            raise PumpFlowDmpcError(
                "WATER_HEAD_OUT_OF_MODEL_RANGE",
                "water_head %s outside model range [%s, %s]"
                % (water_head, heads[0], heads[-1]),
            )
        lower = max(head for head in heads if head <= water_head)
        upper = min(head for head in heads if head >= water_head)
        return lower, upper

    @staticmethod
    def _interpolate_angle(
        points: Sequence[PumpFlowCurvePoint],
        blade_angle: float,
        station_id: int,
        unit_id: int,
    ) -> float:
        if blade_angle < points[0].blade_angle or blade_angle > points[-1].blade_angle:
            raise PumpFlowDmpcError(
                "BLADE_ANGLE_OUT_OF_MODEL_RANGE",
                "blade_angle %s outside performance model for station %s unit %s"
                % (blade_angle, station_id, unit_id),
            )
        lower = max(
            (point for point in points if point.blade_angle <= blade_angle),
            key=lambda point: point.blade_angle,
        )
        upper = min(
            (point for point in points if point.blade_angle >= blade_angle),
            key=lambda point: point.blade_angle,
        )
        if lower.blade_angle == upper.blade_angle:
            return lower.water_flow
        ratio = (blade_angle - lower.blade_angle) / (upper.blade_angle - lower.blade_angle)
        return lower.water_flow + ratio * (upper.water_flow - lower.water_flow)

    @classmethod
    def _curve_point(
        cls,
        payload: object,
        station_id: int,
        unit_id: int,
    ) -> PumpFlowCurvePoint:
        if not isinstance(payload, dict):
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "station %s unit %s curve point must be a mapping" % (station_id, unit_id),
            )
        try:
            return PumpFlowCurvePoint(
                water_head=float(payload["water_head"]),
                blade_angle=float(payload["blade_angle"]),
                water_flow=float(payload["water_flow"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "station %s unit %s has an invalid curve point" % (station_id, unit_id),
            ) from exc

    @staticmethod
    def _positive_integer(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "%s must be an integer" % label,
            ) from exc
        if parsed <= 0:
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "%s must be positive" % label,
            )
        return parsed

    @staticmethod
    def _finite(value: float, label: str) -> None:
        if not math.isfinite(value):
            raise PumpFlowDmpcError(
                "INVALID_PERFORMANCE_CONFIG",
                "%s must be finite" % label,
            )
