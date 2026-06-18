from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from typing import Dict

from hydrosim_api import (
    HydroSimulationApi,
    HydroOutputMode,
)


class HydroSimulationDemo:
    """可直接运行的 Demo：展示算法能力，并提供最小可运行入口。"""

    def __init__(self, api: HydroSimulationApi | None = None) -> None:
        self.api = api or HydroSimulationApi()

    def describe_capabilities(self) -> Dict[str, object]:
        return self.api.describe_capabilities()

    def run_smoke_demo(
        self,
        output_dir: str | None = None,
        make_plots: bool = False,
        output_mode: HydroOutputMode = "mixed",
    ) -> Dict[str, object]:
        artifacts = self.api.run_random(
            sim_steps=1,
            warm_steps=2,
            output_dir=output_dir,
            make_plots=make_plots,
            progress_interval=0,
            output_mode=output_mode,
        )
        if output_mode == "json":
            return artifacts
        return {"capabilities": self.describe_capabilities(), "artifacts": artifacts}

    def run_random_demo(
        self,
        sim_steps: int = 60,
        warm_steps: int = 60,
        output_dir: str | None = None,
        make_plots: bool = False,
        output_mode: HydroOutputMode = "mixed",
    ) -> Dict[str, object]:
        return self.api.run_random(
            sim_steps=sim_steps,
            warm_steps=warm_steps,
            output_dir=output_dir,
            make_plots=make_plots,
            progress_interval=0,
            output_mode=output_mode,
        )

    def run_configured_demo(
        self,
        time_series_file: str,
        mpc_config_file: str = "mpc_config.yaml",
        initial_states_file: str = "initial_states.yaml",
        constraints_file: str = "constrains_targets.yaml",
        output_dir: str | None = None,
        make_plots: bool = False,
        output_mode: HydroOutputMode = "mixed",
    ) -> Dict[str, object]:
        return self.api.run_configured(
            time_series_file=time_series_file,
            mpc_config_file=mpc_config_file,
            initial_states_file=initial_states_file,
            constraints_file=constraints_file,
            output_dir=output_dir,
            make_plots=make_plots,
            progress_interval=0,
            output_mode=output_mode,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HydroSim Demo")
    parser.add_argument("--mode", choices=["smoke", "random", "configured"], default="smoke")
    parser.add_argument("--output-dir", type=str, default=None, help="输出目录")
    parser.add_argument("--sim-steps", type=int, default=60, help="随机模式正式仿真步数")
    parser.add_argument("--warm-steps", type=int, default=60, help="随机模式预热步数")
    parser.add_argument("--make-plots", action="store_true", help="生成图像")
    parser.add_argument("--time-series-file", type=str, default=None, help="配置驱动仿真输入 JSON")
    parser.add_argument("--mpc-config-file", type=str, default="mpc_config.yaml")
    parser.add_argument("--initial-states-file", type=str, default="initial_states.yaml")
    parser.add_argument("--constraints-file", type=str, default="constrains_targets.yaml")
    parser.add_argument("--output-mode", choices=["file", "json", "mixed"], default="mixed")
    parser.add_argument("--print-capabilities", action="store_true", help="仅打印能力摘要")
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = _build_parser().parse_args()
    demo = HydroSimulationDemo()

    if args.print_capabilities:
        print(json.dumps(demo.describe_capabilities(), ensure_ascii=False, indent=2))
        return

    buffer = io.StringIO()
    stream = buffer if args.output_mode == "json" else None
    with contextlib.redirect_stdout(stream) if stream is not None else contextlib.nullcontext():
        if args.mode == "configured":
            if not args.time_series_file:
                raise ValueError("configured 模式需要提供 --time-series-file。")
            result = demo.run_configured_demo(
                time_series_file=args.time_series_file,
                mpc_config_file=args.mpc_config_file,
                initial_states_file=args.initial_states_file,
                constraints_file=args.constraints_file,
                output_dir=args.output_dir,
                make_plots=args.make_plots,
                output_mode=args.output_mode,
            )
        elif args.mode == "random":
            result = demo.run_random_demo(
                sim_steps=args.sim_steps,
                warm_steps=args.warm_steps,
                output_dir=args.output_dir,
                make_plots=args.make_plots,
                output_mode=args.output_mode,
            )
        else:
            result = demo.run_smoke_demo(
                output_dir=args.output_dir,
                make_plots=args.make_plots,
                output_mode=args.output_mode,
            )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
