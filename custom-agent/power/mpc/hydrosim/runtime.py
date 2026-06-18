"""
HydroSim_v15.py - 梯级水电站联合仿真
============================================================
目标：
1. 参数化生成来水与总出力指令曲线。
2. 站间出力分配以总出力零误差为硬约束，并尽量保持相邻时步分配变化最小。
3. 水库泄洪使用 PID + 动态前馈过流。
4. 2/3/4 级水库低于目标水位时拒绝新增出力，新增出力优先分配给瀑布沟。
5. 2/3/4 级水库低水位保护采用黄区连续限额、红区强限额，避免硬切换流量尖峰。
6. 导出正式仿真 CSV、运行摘要、调度最小单位配置、图像和 Markdown 报告。
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import time
from typing import Dict, List, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import yaml

from .config import (
    CANAL_TO_NODE,
    CAPA_LOC,
    FLOW_CONFIGS,
    FLOW_STATION_CFGS,
    NODE_TO_INDEX,
    POWER_CONFIGS,
    STATION_CANAL_IDS,
    STATION_NODE_IDS,
    UNIT_CONFIGS,
    __version__,
    build_station_name_map,
    validate_hydrosim_config,
)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "DejaVu Sans", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
np.set_printoptions(precision=2, suppress=True)

_OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# =============================================================================
# 通用工具
# =============================================================================

def _sanitize_filename(name: str) -> str:
    for ch in r'/\:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "figure"


def _set_output_dir(path: str) -> None:
    global _OUTPUT_DIR
    _OUTPUT_DIR = os.path.abspath(path)
    os.makedirs(_OUTPUT_DIR, exist_ok=True)


def _save_fig(name: str) -> None:
    safe = _sanitize_filename(name)
    stamp = datetime.datetime.now().strftime("%Y%m%d.%H%M%S")
    path = os.path.join(_OUTPUT_DIR, f"{safe}_{stamp}.jpg")
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close()


def _clip(value: float, low: float, high: float) -> float:
    value = float(value)
    if value < low:
        return float(low)
    if value > high:
        return float(high)
    return value


# =============================================================================
# 输入信号
# =============================================================================

class NormalizedSignal:
    """多周期正弦叠加信号，默认归一到 [-1, 1]，支持线性缩放。"""

    def __init__(self, steps: int, periods: Sequence[int], seed: int = 555):
        if steps <= 0:
            raise ValueError("steps 必须 > 0。")
        if not periods:
            raise ValueError("periods 不能为空。")
        self.steps = int(steps)
        self.periods = [int(p) for p in periods]
        self.seed = int(seed)
        self.signal = np.zeros(self.steps, dtype=float)
        self._generate()

    def _generate(self) -> None:
        rng = np.random.default_rng(seed=self.seed)
        periods = np.asarray(self.periods, dtype=float)
        amps = rng.uniform(0.0, 1.0, size=periods.shape[0])
        phases = rng.integers(0, 10, size=periods.shape[0]) * np.pi / 10.0
        t = np.arange(self.steps, dtype=float)[:, None]
        raw = (amps * np.sin(2.0 * np.pi * t / periods + phases)).sum(axis=1)
        lo, hi = float(raw.min()), float(raw.max())
        if hi - lo < 1e-12:
            self.signal[:] = 0.0
        else:
            self.signal = (raw - lo) / (hi - lo) * 2.0 - 1.0

    def scale(self, low: float, high: float) -> "NormalizedSignal":
        if high < low:
            raise ValueError("scale 区间要求 high >= low。")
        self.signal = (self.signal + 1.0) / 2.0 * (high - low) + low
        return self

    def signal_plot(self, name: str = "输入信号") -> None:
        plt.figure(figsize=(14, 4))
        plt.plot(self.signal, "b-", linewidth=1.4)
        plt.title(name)
        plt.xlabel("Time / step")
        plt.ylabel("Value")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        _save_fig(name)


# =============================================================================
# 电调层：机组模型 + 电站调度 + 梯级调度
# =============================================================================

class HydroNHQGenerator:
    """
    机组 NHQ 关系：
    输入：水头 H(m), 出力 P(MW)
    输出：流量 Q(m^3/s), 效率 eta
    """

    def __init__(
        self,
        design_head: float = 50.0,
        max_head: float = 80.0,
        min_head: float = 30.0,
        design_power: float = 100.0,
        min_power: float = 20.0,
        max_power: float = 120.0,
        head_steps: int = 24,
        power_steps: int = 24,
        design_efficiency: float = 0.93,
        eta_head_coeff: float = 0.20,
        eta_power_coeff: float = 0.40,
    ):
        if min_head <= 0 or min_power <= 0:
            raise ValueError("min_head/min_power 必须 > 0。")
        if max_head <= min_head or max_power <= min_power:
            raise ValueError("head/power 上下界配置非法。")

        self.design_head = float(design_head)
        self.min_head = float(min_head)
        self.max_head = float(max_head)
        self.design_power = float(design_power)
        self.min_power = float(min_power)
        self.max_power = float(max_power)
        self.head_steps = int(head_steps)
        self.power_steps = int(power_steps)
        self.design_efficiency = float(design_efficiency)
        self.eta_head_coeff = float(eta_head_coeff)
        self.eta_power_coeff = float(eta_power_coeff)

        self.heads: np.ndarray
        self.powers: np.ndarray
        self.data_q: np.ndarray
        self.data_eta: np.ndarray
        self._build_table()

    def _calc_efficiency(self, head: float, power: float) -> float:
        hr = abs(head / self.design_head - 1.0)
        pr = abs(power / self.design_power - 1.0)
        eta = (
            self.design_efficiency
            - self.eta_head_coeff * hr * hr
            - self.eta_power_coeff * pr * pr
        )
        return max(eta, 0.5)

    def _calc_flow(self, head: float, power: float) -> Tuple[float, float]:
        eta = self._calc_efficiency(head, power)
        q = power * 1000.0 / (9.81 * head * eta)
        return float(q), float(eta)

    def _build_table(self) -> None:
        self.heads = np.linspace(self.min_head, self.max_head, self.head_steps)
        self.powers = np.linspace(self.min_power, self.max_power, self.power_steps)
        q = np.zeros((len(self.heads), len(self.powers)), dtype=float)
        eta = np.zeros_like(q)
        for ih, h in enumerate(self.heads):
            for ip, p in enumerate(self.powers):
                q[ih, ip], eta[ih, ip] = self._calc_flow(h, p)
        self.data_q = q
        self.data_eta = eta

    def query(self, head: float, power: float) -> Tuple[float, float]:
        h = _clip(head, self.min_head, self.max_head)
        p = _clip(power, self.min_power, self.max_power)
        return self._calc_flow(h, p)

    def incremental_rate(self, head: float, power: float) -> float:
        p0 = _clip(power, self.min_power, self.max_power)
        dp = min(1.0, p0 - self.min_power, self.max_power - p0)
        if dp <= 1e-9:
            return 0.0
        q1, _ = self.query(head, p0 + dp)
        q2, _ = self.query(head, p0 - dp)
        return abs(q1 - q2) / (2.0 * dp)

    def plot_nhq_curves(self, name: str = "机组NHQ") -> None:
        fig = plt.figure(figsize=(14, 8))
        X, Y = np.meshgrid(self.powers, self.heads)

        ax1 = fig.add_subplot(2, 2, 1)
        for ih in np.linspace(0, len(self.heads) - 1, 5, dtype=int):
            ax1.plot(self.powers, self.data_q[ih, :], lw=1.5, label=f"H={self.heads[ih]:.1f}m")
        ax1.set(xlabel="Power (MW)", ylabel="Flow (m^3/s)", title="N-Q @ fixed H")
        ax1.grid(True, alpha=0.3)
        ax1.legend(fontsize=8)

        ax2 = fig.add_subplot(2, 2, 2)
        for ip in np.linspace(0, len(self.powers) - 1, 5, dtype=int):
            ax2.plot(self.heads, self.data_q[:, ip], lw=1.5, label=f"P={self.powers[ip]:.1f}MW")
        ax2.set(xlabel="Head (m)", ylabel="Flow (m^3/s)", title="H-Q @ fixed P")
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=8)

        ax3 = fig.add_subplot(2, 2, 3)
        c1 = ax3.contourf(X, Y, self.data_q, 40, cmap="coolwarm", alpha=0.9)
        fig.colorbar(c1, ax=ax3, label="Flow (m^3/s)")
        ax3.set(xlabel="Power (MW)", ylabel="Head (m)", title="NHQ-Q")

        ax4 = fig.add_subplot(2, 2, 4)
        c2 = ax4.contourf(X, Y, self.data_eta * 100.0, 40, cmap="coolwarm", alpha=0.9)
        fig.colorbar(c2, ax=ax4, label="eta (%)")
        ax4.set(xlabel="Power (MW)", ylabel="Head (m)", title="NHQ-eta")

        plt.suptitle(name, fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(name)

class HydroUnit:
    """单机组：支持目标跟踪（带双向爬坡）与 NHQ 查表。"""

    def __init__(self, unit_id: int, cfg: Dict):
        self.unit_id = int(unit_id)
        self.unit_name = str(cfg["Name"])
        self.state = int(cfg.get("State", 1))  # 1=运行, 0=停机

        self.design_head = float(cfg["design_head"])
        self.min_head = float(cfg["min_head"])
        self.max_head = float(cfg["max_head"])

        self.design_power = float(cfg["design_power"])
        self.min_power = float(cfg["min_power"])
        self.max_power = float(cfg["max_power"])

        self.head = self.design_head
        self.target_power = self.design_power
        self.current_power = self.design_power
        self.power_ramp_rate = float(cfg.get("power_ramp_rate", max(10.0, self.design_power * 0.10)))

        self.flow = 0.0
        self.efficiency = 0.0
        self.time = 0

        self.nhq = HydroNHQGenerator(
            design_head=self.design_head,
            min_head=self.min_head,
            max_head=self.max_head,
            design_power=self.design_power,
            min_power=self.min_power,
            max_power=self.max_power,
            design_efficiency=float(cfg.get("design_efficiency", 0.93)),
            eta_head_coeff=float(cfg.get("eta_head_coeff", 0.20)),
            eta_power_coeff=float(cfg.get("eta_power_coeff", 0.40)),
        )

        self.history = {
            "time": [],
            "head": [],
            "current_power": [],
            "target_power": [],
            "flow": [],
            "efficiency": [],
            "state": [],
            "error": [],
        }

    def set_head(self, head: float) -> None:
        self.head = _clip(head, self.min_head, self.max_head)

    def _query_flow_for_current_power(self) -> Tuple[float, float]:
        if self.current_power <= 1e-6:
            return 0.0, 0.0
        if self.current_power < self.min_power:
            q_min, eta_min = self.nhq.query(self.head, self.min_power)
            return q_min * self.current_power / self.min_power, eta_min
        return self.nhq.query(self.head, self.current_power)

    def _record(self) -> None:
        self.history["time"].append(self.time)
        self.history["head"].append(self.head)
        self.history["current_power"].append(self.current_power)
        self.history["target_power"].append(self.target_power)
        self.history["flow"].append(self.flow)
        self.history["efficiency"].append(self.efficiency)
        self.history["state"].append(self.state)
        self.history["error"].append(self.target_power - self.current_power)
        self.time += 1

    def step(self) -> None:
        target = _clip(self.target_power, 0.0, self.max_power)
        self.current_power = _clip(target, 0.0, self.max_power)
        if target <= 0.0 and self.current_power <= 1e-6:
            self.current_power = 0.0
            self.target_power = 0.0
            self.state = 0
            self.flow = 0.0
            self.efficiency = 0.0
        else:
            self.flow, self.efficiency = self._query_flow_for_current_power()
        self._record()

    def history_reset(self) -> None:
        for v in self.history.values():
            v.clear()
        self.time = 0

    def history_plot(self) -> None:
        t = np.array(self.history["time"])
        cp = np.array(self.history["current_power"])
        tp = np.array(self.history["target_power"])
        fl = np.array(self.history["flow"])
        et = np.array(self.history["efficiency"])
        hd = np.array(self.history["head"])

        fig, axes = plt.subplots(2, 2, figsize=(14, 8))
        axes[0, 0].plot(t, hd, "b-", lw=1.5, label="Head")
        axes[0, 0].set(xlabel="min", ylabel="m", title="Head")
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].legend()

        axes[0, 1].plot(t, cp, "r--", lw=1.5, label="Current")
        axes[0, 1].plot(t, tp, "b:", lw=1.5, label="Target")
        axes[0, 1].set(xlabel="min", ylabel="MW", title="Power")
        axes[0, 1].grid(True, alpha=0.3)
        axes[0, 1].legend()

        axes[1, 0].plot(t, fl, "g-", lw=1.5, label="Flow")
        axes[1, 0].set(xlabel="min", ylabel="m^3/s", title="Flow")
        axes[1, 0].grid(True, alpha=0.3)
        axes[1, 0].legend()

        axes[1, 1].plot(t, et * 100.0, "m-", lw=1.5, label="eta")
        axes[1, 1].set(xlabel="min", ylabel="%", title="Efficiency")
        axes[1, 1].grid(True, alpha=0.3)
        axes[1, 1].legend()

        plt.suptitle(f"机组历史数据\n{self.unit_name}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"机组历史_{self.unit_name}")


class HydroStation:
    """
    单站电调：
    1) 机组启停（迟滞阈值）
    2) 站内等微增率离散分配
    """

    def __init__(
        self,
        station_id: int,
        name: str,
        design_head: float,
        design_power: float,
        min_power: float,
        max_power: float,
        unit_cfgs: Sequence[Dict],
        unit_dispatch_min_p: float | None = None,
        station_target_ramp_rate: float = 120.0,
    ):
        if not unit_cfgs:
            raise ValueError(f"{name}: unit_cfgs 不能为空。")

        self.id = int(station_id)
        self.name = str(name)
        self.head = float(design_head)
        self.design_power = float(design_power)
        self.min_power = float(min_power)
        self.max_power = float(max_power)

        self.multi_station = [HydroUnit(cfg["ID"], cfg) for cfg in unit_cfgs]
        self.num_units = len(self.multi_station)
        self.num_current = int(_clip(round(self.design_power / self.multi_station[0].design_power), 1, self.num_units))

        self.target_p = self.design_power
        self.current_p = self.design_power
        self.flow = 0.0
        self.efficiency = 0.0
        self.simulate_flow = 0.0
        self.simulate_power = self.design_power
        self.time = 0
        self.station_target_ramp_rate = float(station_target_ramp_rate)
        self.unit_dispatch_min_p = float(
            unit_dispatch_min_p
            if unit_dispatch_min_p is not None
            else max(1.0, round(self.multi_station[0].design_power * 0.05))
        )

        self.k_open = np.zeros(self.num_units + 1)
        self.k_close = np.zeros(self.num_units + 1)
        self.unit_array = np.zeros((self.num_units, 6))

        self.history = {
            "time": [],
            "head": [],
            "target_power": [],
            "current_power": [],
            "flow": [],
            "efficiency": [],
            "error": [],
            "num_online": [],
        }

        self.signal_inti_set(self.design_power)

    def signal_inti_set(self, signal_p: float) -> None:
        base = max(signal_p / self.num_units, 0.0)
        self.current_p = 0.0
        for u in self.multi_station:
            u.state = 1
            u.target_power = _clip(base, u.min_power, u.max_power)
            u.current_power = u.target_power
            q, eta = u.nhq.query(u.head, u.current_power)
            u.flow = q
            u.efficiency = eta
            self.current_p += u.current_power
        self.num_current = int(_clip(round(signal_p / self.multi_station[0].design_power), 1, self.num_units))

    def _target_commitment_count(self) -> int:
        if self.target_p <= 1e-6:
            return 0
        self._build_hysteresis()
        target_count = max(self.num_current, 1)
        if target_count < self.num_units and self.target_p > self.k_open[target_count]:
            target_count += 1
        if target_count > 1 and self.target_p < self.k_close[target_count - 1]:
            target_count -= 1
        return int(_clip(target_count, 1, self.num_units))

    def set_head(self, head: float) -> None:
        self.head = float(head)
        for u in self.multi_station:
            u.set_head(head)

    def _build_hysteresis(self) -> None:
        n = self.num_units
        self.k_open[:] = 0.0
        self.k_close[:] = 0.0

        pmin_cum = self.multi_station[0].min_power
        pmax_cum = self.multi_station[0].max_power
        self.k_open[0] = pmin_cum
        self.k_close[0] = pmin_cum
        for i in range(1, n):
            pmin_cum += self.multi_station[i].min_power
            avg = (pmin_cum + pmax_cum) / 2.0
            gap = min(30.0, abs(pmax_cum - pmin_cum) / 2.0)
            self.k_open[i] = avg + gap
            self.k_close[i] = avg - gap
            pmax_cum += self.multi_station[i].max_power

        self.k_open[-1] = pmax_cum
        self.k_close[-1] = pmax_cum

    def _update_commitment(self) -> None:
        desired = self._target_commitment_count()
        if desired > self.num_current:
            self.num_current += 1
        elif desired < self.num_current:
            self.num_current -= 1
        self.num_current = int(_clip(self.num_current, 1, self.num_units))

        for i, u in enumerate(self.multi_station):
            if i < self.num_current:
                u.state = 1
            else:
                u.target_power = 0.0

    def _dispatch_units_equal_increment(self) -> None:
        target_total = _clip(self.target_p, 0.0, self.max_power)
        if target_total <= 1e-6:
            self.num_current = 0
            self.unit_array[:] = 0.0
            self.current_p = 0.0
            for u in self.multi_station:
                u.state = 0
                u.target_power = 0.0
            return

        max_powers = np.array([u.max_power for u in self.multi_station], dtype=float)
        cum_max = np.cumsum(max_powers)
        n = int(np.searchsorted(cum_max, target_total, side="left") + 1)
        n = int(_clip(n, 1, self.num_units))
        self.num_current = n

        ua = np.zeros((n, 6), dtype=float)
        remaining = target_total
        for i in range(n):
            u = self.multi_station[i]
            p = min(u.max_power, remaining)
            ua[i, 0] = p
            ua[i, 2] = 0.0
            ua[i, 3] = u.max_power
            ua[i, 4] = 1.0 if p >= u.max_power - 1e-6 else 0.0
            ua[i, 5] = float(i)
            ua[i, 1] = u.nhq.incremental_rate(u.head, ua[i, 0])
            remaining -= p

        self.unit_array[:] = 0.0
        self.unit_array[:n, :] = ua
        self.current_p = float(ua[:, 0].sum())

        for u in self.multi_station:
            u.state = 0
            u.target_power = 0.0
        for i in range(n):
            uid = int(ua[i, 5])
            self.multi_station[uid].state = 1
            self.multi_station[uid].target_power = ua[i, 0]

    def estimate_flow_for_power(self, total_power: float) -> float:
        if total_power <= 1e-6:
            return 0.0
        u0 = self.multi_station[0]
        n = int(_clip(round(total_power / max(u0.design_power, 1e-6)), 1, self.num_units))
        p_per = total_power / n
        p_per = _clip(p_per, u0.min_power, u0.max_power)
        q_per, _ = u0.nhq.query(self.head, p_per)
        return q_per * n

    def step_simulate(self, signal_p: float) -> float:
        saved_target_p = self.target_p
        saved_current_p = self.current_p
        saved_num_current = self.num_current
        saved_unit_array = self.unit_array.copy()
        saved_units = [(u.state, u.target_power) for u in self.multi_station]

        self.target_p = float(signal_p)
        self._dispatch_units_equal_increment()
        n = self.num_current
        q_sum = 0.0
        for i in range(n):
            uid = int(self.unit_array[i, 5])
            p = self.unit_array[i, 0]
            q, _ = self.multi_station[uid].nhq.query(self.multi_station[uid].head, p)
            q_sum += q
        self.simulate_power = float(self.unit_array[:n, 0].sum())
        self.simulate_flow = float(q_sum)

        self.target_p = saved_target_p
        self.current_p = saved_current_p
        self.num_current = saved_num_current
        self.unit_array[:, :] = saved_unit_array
        for u, (state, target_power) in zip(self.multi_station, saved_units):
            u.state = state
            u.target_power = target_power
        return self.simulate_flow

    def step_execute(self, signal_p: float) -> float:
        self.time += 1
        self.target_p = float(signal_p)
        self._dispatch_units_equal_increment()

        for u in self.multi_station:
            u.step()

        self.flow = 0.0
        eta_sum = 0.0
        for u in self.multi_station:
            self.flow += u.flow
            eta_sum += u.efficiency if u.state == 1 else 0.0

        online = sum(u.state for u in self.multi_station)
        self.efficiency = eta_sum / max(online, 1)
        self.current_p = float(sum(u.current_power for u in self.multi_station))

        self.history["time"].append(self.time)
        self.history["head"].append(self.head)
        self.history["target_power"].append(self.target_p)
        self.history["current_power"].append(self.current_p)
        self.history["flow"].append(self.flow)
        self.history["efficiency"].append(self.efficiency)
        self.history["error"].append(self.target_p - self.current_p)
        self.history["num_online"].append(int(online))
        return self.flow

    def history_reset(self) -> None:
        for v in self.history.values():
            v.clear()
        self.time = 0
        for u in self.multi_station:
            u.history_reset()

    def history_plot(self, tag: str = "") -> None:
        t = np.array(self.history["time"])
        if t.size == 0:
            return

        plt.figure(figsize=(16, 8))
        ax1 = plt.subplot(2, 3, 1)
        ax1.plot(t, self.history["target_power"], "b--", lw=1.2, label="Target")
        ax1.plot(t, self.history["current_power"], "r-", lw=1.2, label="Current")
        ax1.set(xlabel="min", ylabel="MW", title="Station Power")
        ax1.grid(True, alpha=0.3)
        ax1.legend()

        ax2 = plt.subplot(2, 3, 2)
        ax2.plot(t, self.history["flow"], "g-", lw=1.2, label="Flow")
        ax2.set(xlabel="min", ylabel="m^3/s", title="Station Flow")
        ax2.grid(True, alpha=0.3)
        ax2.legend()

        ax3 = plt.subplot(2, 3, 3)
        ax3.plot(t, np.array(self.history["efficiency"]) * 100.0, "m-", lw=1.2, label="eta")
        ax3.set(xlabel="min", ylabel="%", title="Efficiency")
        ax3.grid(True, alpha=0.3)
        ax3.legend()

        ax4 = plt.subplot(2, 3, 4)
        ax4.plot(t, self.history["num_online"], "k-", lw=1.2, label="#online")
        ax4.set(xlabel="min", ylabel="count", title="Committed Units")
        ax4.grid(True, alpha=0.3)
        ax4.legend()

        ax5 = plt.subplot(2, 3, 5)
        err = np.array(self.history["target_power"]) - np.array(self.history["current_power"])
        ax5.plot(t, err, "c-", lw=1.2, label="Power Error")
        margin = max(float(np.max(np.abs(err))) * 1.2, 1.0)
        ax5.set_ylim(-margin, margin)
        ax5.set(xlabel="min", ylabel="MW", title="Power Error")
        ax5.grid(True, alpha=0.3)
        ax5.legend()

        ax6 = plt.subplot(2, 3, 6)
        for u in self.multi_station:
            up = np.array(u.history["current_power"])
            if up.size == t.size:
                ax6.plot(t, up, lw=1.0, label=u.unit_name)
        ax6.set(xlabel="min", ylabel="MW", title="Unit Power Curves")
        ax6.grid(True, alpha=0.3)
        ax6.legend(fontsize=7, ncol=2)

        plt.suptitle(f"电站历史数据\n{self.name}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"{tag}电站历史_{self.name}")


class HydroStair:
    """
    梯级电调（站间）：
    1) 总功率目标按站间流量平衡思想分配。
    2) 各站再执行站内等微增率分配。
    3) V7：站间/站内最小分配单位 P 显式配置，并输出调度关键参数。
    """

    def __init__(
        self,
        stair_id: int,
        name: str,
        current_power: float,
        station_cfgs: Sequence[Dict],
        unit_cfgs_by_station: Sequence[Sequence[Dict]],
    ):
        if len(station_cfgs) != len(unit_cfgs_by_station):
            raise ValueError("station_cfgs 与 unit_cfgs_by_station 长度不一致。")

        self.id = int(stair_id)
        self.name = str(name)
        self.current_power = float(current_power)
        self.time = 0
        self.num_stairs = len(station_cfgs)

        self.multi_stair: List[HydroStation] = []
        self.stair_dispatch_min_p = np.zeros(self.num_stairs, dtype=float)
        for i, sc in enumerate(station_cfgs):
            sta = HydroStation(
                station_id=sc["ID"],
                name=sc["Name"],
                design_head=float(sc["design_head"]),
                design_power=float(sc["design_power"]),
                min_power=float(sc["min_power"]),
                max_power=float(sc["max_power"]),
                unit_cfgs=unit_cfgs_by_station[i],
                unit_dispatch_min_p=float(sc.get("unit_min_step_p", max(1.0, round(float(sc["design_power"]) * 0.05)))),
                station_target_ramp_rate=float(sc.get("station_target_ramp_rate", 120.0)),
            )
            self.multi_stair.append(sta)
            self.stair_dispatch_min_p[i] = float(
                sc.get("stair_min_step_p", max(1.0, round(float(sc["design_head"]) / 10.0)))
            )

        self.stair_array = np.zeros((self.num_stairs, 8), dtype=float)
        for i, s in enumerate(self.multi_stair):
            self.stair_array[i, 0] = s.id
            self.stair_array[i, 1] = s.current_p
            self.stair_array[i, 2] = s.target_p
            self.stair_array[i, 3] = s.flow
            self.stair_array[i, 5] = s.min_power
            self.stair_array[i, 6] = s.design_power
            self.stair_array[i, 7] = s.max_power

        self.total_p_target = float(sum(s.design_power for s in self.multi_stair))
        self.total_p_current = self.total_p_target
        self.flow = 0.0
        self.stage_hints: List[Dict] = [{} for _ in range(self.num_stairs)]
        self.increment_guard_enable = True
        self.increment_guard_upstream_idx = 0
        self.increment_guard_protected_idxs = {1, 2, 3}
        self.low_stage_power_guard_enable = True
        self.low_stage_guard_station_idxs = tuple(sorted(self.increment_guard_protected_idxs))
        self.low_stage_guard_station_idx = 3
        self.low_stage_guard_yellow_limit_ratio = 0.55
        self.low_stage_guard_red_limit_ratio = 0.30
        self.low_stage_guard_abs_floor_mw = 120.0
        self.low_stage_guard_last = {
            "active": False,
            "station": "",
            "zone": "green",
            "original_max_mw": 0.0,
            "guarded_max_mw": 0.0,
            "target_mw": 0.0,
            "unserved_mw": 0.0,
        }

        self.history = {
            "time": [],
            "flow": [],
            "power_target": [],
            "power_current": [],
            "flows": [[] for _ in range(self.num_stairs)],
            "powers": [[] for _ in range(self.num_stairs)],
            "heads": [[] for _ in range(self.num_stairs)],
            "low_stage_guard": [],
        }

    def update_heads(self, heads: Sequence[float]) -> None:
        if len(heads) != self.num_stairs:
            raise ValueError("heads 长度与电站数不一致。")
        for i, h in enumerate(heads):
            self.multi_stair[i].set_head(float(h))

    def update_stage_hints(self, hints: Sequence[Dict]) -> None:
        if len(hints) != self.num_stairs:
            raise ValueError("stage hints 长度与电站数不一致。")
        self.stage_hints = [dict(h) for h in hints]

    def dispatch_min_p_report(self) -> List[Dict]:
        report: List[Dict] = []
        for i, sta in enumerate(self.multi_stair):
            report.append(
                {
                    "station": sta.name,
                    "inter_station_min_p_mw": float(self.stair_dispatch_min_p[i]),
                    "intra_station_min_p_mw": float(sta.unit_dispatch_min_p),
                }
            )
        return report

    def _guarded_station_max(self, i: int) -> float:
        base_max = float(self.stair_array[i, 7])
        if not self.low_stage_power_guard_enable or i not in self.low_stage_guard_station_idxs:
            return base_max
        if i >= len(self.stage_hints):
            return base_max

        hint = self.stage_hints[i]
        direction = float(hint.get("direction", 0.0))
        if direction >= 0.0:
            return base_max

        zone = hint.get("zone", "green")
        if zone == "red":
            ratio = self.low_stage_guard_red_limit_ratio
        elif zone == "yellow":
            severity = self._low_stage_yellow_severity(i, hint)
            ratio = 1.0 - severity * (1.0 - self.low_stage_guard_yellow_limit_ratio)
        else:
            return base_max

        guarded = max(float(self.stair_array[i, 5]), self.low_stage_guard_abs_floor_mw, base_max * ratio)
        return min(base_max, guarded)

    def _low_stage_yellow_severity(self, i: int, hint: Dict) -> float:
        delta = abs(float(hint.get("delta", 0.0)))
        if i < len(self.stage_hints):
            green_band = 1.0 if i == 0 else 0.5
            yellow_band = 3.0 if i == 0 else 1.0
        else:
            green_band = 0.5
            yellow_band = 1.0
        return _clip((delta - green_band) / max(yellow_band - green_band, 1e-6), 0.0, 1.0)

    def _guarded_station_maxes(self) -> np.ndarray:
        return np.array([self._guarded_station_max(i) for i in range(self.num_stairs)], dtype=float)

    def _increment_blocked(self, i: int) -> bool:
        if not self.increment_guard_enable or i not in self.increment_guard_protected_idxs:
            return False
        if i >= len(self.stage_hints):
            return False
        return float(self.stage_hints[i].get("delta", 0.0)) < -1e-9

    def _update_low_stage_guard_status(self, max_allowed: np.ndarray, unserved_mw: float = 0.0) -> None:
        guarded_items = []
        for idx in self.low_stage_guard_station_idxs:
            if idx >= self.num_stairs:
                continue
            hint = self.stage_hints[idx] if idx < len(self.stage_hints) else {}
            guarded_max = float(max_allowed[idx]) if idx < len(max_allowed) else float(self.stair_array[idx, 7])
            original_max = float(self.stair_array[idx, 7])
            if guarded_max < original_max - 1e-6:
                guarded_items.append({
                    "station": str(hint.get("station", self.multi_stair[idx].name)),
                    "zone": str(hint.get("zone", "green")),
                    "original_max_mw": original_max,
                    "guarded_max_mw": guarded_max,
                })

        primary = guarded_items[0] if guarded_items else {
            "station": self.multi_stair[self.low_stage_guard_station_idx].name,
            "zone": "green",
            "original_max_mw": float(self.stair_array[self.low_stage_guard_station_idx, 7]),
            "guarded_max_mw": float(self.stair_array[self.low_stage_guard_station_idx, 7]),
        }
        self.low_stage_guard_last = {
            "active": bool(guarded_items),
            "station": primary["station"],
            "zone": primary["zone"],
            "original_max_mw": float(primary["original_max_mw"]),
            "guarded_max_mw": float(primary["guarded_max_mw"]),
            "target_mw": float(self.total_p_target),
            "unserved_mw": float(max(0.0, unserved_mw)),
            "guarded_stations": guarded_items,
        }

    def _allocate_increment_min_change(
        self,
        remaining: float,
        flow_est: np.ndarray,
        max_allowed: np.ndarray,
        prev: np.ndarray,
    ) -> float:
        sa = self.stair_array
        n = self.num_stairs
        upstream = self.increment_guard_upstream_idx
        protected_blocked = any(self._increment_blocked(i) for i in self.increment_guard_protected_idxs)

        while remaining > 1e-6:
            avail_all = [i for i in range(n) if sa[i, 2] < max_allowed[i] - 1e-6]
            if not avail_all:
                break

            if protected_blocked and upstream in avail_all:
                avail = [upstream]
            else:
                avail = avail_all

            idx = min(avail, key=lambda k: (max(0.0, sa[k, 2] - prev[k]), flow_est[k], k))
            amount = min(max(1.0, float(self.stair_dispatch_min_p[idx])), remaining, max_allowed[idx] - sa[idx, 2])
            sa[idx, 2] += amount
            remaining -= amount
            flow_est[idx] = self.multi_stair[idx].estimate_flow_for_power(sa[idx, 2])
        return remaining

    def _reduce_power_min_change(self, reduction: float, flow_est: np.ndarray, prev: np.ndarray) -> float:
        sa = self.stair_array
        n = self.num_stairs
        while reduction > 1e-6:
            avail = [i for i in range(n) if sa[i, 2] > 1e-6]
            if not avail:
                break
            idx = min(avail, key=lambda k: (max(0.0, prev[k] - sa[k, 2]), -flow_est[k], k))
            amount = min(reduction, sa[idx, 2])
            sa[idx, 2] -= amount
            reduction -= amount
            flow_est[idx] = self.multi_stair[idx].estimate_flow_for_power(sa[idx, 2])
        return reduction

    def _station_dispatch(self) -> None:
        sa = self.stair_array
        n = self.num_stairs

        max_allowed = self._guarded_station_maxes()
        max_sum = float(max_allowed.sum())
        self.total_p_target = _clip(self.total_p_target, 0.0, max_sum)
        self._update_low_stage_guard_status(max_allowed)

        prev = np.array([self.multi_stair[i].current_p for i in range(n)], dtype=float)
        current_sum = float(prev.sum())
        if current_sum <= 1e-6:
            base = np.zeros(n, dtype=float)
        else:
            base = prev * min(1.0, self.total_p_target / current_sum)
        for i in range(n):
            sa[i, 2] = _clip(base[i], 0.0, max_allowed[i])

        diff = float(self.total_p_target - sa[:, 2].sum())
        flow_est = np.zeros(n, dtype=float)
        for i in range(n):
            flow_est[i] = self.multi_stair[i].estimate_flow_for_power(sa[i, 2])

        if diff > 1e-6:
            diff = self._allocate_increment_min_change(diff, flow_est, max_allowed, prev)
        elif diff < -1e-6:
            diff = -self._reduce_power_min_change(-diff, flow_est, prev)
        self._update_low_stage_guard_status(max_allowed, unserved_mw=abs(diff))

        for i in range(n):
            sa[i, 1] = sa[i, 2]
            sa[i, 3] = self.multi_stair[i].step_simulate(sa[i, 2])

        self.total_p_current = float(sa[:, 1].sum())
        self.flow = float(sa[:, 3].sum())

    def step_execute(self, signal_p: float) -> float:
        self.time += 1
        self.total_p_target = float(signal_p)
        self._station_dispatch()

        total_flow = 0.0
        for i, s in enumerate(self.multi_stair):
            s.step_execute(self.stair_array[i, 1])
            self.stair_array[i, 1] = s.current_p
            self.stair_array[i, 2] = s.target_p
            self.stair_array[i, 3] = s.flow
            total_flow += s.flow

            self.history["flows"][i].append(s.flow)
            self.history["powers"][i].append(s.current_p)
            self.history["heads"][i].append(s.head)

        self.total_p_current = float(self.stair_array[:, 1].sum())
        self.flow = float(total_flow)
        self.history["time"].append(self.time)
        self.history["flow"].append(self.flow)
        self.history["power_target"].append(self.total_p_target)
        self.history["power_current"].append(self.total_p_current)
        self.history["low_stage_guard"].append(dict(self.low_stage_guard_last))
        return self.flow

    def history_reset(self) -> None:
        for k in ("time", "flow", "power_target", "power_current"):
            self.history[k].clear()
        self.history["low_stage_guard"].clear()
        for lists_key in ("flows", "powers", "heads"):
            for v in self.history[lists_key]:
                v.clear()
        self.time = 0
        for s in self.multi_stair:
            s.history_reset()

    def history_plot(self, tag: str = "") -> None:
        t = np.array(self.history["time"])
        if t.size == 0:
            return
        pt = np.array(self.history["power_target"])
        pc = np.array(self.history["power_current"])
        err = pt - pc

        fig = plt.figure(figsize=(14, 8))
        ax1 = plt.subplot(2, 3, 1)
        ax1.plot(t, pt, "b--", lw=1.2, label="Target")
        ax1.plot(t, pc, "r-", lw=1.2, label="Current")
        ax1.set(xlabel="min", ylabel="MW", title="Cascade Power")
        ax1.grid(True, alpha=0.3)
        ax1.legend(fontsize=8)

        ax2 = plt.subplot(2, 3, 4)
        ax2.plot(t, err, "k-", lw=1.2, label="Error")
        margin = max(float(np.max(np.abs(err))) * 1.2, 1.0)
        ax2.set_ylim(-margin, margin)
        ax2.set(xlabel="min", ylabel="MW", title="Power Error")
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=8)

        ax3 = plt.subplot(2, 3, 2)
        y = np.zeros_like(t, dtype=float)
        for i in range(self.num_stairs):
            y += np.array(self.history["powers"][i])
            ax3.plot(t, y, lw=1.2, label=self.multi_stair[i].name)
        ax3.set(xlabel="min", ylabel="MW", title="Cumulative Station Power")
        ax3.grid(True, alpha=0.3)
        ax3.legend(fontsize=8)

        ax4 = plt.subplot(2, 3, 5)
        for i in range(self.num_stairs):
            ax4.plot(t, np.array(self.history["powers"][i]), lw=1.2, label=self.multi_stair[i].name)
        ax4.set(xlabel="min", ylabel="MW", title="Station Power")
        ax4.grid(True, alpha=0.3)
        ax4.legend(fontsize=8)

        ax5 = plt.subplot(2, 3, 3)
        for i in range(self.num_stairs):
            ax5.plot(t, np.array(self.history["flows"][i]), lw=1.2, label=self.multi_stair[i].name)
        ax5.set(xlabel="min", ylabel="m^3/s", title="Station Turbine Flow")
        ax5.grid(True, alpha=0.3)
        ax5.legend(fontsize=8)

        ax6 = plt.subplot(2, 3, 6)
        for i in range(self.num_stairs):
            ax6.plot(t, np.array(self.history["heads"][i]), lw=1.2, label=self.multi_stair[i].name)
        ax6.set(xlabel="min", ylabel="m", title="Dynamic Head")
        ax6.grid(True, alpha=0.3)
        ax6.legend(fontsize=8)

        plt.suptitle(f"梯级电站站间调度\n{self.name}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"{tag}梯级电站调度_{self.name}")

        for sta in self.multi_stair:
            sta.history_plot(tag=tag)

# =============================================================================
# 水调层：PID + 水库 + 梯级水库群
# =============================================================================

class PIDController:
    """滚动均值误差 PID（支持积分开关与积分防饱和）。"""

    def __init__(self, Kp: float = 1.0, Ki: float = 0.1, Kd: float = 0.01, use_integral: bool = True):
        self.Kp = float(Kp)
        self.Ki = float(Ki)
        self.Kd = float(Kd)
        self.use_integral = bool(use_integral)
        self._cache = np.zeros(10, dtype=float)
        self._integral = 0.0
        self._output = 0.0

    def initialize(self, value: float) -> None:
        self._cache[:] = float(value)
        self._integral = 0.0
        self._output = 0.0

    def update(self, current: float, target: float) -> float:
        self._cache[:-1] = self._cache[1:]
        self._cache[-1] = float(current)

        smooth_error = float(np.mean(self._cache) - target)
        if self.use_integral:
            self._integral += smooth_error
            integral_limit = len(self._cache) * 20000.0 / max(self.Ki, 1e-9)
            self._integral = _clip(self._integral, -integral_limit, integral_limit)
        else:
            self._integral = 0.0

        p = self.Kp * (current - target)
        i = self.Ki * self._integral / len(self._cache)
        d = self.Kd * ((self._cache[-1] - target) - (self._cache[-2] - target))
        self._output = p + i + d
        return self._output


class HydroReservoir:
    """单水库：库容-水位插值 + PID 泄洪 + 出入流平衡。"""

    def __init__(self, reservoir_id: int, name: str, cfg: Dict):
        self.id = int(reservoir_id)
        self.name = str(name)
        self.time = 0
        self.time_steps = int(cfg.get("time_steps", 60))

        self.min_stage = float(cfg["min_stage"])
        self.design_stage = float(cfg["design_stage"])
        self.max_stage = float(cfg["max_stage"])

        self.min_capacity = float(cfg["min_capacity"])
        self.design_capacity = float(cfg["design_capacity"])
        self.max_capacity = float(cfg["max_capacity"])

        self.stages = np.array([self.min_stage, self.design_stage, self.max_stage], dtype=float)
        self.capacities = np.array([self.min_capacity, self.design_capacity, self.max_capacity], dtype=float)

        self.target_stage = self.design_stage
        self.target_capacity = self.design_capacity
        self.current_stage = self.design_stage
        self.current_capacity = self.design_capacity

        self.current_inflow = 0.0
        self.current_outflow = 0.0
        self.current_outflow_power = 0.0
        self.current_outflow_discharge = 0.0
        self.current_outflow_discharge_ff = 0.0

        self.capacity_overflow = 0.0
        self.capacity_underflow = 0.0

        # 来水-发电需水前馈：当入流持续大于发电出流时，提前开启泄洪闸。
        self.spill_ff_enable = bool(cfg.get("spill_ff_enable", True))
        self.spill_ff_gain = float(cfg.get("spill_ff_gain", 1.00))
        self.spill_ff_deadband = float(cfg.get("spill_ff_deadband", 20.0))
        self.spill_ff_gain_yellow_high = float(cfg.get("spill_ff_gain_yellow_high", max(self.spill_ff_gain, 1.05)))
        self.spill_ff_gain_red_high = float(cfg.get("spill_ff_gain_red_high", max(self.spill_ff_gain, 1.15)))
        self.spill_ff_high_deadband = float(cfg.get("spill_ff_high_deadband", 0.0))
        self.spill_ff_high_green_band = float(cfg.get("spill_ff_high_green_band", 0.5))
        self.spill_ff_high_yellow_band = float(cfg.get("spill_ff_high_yellow_band", 1.0))
        self.max_spill_q = float(cfg.get("max_spill_q", 20000.0))
        # 前馈泄洪水位保护：水位明显低于目标时禁用前馈泄洪，避免“边缺水边放水”。
        self.spill_ff_stage_guard_enable = bool(cfg.get("spill_ff_stage_guard_enable", True))
        self.spill_ff_stage_guard_band = float(cfg.get("spill_ff_stage_guard_band", 0.05))
        self.spill_ramp_rate = float(cfg.get("spill_ramp_rate", 250.0))

        self.PID = PIDController(
            Kp=float(cfg.get("Kp", 100.0)),
            Ki=float(cfg.get("Ki", 5.0)),
            Kd=float(cfg.get("Kd", 0.5)),
            use_integral=bool(cfg.get("use_integral", True)),
        )
        self.PID.initialize(self.current_stage)

        self.history = {
            "time": [],
            "current_stage": [],
            "current_capacity": [],
            "current_inflow": [],
            "current_outflow": [],
            "current_outflow_power": [],
            "current_outflow_discharge": [],
            "current_outflow_discharge_ff": [],
            "capacity_overflow": [],
            "capacity_underflow": [],
        }

    def stage_to_capacity(self, stage: float) -> float:
        return float(np.interp(stage, self.stages, self.capacities))

    def capacity_to_stage(self, capacity: float) -> float:
        return float(np.interp(capacity, self.capacities, self.stages))

    def _dynamic_spill_ff_params(self) -> Tuple[float, float, bool]:
        delta = self.current_stage - self.target_stage
        if self.spill_ff_stage_guard_enable and delta < -self.spill_ff_stage_guard_band:
            return 0.0, self.spill_ff_deadband, False
        if delta >= self.spill_ff_high_yellow_band:
            return self.spill_ff_gain_red_high, self.spill_ff_high_deadband, True
        if delta >= self.spill_ff_high_green_band:
            return self.spill_ff_gain_yellow_high, self.spill_ff_high_deadband, True
        return self.spill_ff_gain, self.spill_ff_deadband, False

    def _calc_spill_feedforward(self, inflow: float, outflow_power: float) -> float:
        if not self.spill_ff_enable:
            return 0.0
        gain, deadband, force_pass = self._dynamic_spill_ff_params()
        if gain <= 0.0:
            return 0.0
        surplus = float(inflow) - float(outflow_power) - deadband
        if surplus <= 0.0:
            return 0.0
        spill = gain * surplus
        if force_pass:
            spill = max(spill, surplus)
        return spill

    def step(self, inflow: float, outflow_power: float, record: bool = True) -> None:
        pid_output = self.PID.update(self.current_stage, self.target_stage)
        self.current_inflow = float(inflow)
        self.current_outflow_power = float(outflow_power)
        self.current_outflow_discharge_ff = self._calc_spill_feedforward(self.current_inflow, self.current_outflow_power)
        # V7: 泄洪由“PID指令 + 来水前馈指令”共同决定。
        target_spill = _clip(pid_output + self.current_outflow_discharge_ff, 0.0, self.max_spill_q)
        spill_delta = _clip(
            target_spill - self.current_outflow_discharge,
            -self.spill_ramp_rate,
            self.spill_ramp_rate,
        )
        outflow_discharge = _clip(self.current_outflow_discharge + spill_delta, 0.0, self.max_spill_q)
        self.current_outflow_discharge = outflow_discharge
        self.current_outflow = self.current_outflow_power + self.current_outflow_discharge

        net_out = self.current_outflow - self.current_inflow
        next_capacity = self.current_capacity - net_out * self.time_steps / 10000.0

        self.capacity_overflow = max(0.0, next_capacity - self.max_capacity)
        self.capacity_underflow = max(0.0, self.min_capacity - next_capacity)
        self.current_capacity = _clip(next_capacity, self.min_capacity, self.max_capacity)
        self.current_stage = self.capacity_to_stage(self.current_capacity)

        if record:
            self._record()

    def _record(self) -> None:
        h = self.history
        h["time"].append(self.time)
        h["current_stage"].append(self.current_stage)
        h["current_capacity"].append(self.current_capacity)
        h["current_inflow"].append(self.current_inflow)
        h["current_outflow"].append(self.current_outflow)
        h["current_outflow_power"].append(self.current_outflow_power)
        h["current_outflow_discharge"].append(self.current_outflow_discharge)
        h["current_outflow_discharge_ff"].append(self.current_outflow_discharge_ff)
        h["capacity_overflow"].append(self.capacity_overflow)
        h["capacity_underflow"].append(self.capacity_underflow)
        self.time += 1

    def history_reset(self) -> None:
        for v in self.history.values():
            v.clear()
        self.time = 0

    def history_plot(self, tag: str = "", history_interval: int = 120) -> None:
        t = np.array(self.history["time"])
        if t.size == 0:
            return
        h = self.history

        fig, axes = plt.subplots(2, 3, figsize=(16, 8))
        axes[0, 0].plot(t, h["current_stage"], "b-", lw=1.2, label="Stage")
        axes[0, 0].set(xlabel="min", ylabel="m", title="Stage")
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].legend()

        axes[0, 1].plot(t, h["current_capacity"], "b-", lw=1.2, label="Capacity")
        axes[0, 1].set(xlabel="min", ylabel="10^4m^3", title="Capacity")
        axes[0, 1].grid(True, alpha=0.3)
        axes[0, 1].legend()

        axes[0, 2].plot(t, h["current_inflow"], "b-", lw=1.2, label="Inflow")
        axes[0, 2].plot(t, h["current_outflow"], "r-", lw=1.2, label="Outflow")
        axes[0, 2].set(xlabel="min", ylabel="m^3/s", title="In/Out Flow")
        axes[0, 2].grid(True, alpha=0.3)
        axes[0, 2].legend()

        axes[1, 0].plot(t, h["current_outflow_power"], "r-", lw=1.2, label="Power Outflow")
        axes[1, 0].plot(t, h["current_outflow_discharge"], "g-", lw=1.2, label="Spill Outflow")
        axes[1, 0].plot(t, h["current_outflow_discharge_ff"], "m--", lw=1.0, label="Spill FF")
        axes[1, 0].set(xlabel="min", ylabel="m^3/s", title="Outflow Decomposition")
        axes[1, 0].grid(True, alpha=0.3)
        axes[1, 0].legend(fontsize=8)

        axes[1, 1].plot(t, h["capacity_overflow"], "r-", lw=1.2, label="Overflow")
        axes[1, 1].plot(t, h["capacity_underflow"], "k-", lw=1.2, label="Underflow")
        axes[1, 1].set(xlabel="min", ylabel="10^4m^3", title="Capacity Violation")
        axes[1, 1].grid(True, alpha=0.3)
        axes[1, 1].legend()

        caps = np.array(h["current_capacity"])
        stages = np.array(h["current_stage"])
        axes[1, 2].plot(caps, stages, "m-", lw=1.0, label="Trajectory")
        idx = np.arange(0, len(caps), max(1, int(history_interval)))
        if idx.size > 0:
            axes[1, 2].scatter(caps[idx], stages[idx], c="navy", s=24, zorder=5,
                               label=f"Samples (every {max(1, int(history_interval))} step)")
            axes[1, 2].scatter(caps[0], stages[0], c="limegreen", s=70, marker="^", zorder=6, label="Start")
            axes[1, 2].scatter(caps[-1], stages[-1], c="crimson", s=70, marker="v", zorder=6, label="End")
        axes[1, 2].set(xlabel="10^4m^3", ylabel="m", title="Capacity-Stage")
        axes[1, 2].grid(True, alpha=0.3)
        axes[1, 2].legend(fontsize=8)

        plt.suptitle(f"水库历史数据\n{self.name}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"{tag}水库历史_{self.name}")

    def odd_plot(self, history_interval: int = 120, tag: str = "") -> None:
        fig, ax = plt.subplots(figsize=(10, 8))
        self._draw_odd_on_axis(ax=ax, history_interval=history_interval)
        plt.suptitle(f"水库运行域图 (ODD)\n{self.name}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"{tag}水库ODD_{self.name}")

    def _draw_odd_on_axis(self, ax: plt.Axes, history_interval: int = 120) -> None:
        c_min, c_des, c_max = self.min_capacity, self.design_capacity, self.max_capacity
        h_min, h_des, h_max = self.min_stage, self.design_stage, self.max_stage

        c_margin = (c_max - c_min) * 0.08
        h_margin = (h_max - h_min) * 0.15
        x0, x1 = max(0.0, c_min - c_margin), c_max + c_margin
        y0, y1 = h_min - h_margin, h_max + h_margin

        c_curve = np.linspace(x0, x1, 400)
        h_curve = np.interp(c_curve, self.capacities, self.stages)

        ax.fill_between(c_curve, y0, h_min, color="red", alpha=0.2)
        ax.fill_between(c_curve, h_min, h_des, color="green", alpha=0.2)
        ax.fill_between(c_curve, h_des, h_max, color="yellow", alpha=0.3)
        ax.fill_between(c_curve, h_max, y1, color="red", alpha=0.2)
        # 区域图例占位，便于直观识别红黄绿区。
        ax.plot([], [], "s", color="green", alpha=0.4, ms=10, label=f"Green Zone [{h_min:.1f}, {h_des:.1f})")
        ax.plot([], [], "s", color="yellow", alpha=0.6, ms=10, label=f"Yellow Zone [{h_des:.1f}, {h_max:.1f})")
        ax.plot([], [], "s", color="red", alpha=0.4, ms=10, label="Red Zone (<min or >max)")
        ax.plot(c_curve, h_curve, "k-", lw=1.5, label="Capacity-Stage Curve")

        if self.history["current_capacity"]:
            caps = np.array(self.history["current_capacity"])
            stages = np.array(self.history["current_stage"])
            ax.plot(caps, stages, "b-", lw=0.8, alpha=0.4, label="Trajectory")
            idx = np.arange(0, len(caps), max(1, int(history_interval)))
            if idx.size > 0:
                ax.scatter(caps[idx], stages[idx], c="navy", s=24, zorder=5,
                           label=f"Samples (every {max(1, int(history_interval))} step)")
                ax.scatter(caps[0], stages[0], c="limegreen", s=70, marker="^", zorder=6, label="Start")
                ax.scatter(caps[-1], stages[-1], c="crimson", s=70, marker="v", zorder=6, label="End")

        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_xlabel("Capacity (10^4m^3)")
        ax.set_ylabel("Stage (m)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left", fontsize=8)


class HydroResStairs:
    """梯级水库群：接收入流、计算各水库状态并向电调反馈动态水头。"""

    def __init__(
        self,
        stairs_id: int,
        name: str,
        flow_configs: Sequence[Dict],
        flow_station_cfgs: Sequence[Dict],
        capa_loc: Sequence[int],
    ):
        if len(flow_configs) != len(flow_station_cfgs):
            raise ValueError("flow_configs 与 flow_station_cfgs 长度不一致。")
        if len(capa_loc) != len(flow_configs) + 1:
            raise ValueError("capa_loc 长度应为水库数 + 1。")

        self.id = int(stairs_id)
        self.name = str(name)
        self.configs = list(flow_configs)
        self._flow_station_cfgs = list(flow_station_cfgs)
        self.Capa_Loc = list(capa_loc)

        self.Capacity_Stairs: List[HydroReservoir] = []
        for cfg in self.configs:
            res = HydroReservoir(cfg["ID"], cfg["Name"], cfg)
            self.Capacity_Stairs.append(res)

        self._design_gross = []
        for fc, fsc in zip(self.configs, self._flow_station_cfgs):
            self._design_gross.append(float(fc["design_stage"] - fsc["tail_design_stage"]))
        self._tail_stage = float(self.configs[-1].get("tail_stage", 540.0))
        self.stage_zone_bands = [
            {"green": 1.0, "yellow": 3.0},
            {"green": 0.5, "yellow": 1.0},
            {"green": 0.5, "yellow": 1.0},
            {"green": 0.5, "yellow": 1.0},
        ]

    def _compute_heads(self, power_stair: HydroStair) -> None:
        stages = [r.current_stage for r in self.Capacity_Stairs]
        heads = []
        for i, cfg in enumerate(self._flow_station_cfgs):
            if i < len(stages) - 1:
                gross = stages[i] - stages[i + 1]
            else:
                gross = stages[i] - self._tail_stage
            design_gross = max(self._design_gross[i], 1e-6)
            head = cfg["design_head"] * (gross / design_gross)
            head = _clip(head, cfg["min_head"], cfg["max_head"])
            heads.append(head)
        power_stair.update_heads(heads)

    def stage_state(self, reservoir_idx: int, stage: float | None = None) -> Dict:
        res = self.Capacity_Stairs[reservoir_idx]
        band = self.stage_zone_bands[reservoir_idx]
        green = float(band["green"])
        yellow = float(band["yellow"])
        current_stage = float(res.current_stage if stage is None else stage)
        delta = current_stage - float(res.design_stage)
        abs_delta = abs(delta)
        if abs_delta <= green:
            zone = "green"
            denom = green
        elif abs_delta <= yellow:
            zone = "yellow"
            denom = yellow
        else:
            zone = "red"
            denom = yellow

        direction = 0.0 if abs_delta <= green else _clip(delta / max(denom, 1e-6), -2.0, 2.0)
        return {
            "station": res.name,
            "stage": current_stage,
            "design_stage": float(res.design_stage),
            "delta": delta,
            "zone": zone,
            "direction": direction,
        }

    def stage_hints(self) -> List[Dict]:
        return [self.stage_state(i) for i in range(len(self.Capacity_Stairs))]

    def step(self, river: "RiverArray", power: HydroStair, record: bool = True) -> None:
        for i in range(len(self.configs)):
            inflow = river.River_Steps[self.Capa_Loc[i]]
            outflow_power = power.multi_stair[i].flow
            self.Capacity_Stairs[i].step(inflow, outflow_power, record=record)
        self._compute_heads(power)

    def history_plot(self, tag: str = "") -> None:
        for res in self.Capacity_Stairs:
            res.history_plot(tag=tag)

    def odd_plot(self, history_interval: int = 120, tag: str = "") -> None:
        for res in self.Capacity_Stairs:
            res.odd_plot(history_interval=history_interval, tag=tag)
        # 额外输出：四个水库 ODD 合并 2x2 视图，便于并排对比。
        if not self.Capacity_Stairs:
            return
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        flat = axes.flatten()
        for i in range(4):
            if i < len(self.Capacity_Stairs):
                res = self.Capacity_Stairs[i]
                res._draw_odd_on_axis(ax=flat[i], history_interval=history_interval)
                flat[i].set_title(res.name, fontsize=12, fontweight="bold")
            else:
                flat[i].axis("off")
        plt.suptitle(f"水库运行域图 (ODD) 合并2x2\n{self.name}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"{tag}水库ODD_合并2x2_{self.name}")

    def history_reset(self) -> None:
        for res in self.Capacity_Stairs:
            res.history_reset()

# =============================================================================
# 河道层：简化时延传播
# =============================================================================

class RiverArray:
    """简化 IDZ 河道（固定传播）。"""

    def __init__(self, river_id: int, name: str, configs: Sequence[Dict], sim_steps: int, capa_loc: Sequence[int]):
        if len(capa_loc) != len(configs) + 1:
            raise ValueError("capa_loc 长度必须等于电站数 + 1。")
        n_cells = int(capa_loc[-1])
        if n_cells <= 2:
            raise ValueError("河道离散点数量过小。")

        self.id = int(river_id)
        self.name = str(name)
        self.configs = list(configs)
        self.casc_nums = len(configs)
        self.capa_loc = list(capa_loc)
        self.hot_step = n_cells

        self.River_Steps = np.ones(n_cells, dtype=float) * 1000.0

        self.history_total = np.zeros((n_cells, int(sim_steps)), dtype=float)
        self.cnt = 0

    def _move_forward(self, value: float) -> None:
        self.River_Steps[1:] = self.River_Steps[:-1]
        self.River_Steps[0] = float(value)

    def _inject_outflows(self, reservoirs: HydroResStairs) -> None:
        for i in range(self.casc_nums):
            idx = int(self.capa_loc[i] + 1)
            self.River_Steps[idx] = reservoirs.Capacity_Stairs[i].current_outflow

    def _record(self) -> None:
        if self.cnt < self.history_total.shape[1]:
            self.history_total[:, self.cnt] = self.River_Steps.copy()
        self.cnt += 1

    def step_execute(self, reservoirs: HydroResStairs, upstream_flow: float) -> None:
        self._move_forward(upstream_flow)
        self._inject_outflows(reservoirs)
        self._record()

    def history_reset(self) -> None:
        self.history_total[:] = 0.0
        self.cnt = 0

    def history_plot(self, tag: str = "") -> None:
        valid = min(self.cnt, self.history_total.shape[1])
        if valid <= 0:
            return
        data = self.history_total[:, :valid]

        plt.figure(figsize=(14, 7))
        plt.imshow(data, cmap="coolwarm", aspect="auto")
        plt.colorbar(label="Flow (m^3/s)")
        plt.title("河道流量热图")
        plt.xlabel("Time / min")
        plt.ylabel("Cell")
        plt.tight_layout()
        _save_fig(f"{tag}河道热图_{self.name}")

        n_sta = len(self.configs)
        plt.figure(figsize=(14, 8))
        nrows = n_sta // 2 + n_sta % 2
        for i in range(n_sta):
            ax = plt.subplot(nrows, 2, i + 1)
            ax.plot(data[self.capa_loc[i], :], "b-", lw=1.0, label=f"{self.configs[i]['Name']} In")
            ax.plot(data[self.capa_loc[i] + 1, :], "r-", lw=1.0, label=f"{self.configs[i]['Name']} Out")
            ax.set(xlabel="min", ylabel="m^3/s")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)
        plt.suptitle("梯级入流/出流", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"{tag}河道入出流_{self.name}")

        plt.figure(figsize=(14, 8))
        picks = np.linspace(0, valid - 1, min(9, valid), dtype=int)
        for k, ti in enumerate(picks):
            ax = plt.subplot(3, 3, k + 1)
            ax.plot(data[:, ti], "k-", lw=1.2, label=f"t={ti}")
            ax.set(xlabel="Cell", ylabel="m^3/s")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)
        plt.suptitle("河道时间断面", fontsize=14, fontweight="bold")
        plt.tight_layout()
        _save_fig(f"{tag}河道断面_{self.name}")

# =============================================================================
# 运行入口
# =============================================================================

def _configure_output_dir(output_dir: str | None) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out = os.path.abspath(output_dir or os.environ.get("HYDRO_OUTPUT_DIR") or script_dir)
    _set_output_dir(out)
    return _OUTPUT_DIR


def _validate_configs() -> None:
    validate_hydrosim_config()


def _validate_range(name: str, low: float, high: float) -> Tuple[float, float]:
    lo = float(low)
    hi = float(high)
    if hi < lo:
        raise ValueError(f"{name} 区间非法：high({hi}) < low({lo})。")
    return lo, hi


def _read_yaml(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _read_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _object_ids(item: Dict) -> List[int]:
    ids = item.get("object_ids") or []
    if item.get("object_id") is not None:
        ids = list(ids) + [item["object_id"]]
    return [int(v) for v in ids]


def _series_points(item: Dict) -> Tuple[np.ndarray, np.ndarray]:
    pairs = []
    for row in item.get("time_series", []):
        if "step" not in row or "value" not in row:
            continue
        pairs.append((int(row["step"]), float(row["value"])))
    if not pairs:
        raise ValueError(f"{item.get('object_name', '')}: time_series 为空。")
    pairs.sort(key=lambda x: x[0])
    steps = np.array([p[0] for p in pairs], dtype=int)
    values = np.array([p[1] for p in pairs], dtype=float)
    return steps, values


def _interp_series(item: Dict, steps: np.ndarray) -> np.ndarray:
    src_steps, src_values = _series_points(item)
    return np.interp(steps, src_steps, src_values).astype(float)


def _time_axis_from_event(event: Dict, sim_steps: int | None = None) -> np.ndarray:
    max_step = 0
    for item in event.get("object_time_series", []):
        for row in item.get("time_series", []):
            if "step" in row:
                max_step = max(max_step, int(row["step"]))
    if sim_steps is not None:
        if sim_steps <= 0:
            raise ValueError("sim_steps 必须 > 0。")
        return np.arange(int(sim_steps), dtype=int)
    return np.arange(max_step + 1, dtype=int)


def _station_name_by_node() -> Dict[int, str]:
    return build_station_name_map()


def _initial_overrides(initial_states: Dict) -> Dict[Tuple[int, str], float]:
    root = initial_states.get("initial_states", initial_states)
    result: Dict[Tuple[int, str], float] = {}
    for section in root.values():
        if not isinstance(section, dict):
            continue
        overrides = section.get("overrides", [])
        if isinstance(overrides, dict):
            items = []
            for value in overrides.values():
                if isinstance(value, list):
                    items.extend(value)
            overrides = items
        for row in overrides or []:
            if not isinstance(row, dict) or row.get("id") is None:
                continue
            try:
                obj_id = int(row["id"])
            except (TypeError, ValueError):
                continue
            metric = str(row.get("metrics_code", ""))
            if metric and "value" in row:
                result[(obj_id, metric)] = float(row["value"])
    return result


def _target_limits_by_node(constraints: Dict) -> Dict[int, Dict]:
    limits = {}
    for row in constraints.get("control_targets", []) or []:
        node_id = int(row["node_id"])
        limits[node_id] = dict(row)
    return limits


def _apply_yaml_basic_parameters(
    flow_configs: List[Dict],
    constraints: Dict,
    initial_states: Dict,
    event: Dict,
) -> Tuple[List[Dict], Dict[int, float]]:
    configs = copy.deepcopy(flow_configs)
    limits = _target_limits_by_node(constraints)
    initial = _initial_overrides(initial_states)
    first_water_level = {}

    for item in event.get("object_time_series", []):
        if item.get("object_type") != "Station" or item.get("metrics_code") != "water_level":
            continue
        steps, values = _series_points(item)
        if steps.size:
            for node_id in _object_ids(item):
                first_water_level[int(node_id)] = float(values[0])

    target_stage_by_node: Dict[int, float] = {}
    for node_id, idx in NODE_TO_INDEX.items():
        cfg = configs[idx]
        if node_id in limits:
            limit = limits[node_id]
            cfg["min_stage"] = float(limit.get("min_water_level", cfg["min_stage"]))
            cfg["max_stage"] = float(limit.get("max_water_level", cfg["max_stage"]))
            cfg["design_stage"] = _clip(
                cfg["design_stage"],
                cfg["min_stage"],
                cfg["max_stage"],
            )
            cfg["max_spill_q"] = float(limit.get("max_flow", cfg.get("max_spill_q", 20000.0)))

        initial_stage = None
        if (node_id, "water_level") in initial:
            initial_stage = initial[(node_id, "water_level")]
        canal_id = STATION_CANAL_IDS[idx]
        if initial_stage is None and (canal_id, "water_depth") in initial:
            initial_stage = initial[(canal_id, "water_depth")]
        if initial_stage is None and node_id in first_water_level:
            initial_stage = first_water_level[node_id]
        if initial_stage is not None:
            cfg["initial_stage"] = _clip(float(initial_stage), cfg["min_stage"], cfg["max_stage"])

        target_stage_by_node[node_id] = _clip(
            first_water_level.get(node_id, cfg["design_stage"]),
            cfg["min_stage"],
            cfg["max_stage"],
        )

    return configs, target_stage_by_node


def _set_reservoir_stage(res: HydroReservoir, stage: float) -> None:
    res.current_stage = _clip(float(stage), res.min_stage, res.max_stage)
    res.current_capacity = res.stage_to_capacity(res.current_stage)
    res.target_stage = res.current_stage
    res.target_capacity = res.current_capacity
    res.PID.initialize(res.current_stage)


def _apply_initial_conditions(
    multi_reservoir: HydroResStairs,
    multi_stair: HydroStair,
    flow_configs: Sequence[Dict],
    initial_states: Dict,
) -> float:
    initial = _initial_overrides(initial_states)
    for idx, res in enumerate(multi_reservoir.Capacity_Stairs):
        cfg = flow_configs[idx]
        if "initial_stage" in cfg:
            _set_reservoir_stage(res, float(cfg["initial_stage"]))

    turbine_power_by_node: Dict[int, float] = {node_id: 0.0 for node_id in STATION_NODE_IDS}
    for (obj_id, metric), value in initial.items():
        if metric != "power":
            continue
        node_id = _infer_station_node_for_device(obj_id)
        if node_id in turbine_power_by_node:
            turbine_power_by_node[node_id] += float(value)

    total_power = 0.0
    for node_id, power in turbine_power_by_node.items():
        if power <= 1e-9:
            continue
        idx = NODE_TO_INDEX[node_id]
        multi_stair.multi_stair[idx].signal_inti_set(power)
        total_power += power
    return total_power


def _infer_station_node_for_device(device_id: int) -> int | None:
    device_id = int(device_id)
    if 20101 <= device_id <= 20199:
        return 20100
    if 20301 <= device_id <= 20399:
        return 20300
    if 20501 <= device_id <= 20599:
        return 20500
    if 20701 <= device_id <= 20799:
        return 20700
    return None


def _power_series_by_station(event: Dict, steps: np.ndarray) -> Tuple[np.ndarray, Dict[int, np.ndarray]]:
    station_power = {node_id: np.zeros(len(steps), dtype=float) for node_id in STATION_NODE_IDS}
    explicit: set[int] = set()

    for item in event.get("object_time_series", []):
        if item.get("object_type") != "Station" or item.get("metrics_code") != "power":
            continue
        ids = [node_id for node_id in _object_ids(item) if node_id in NODE_TO_INDEX]
        if not ids:
            continue
        series = _interp_series(item, steps)
        if len(ids) == 1:
            station_power[ids[0]] += series
            explicit.add(ids[0])
        else:
            weights = np.array([POWER_CONFIGS[NODE_TO_INDEX[node_id]]["design_power"] for node_id in ids], dtype=float)
            weights = weights / max(float(weights.sum()), 1e-9)
            for node_id, weight in zip(ids, weights):
                station_power[node_id] += series * weight
                explicit.add(node_id)

    total_power = np.zeros(len(steps), dtype=float)
    for series in station_power.values():
        total_power += series
    if not explicit:
        raise ValueError("time_series 中未找到 Station/power 出力计划。")
    return total_power, station_power


def _upstream_inflow_series(event: Dict, steps: np.ndarray, initial_states: Dict) -> np.ndarray:
    candidates = []
    for item in event.get("object_time_series", []):
        if item.get("object_type") == "Station" and item.get("metrics_code") == "water_flow":
            if any(node_id == STATION_NODE_IDS[0] for node_id in _object_ids(item)):
                candidates.append(item)
    if candidates:
        return _interp_series(candidates[0], steps)

    initial = _initial_overrides(initial_states)
    fallback = initial.get((20001, "water_flow"), 1000.0)
    return np.ones(len(steps), dtype=float) * float(fallback)


def _target_stage_series_by_node(
    event: Dict,
    steps: np.ndarray,
    default_by_node: Dict[int, float],
) -> Dict[int, np.ndarray]:
    result = {node_id: np.ones(len(steps), dtype=float) * float(default_by_node[node_id]) for node_id in STATION_NODE_IDS}
    for item in event.get("object_time_series", []):
        if item.get("object_type") != "Station" or item.get("metrics_code") != "water_level":
            continue
        series = _interp_series(item, steps)
        for node_id in _object_ids(item):
            if node_id in result:
                result[node_id] = series
    return result


def _set_step_target_stages(
    reservoirs: HydroResStairs,
    target_stage_by_node: Dict[int, np.ndarray],
    step_idx: int,
) -> None:
    for node_id, idx in NODE_TO_INDEX.items():
        res = reservoirs.Capacity_Stairs[idx]
        target = float(target_stage_by_node[node_id][step_idx])
        res.target_stage = _clip(target, res.min_stage, res.max_stage)
        res.target_capacity = res.stage_to_capacity(res.target_stage)


def _run_phase_v16(
    title: str,
    idx_start: int,
    idx_end: int,
    progress_interval: int,
    flows_in: np.ndarray,
    power_cmd: np.ndarray,
    target_stage_by_node: Dict[int, np.ndarray],
    multi_river: RiverArray,
    multi_reservoir: HydroResStairs,
    multi_stair: HydroStair,
) -> None:
    total = idx_end - idx_start
    if total <= 0:
        return

    for i in range(idx_start, idx_end):
        _set_step_target_stages(multi_reservoir, target_stage_by_node, i)
        multi_stair.update_stage_hints(multi_reservoir.stage_hints())
        multi_stair.step_execute(power_cmd[i])
        multi_reservoir.step(multi_river, multi_stair, record=True)
        multi_river.step_execute(multi_reservoir, flows_in[i])

        done = i - idx_start + 1
        if progress_interval > 0 and (done % progress_interval == 0 or done == total):
            print(f"{title}进度: {done:4d} / {total}")


def _run_phase(
    title: str,
    idx_start: int,
    idx_end: int,
    progress_interval: int,
    flows_in: np.ndarray,
    power_cmd: np.ndarray,
    multi_river: RiverArray,
    multi_reservoir: HydroResStairs,
    multi_stair: HydroStair,
) -> None:
    total = idx_end - idx_start
    if total <= 0:
        return

    for i in range(idx_start, idx_end):
        multi_stair.update_stage_hints(multi_reservoir.stage_hints())
        multi_stair.step_execute(power_cmd[i])
        multi_reservoir.step(multi_river, multi_stair, record=True)
        multi_river.step_execute(multi_reservoir, flows_in[i])

        done = i - idx_start + 1
        if progress_interval > 0 and (done % progress_interval == 0 or done == total):
            print(f"{title}进度: {done:4d} / {total}")






