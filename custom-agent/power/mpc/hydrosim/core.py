from __future__ import annotations

import os
import time
from typing import Any, Dict, Sequence, Tuple

from . import config as hydrosim_config
from . import runtime as default_runtime
from .result_factory import HydroSimulationResultFactory
from .types import HydroConfiguredSimulationRequest, HydroRandomSimulationRequest, HydroSimulationArtifacts


class HydroSimulationCore:
    """算法核心类：负责梯级水电联合仿真的装配、执行与结果导出。"""

    def __init__(
        self,
        runtime: Any | None = None,
        flow_configs: Sequence[Dict] | None = None,
        flow_station_cfgs: Sequence[Dict] | None = None,
        power_configs: Sequence[Dict] | None = None,
        unit_configs: Sequence[Sequence[Dict]] | None = None,
        capa_loc: Sequence[int] | None = None,
    ) -> None:
        self.runtime = runtime or default_runtime
        self.flow_configs = list(flow_configs or hydrosim_config.FLOW_CONFIGS)
        self.flow_station_cfgs = list(flow_station_cfgs or hydrosim_config.FLOW_STATION_CFGS)
        self.power_configs = list(power_configs or hydrosim_config.POWER_CONFIGS)
        self.unit_configs = [list(cfgs) for cfgs in (unit_configs or hydrosim_config.UNIT_CONFIGS)]
        self.capa_loc = list(capa_loc or hydrosim_config.CAPA_LOC)
        self.version = hydrosim_config.__version__
        self.result_factory = HydroSimulationResultFactory(self.runtime)

    def run_random(self, request: HydroRandomSimulationRequest) -> HydroSimulationArtifacts:
        if request.sim_steps <= 0 or request.warm_steps <= 0:
            raise ValueError("sim_steps 与 warm_steps 必须为正整数。")
        flow_low, flow_high = self.runtime._validate_range("flow_range", request.flow_range[0], request.flow_range[1])
        power_low, power_high = self.runtime._validate_range("power_range", request.power_range[0], request.power_range[1])

        t0 = time.perf_counter()
        out = self.runtime._configure_output_dir(request.output_dir)
        self._validate_configs()
        print(f"输出目录: {out}")

        n_total = request.sim_steps + request.warm_steps
        flows_in_sig = self.runtime.NormalizedSignal(n_total, [1200, 300, 770, 6000], seed=request.flow_seed).scale(flow_low, flow_high)
        power_cmd_sig = self.runtime.NormalizedSignal(n_total, [1200, 300, 770, 6000], seed=request.power_seed).scale(power_low, power_high)

        if request.make_plots:
            flows_in_sig.signal_plot(name="大渡河_上游来流Q(m^3/s)")
            power_cmd_sig.signal_plot(name="大渡河_电网调度P(MW)")

        multi_river, multi_reservoir, multi_stair = self._build_runtime_components(
            sim_name_suffix="",
            initial_power=float(power_cmd_sig.signal[0]),
            history_steps=max(request.sim_steps, request.warm_steps),
        )
        min_p_path = self.result_factory.export_dispatch_min_p(out, multi_stair)

        print("开始预热阶段...")
        self.runtime._run_phase(
            title="预热",
            idx_start=0,
            idx_end=request.warm_steps,
            progress_interval=request.progress_interval,
            flows_in=flows_in_sig.signal,
            power_cmd=power_cmd_sig.signal,
            multi_river=multi_river,
            multi_reservoir=multi_reservoir,
            multi_stair=multi_stair,
        )
        print("预热完成。")

        if request.make_plots:
            multi_river.history_plot(tag="预热_")
            multi_reservoir.history_plot(tag="预热_")
            multi_reservoir.odd_plot(history_interval=120, tag="预热_")
            multi_stair.history_plot(tag="预热_")

        multi_river.history_reset()
        multi_reservoir.history_reset()
        multi_stair.history_reset()

        print("开始正式仿真阶段...")
        self.runtime._run_phase(
            title="正式仿真",
            idx_start=request.warm_steps,
            idx_end=n_total,
            progress_interval=request.progress_interval,
            flows_in=flows_in_sig.signal,
            power_cmd=power_cmd_sig.signal,
            multi_river=multi_river,
            multi_reservoir=multi_reservoir,
            multi_stair=multi_stair,
        )
        print("正式仿真完成。")

        formal_results_csv = self.result_factory.export_formal_results_csv(
            output_dir=out,
            flows_in=flows_in_sig.signal,
            power_cmd=power_cmd_sig.signal,
            warm_steps=request.warm_steps,
            multi_stair=multi_stair,
            multi_reservoir=multi_reservoir,
        )
        print(f"正式模拟结果CSV: {formal_results_csv}")

        elapsed = time.perf_counter() - t0
        stage_summary = self.result_factory.stage_zone_summary(multi_reservoir)
        report_path = self.result_factory.export_simulation_report_md(
            output_dir=out,
            sim_steps=request.sim_steps,
            warm_steps=request.warm_steps,
            flow_seed=request.flow_seed,
            power_seed=request.power_seed,
            flow_range=(flow_low, flow_high),
            power_range=(power_low, power_high),
            make_plots=request.make_plots,
            elapsed_seconds=elapsed,
            csv_path=formal_results_csv,
            min_p_path=min_p_path,
            stage_zone_summary=stage_summary,
            multi_stair=multi_stair,
            multi_reservoir=multi_reservoir,
        )
        print(f"仿真汇总报告MD: {report_path}")

        summary_path = self.result_factory.export_run_summary_json(
            output_dir=out,
            sim_steps=request.sim_steps,
            warm_steps=request.warm_steps,
            flow_seed=request.flow_seed,
            power_seed=request.power_seed,
            flow_range=(flow_low, flow_high),
            power_range=(power_low, power_high),
            make_plots=request.make_plots,
            elapsed_seconds=elapsed,
            csv_path=formal_results_csv,
            min_p_path=min_p_path,
            report_path=report_path,
            stage_zone_summary=stage_summary,
        )
        print(f"运行摘要JSON: {summary_path}")
        print(f"总耗时: {elapsed:.2f} s")

        if request.make_plots:
            multi_river.history_plot(tag="正式_")
            multi_reservoir.history_plot(tag="正式_")
            multi_reservoir.odd_plot(history_interval=120, tag="正式_")
            multi_stair.history_plot(tag="正式_")

        print("联合仿真结束。")
        return self.result_factory.build_random_artifacts(out, formal_results_csv, min_p_path, report_path, summary_path, multi_stair)

    def run_configured(self, request: HydroConfiguredSimulationRequest) -> HydroSimulationArtifacts:
        t0 = time.perf_counter()
        out = self.runtime._configure_output_dir(request.output_dir)
        self._validate_configs()

        event = self.runtime._read_json(request.time_series_file)
        self.runtime._read_yaml(request.mpc_config_file)
        initial_states = self.runtime._read_yaml(request.initial_states_file)
        constraints = self.runtime._read_yaml(request.constraints_file)
        if not event.get("valid", True):
            raise ValueError("time_series_file 标记为 valid=false。")

        steps = self.runtime._time_axis_from_event(event, sim_steps=request.sim_steps)
        n_total = len(steps)
        if request.warm_steps < 0 or request.warm_steps >= n_total:
            raise ValueError("warm_steps 必须 >=0 且小于总步数。")

        flow_configs, default_target_stage_by_node = self.runtime._apply_yaml_basic_parameters(
            self.flow_configs,
            constraints,
            initial_states,
            event,
        )
        flows_in = self.runtime._upstream_inflow_series(event, steps, initial_states)
        power_cmd, station_power_plan = self.runtime._power_series_by_station(event, steps)
        target_stage_by_node = self.runtime._target_stage_series_by_node(event, steps, default_target_stage_by_node)

        print(f"输出目录: {out}")
        print(f"配置驱动仿真: 总步数={n_total}, 预热步数={request.warm_steps}, 正式步数={n_total - request.warm_steps}")
        print(f"输入文件: {os.path.abspath(request.time_series_file)}")

        multi_river = self.runtime.RiverArray(
            1,
            "大渡河_水力_V16",
            flow_configs,
            max(n_total - request.warm_steps, 1),
            self.capa_loc,
        )
        multi_reservoir = self.runtime.HydroResStairs(
            1,
            "大渡河_水库_V16",
            flow_configs,
            self.flow_station_cfgs,
            self.capa_loc,
        )
        multi_stair = self.runtime.HydroStair(
            1,
            "大渡河_电站_V16",
            float(power_cmd[0]),
            self.power_configs,
            self.unit_configs,
        )
        self.runtime._apply_initial_conditions(multi_reservoir, multi_stair, flow_configs, initial_states)

        if request.warm_steps > 0:
            print("开始预热阶段...")
            self.runtime._run_phase_v16(
                title="预热",
                idx_start=0,
                idx_end=request.warm_steps,
                progress_interval=request.progress_interval,
                flows_in=flows_in,
                power_cmd=power_cmd,
                target_stage_by_node=target_stage_by_node,
                multi_river=multi_river,
                multi_reservoir=multi_reservoir,
                multi_stair=multi_stair,
            )
            multi_river.history_reset()
            multi_reservoir.history_reset()
            multi_stair.history_reset()

        print("开始正式仿真阶段...")
        self.runtime._run_phase_v16(
            title="正式仿真",
            idx_start=request.warm_steps,
            idx_end=n_total,
            progress_interval=request.progress_interval,
            flows_in=flows_in,
            power_cmd=power_cmd,
            target_stage_by_node=target_stage_by_node,
            multi_river=multi_river,
            multi_reservoir=multi_reservoir,
            multi_stair=multi_stair,
        )
        print("正式仿真完成。")

        formal_results_csv = self.result_factory.export_formal_results_csv(
            output_dir=out,
            flows_in=flows_in,
            power_cmd=power_cmd,
            warm_steps=request.warm_steps,
            multi_stair=multi_stair,
            multi_reservoir=multi_reservoir,
        )
        configured_outputs_yaml = self.result_factory.export_configured_outputs_yaml(
            output_dir=out,
            event=event,
            constraints=constraints,
            steps=steps,
            warm_steps=request.warm_steps,
            flows_in=flows_in,
            power_cmd=power_cmd,
            station_power_plan=station_power_plan,
            multi_stair=multi_stair,
            multi_reservoir=multi_reservoir,
            sample_interval=request.output_sample_interval,
        )

        elapsed = time.perf_counter() - t0
        summary_path = self.result_factory.export_run_summary_json_v16(
            output_dir=out,
            event_path=request.time_series_file,
            mpc_config_path=request.mpc_config_file,
            initial_states_path=request.initial_states_file,
            constraints_path=request.constraints_file,
            sim_steps=n_total - request.warm_steps,
            warm_steps=request.warm_steps,
            elapsed_seconds=elapsed,
            csv_path=formal_results_csv,
            yaml_path=configured_outputs_yaml,
            stage_zone_summary=self.result_factory.stage_zone_summary(multi_reservoir),
        )

        if request.make_plots:
            multi_river.history_plot(tag="V16_正式_")
            multi_reservoir.history_plot(tag="V16_正式_")
            multi_reservoir.odd_plot(history_interval=120, tag="V16_正式_")
            multi_stair.history_plot(tag="V16_正式_")

        print(f"正式模拟结果CSV: {formal_results_csv}")
        print(f"配置指定输出YAML: {configured_outputs_yaml}")
        print(f"运行摘要JSON: {summary_path}")
        print(f"总耗时: {elapsed:.2f} s")

        return self.result_factory.build_configured_artifacts(out, formal_results_csv, configured_outputs_yaml, summary_path, multi_stair)

    def _validate_configs(self) -> None:
        n = len(self.flow_configs)
        if not (n == len(self.flow_station_cfgs) == len(self.power_configs) == len(self.unit_configs)):
            raise ValueError("FLOW/FLOW_STATION/POWER/UNIT 配置长度不一致。")
        if len(self.capa_loc) != n + 1:
            raise ValueError("CAPA_LOC 长度应等于电站数 + 1。")

    def _build_runtime_components(
        self,
        sim_name_suffix: str,
        initial_power: float,
        history_steps: int,
    ) -> Tuple[Any, Any, Any]:
        multi_river = self.runtime.RiverArray(
            1,
            f"大渡河_水力{sim_name_suffix}",
            self.flow_configs,
            history_steps,
            self.capa_loc,
        )
        multi_reservoir = self.runtime.HydroResStairs(
            1,
            f"大渡河_水库{sim_name_suffix}",
            self.flow_configs,
            self.flow_station_cfgs,
            self.capa_loc,
        )
        multi_stair = self.runtime.HydroStair(
            1,
            f"大渡河_电站{sim_name_suffix}",
            initial_power,
            self.power_configs,
            self.unit_configs,
        )
        return multi_river, multi_reservoir, multi_stair
