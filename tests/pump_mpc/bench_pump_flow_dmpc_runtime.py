"""Benchmark pump_flow_dmpc lower-controller single-step runtime.

用法:
    python tests/pump_mpc/bench_pump_flow_dmpc_runtime.py <input.json> \
        [--iterations N] [--per-station] [--show-output]

``<input.json>`` 是一次 ``ControlAlgorithmInput`` 的 JSON 请求体（与 edge 调用
``solve`` 时传入的参数一致）。脚本只做读取与计时，不修改任何源代码。

默认静默掉控制台决策表格与求解器参数打印，避免打印开销污染计时；如需查看
每次控制器的实际输出，追加 ``--show-output``。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUMP_AGENT_ROOT = PROJECT_ROOT / "custom-agent" / "pump"

for root in (str(PROJECT_ROOT), str(PUMP_AGENT_ROOT)):
    if root not in sys.path:
        sys.path.insert(0, root)

from hydros_agent_sdk.control_algorithms import (  # noqa: E402
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
)
from pump_flow_dmpc import (  # noqa: E402
    PumpFlowDmpcInputResolver,
    PumpFlowDmpcSolver,
    PumpStationFlowDmpcAlgorithm,
)
from pump_flow_dmpc.console_reporter import PumpFlowDmpcConsoleReporter  # noqa: E402


def _quiet_printer(*_args, **_kwargs) -> None:
    """Silence the default console reporter output during timing."""


def _run(fn: Callable[[], object], show_output: bool) -> Tuple[float, object]:
    """Run ``fn`` and return ``(elapsed_seconds, result)``.

    Unless ``show_output`` is set, stdout is redirected so solver parameter prints
    and controller decision tables do not pollute the timing output.
    """

    if show_output:
        start = time.perf_counter()
        result = fn()
        return time.perf_counter() - start, result

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        start = time.perf_counter()
        result = fn()
    return time.perf_counter() - start, result


def _fmt_stats(values: List[float]) -> str:
    values = sorted(values)
    return (
        "count=%d min=%.4fs median=%.4fs mean=%.4fs max=%.4fs"
        % (
            len(values),
            values[0],
            statistics.median(values),
            statistics.fmean(values),
            values[-1],
        )
    )


def _print_output_summary(output: ControlAlgorithmOutput) -> None:
    station_count = output.evidence.get("station_count")
    station_ids = output.evidence.get("station_ids")
    print(
        "  status=%s station_count=%s station_ids=%s results=%d actuator_targets=%d"
        % (
            output.status.value,
            station_count,
            station_ids,
            len(output.results),
            len(output.actuator_targets),
        )
    )


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark pump_flow_dmpc single-step lower-controller runtime."
    )
    parser.add_argument("input_json", help="path to a captured ControlAlgorithmInput JSON")
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="number of warm solve iterations for statistics (default: 5)",
    )
    parser.add_argument(
        "--per-station",
        action="store_true",
        help="also time solver.solve() separately for each pump station",
    )
    parser.add_argument(
        "--show-output",
        action="store_true",
        help="print controller decision tables instead of suppressing them",
    )
    args = parser.parse_args(argv)

    raw = Path(args.input_json).read_text(encoding="utf-8")
    input_data = ControlAlgorithmInput.model_validate(json.loads(raw))

    resolver = PumpFlowDmpcInputResolver()
    solver = PumpFlowDmpcSolver()
    algorithm = PumpStationFlowDmpcAlgorithm(
        solver=solver,
        resolver=resolver,
        console_reporter=PumpFlowDmpcConsoleReporter(printer=_quiet_printer),
    )

    station_ids = resolver.resolve_station_ids(input_data)
    print("input=%s" % args.input_json)
    print("stations=%s" % station_ids)

    # First call pays config load / runtime build; measure it separately.
    cold_elapsed, output = _run(lambda: algorithm.solve(input_data), args.show_output)
    print("cold algorithm.solve (includes config load): %.4fs" % cold_elapsed)
    _print_output_summary(output)

    warm: List[float] = []
    for _ in range(max(1, args.iterations)):
        elapsed, output = _run(lambda: algorithm.solve(input_data), args.show_output)
        warm.append(elapsed)
    print("warm algorithm.solve: %s" % _fmt_stats(warm))
    _print_output_summary(output)

    if args.per_station:
        station_arguments = [
            resolver.resolve_station(input_data, sid) for sid in station_ids
        ]
        print("per-station solver.solve (warm):")
        for sid, arguments in zip(station_ids, station_arguments):
            # One warm-up call to ensure the local controller is loaded.
            _run(lambda a=arguments: solver.solve(a), args.show_output)
            samples: List[float] = []
            for _ in range(max(1, args.iterations)):
                elapsed, _ = _run(
                    lambda a=arguments: solver.solve(a), args.show_output
                )
                samples.append(elapsed)
            print("  station %d: %s" % (sid, _fmt_stats(samples)))


if __name__ == "__main__":
    main()
