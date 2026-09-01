from __future__ import annotations

from dataclasses import dataclass


def clip(value: float, low: float, high: float) -> float:
    value = float(value)
    if value < low:
        return float(low)
    if value > high:
        return float(high)
    return value


@dataclass(frozen=True)
class HydroNHQGenerator:
    """Pure V47 NHQ helper.

    The original HydroSim.V47 script builds tables for plotting and demos. The
    runtime control path only needs the query semantics: given head H and power
    P, estimate turbine flow Q and efficiency eta.
    """

    design_head: float = 50.0
    max_head: float = 80.0
    min_head: float = 30.0
    design_power: float = 100.0
    min_power: float = 20.0
    max_power: float = 120.0
    design_efficiency: float = 0.93
    eta_head_coeff: float = 0.20
    eta_power_coeff: float = 0.40

    def __post_init__(self) -> None:
        if self.min_head <= 0 or self.min_power <= 0:
            raise ValueError("min_head/min_power must be greater than zero.")
        if self.max_head <= self.min_head or self.max_power <= self.min_power:
            raise ValueError("head/power bounds are invalid.")

    def query(self, head: float, power: float) -> tuple[float, float]:
        clipped_head = clip(head, self.min_head, self.max_head)
        clipped_power = clip(power, self.min_power, self.max_power)
        return self._calc_flow(clipped_head, clipped_power)

    def _calc_efficiency(self, head: float, power: float) -> float:
        head_ratio = abs(head / self.design_head - 1.0)
        power_ratio = abs(power / self.design_power - 1.0)
        eta = (
            self.design_efficiency
            - self.eta_head_coeff * head_ratio * head_ratio
            - self.eta_power_coeff * power_ratio * power_ratio
        )
        return max(float(eta), 0.5)

    def _calc_flow(self, head: float, power: float) -> tuple[float, float]:
        efficiency = self._calc_efficiency(head, power)
        flow = power * 1000.0 / (9.81 * head * efficiency)
        return float(flow), float(efficiency)
