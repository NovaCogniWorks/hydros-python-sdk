import numpy as np
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt

class PlotHistoryTracker:
    def __init__(self, system_config, demand_plan=None, output_dir=None):
        self.system_config = system_config
        if demand_plan is not None:
            self.demand_plan = demand_plan
        else:
            self.demand_plan = pd.DataFrame()
            
        self.output_dir = Path(output_dir) if output_dir else Path("output/agent_steps")
        self.steps_dir = self.output_dir
        self.steps_dir.mkdir(parents=True, exist_ok=True)
        
        self.hours = int(self.system_config.horizon_hours) if hasattr(self.system_config, 'horizon_hours') else 72
        
        self.hist_times = []
        self.hist_flows = {sid: [] for sid in self.system_config.station_ids}
        self.hist_back_levels = {sid: [] for sid in self.system_config.station_ids}
        self.hist_front_levels = {sid: [] for sid in self.system_config.station_ids}
        self.hist_pool_levels = {pid: [] for pid in self.system_config.pool_ids}
        self.hist_disturbances = {pid: [] for pid in self.system_config.pool_ids}
        self.hist_upper_flow_errors = {sid: [] for sid in self.system_config.station_ids}
        self.hist_lower_flow_errors = {sid: [] for sid in self.system_config.station_ids}
        self.hist_efficiencies = {sid: [] for sid in self.system_config.station_ids}
        self.hist_odd_flow_errors = {sid: [] for sid in self.system_config.station_ids}
        self.hist_odd_level_errors = {sid: [] for sid in self.system_config.station_ids}
        self.hist_unit_status = []
        
        # We need a mock runtime or just create a dict for odd boundaries
        self.odd1_flow_tolerance = 0.5
        self.odd3_flow_tolerance = 2.0
        
    def _fmt(self, val):
        if val is None or np.isnan(val): return "N/A"
        return f"{val:.2f}"

    def update_and_plot(self, step_index, current_time_hours, lower_step_hours, upper_plan, actions, decisions, observation, transfer_bundles):
        # Update histories
        self.hist_times.append(current_time_hours)
        snapshot = {}
        for station_id in self.system_config.station_ids:
            # Flow
            flow = float(observation.station_flows[station_id])
            self.hist_flows[station_id].append(flow)
            
            # Levels
            back = float(observation.station_back_levels[station_id])
            front = float(observation.station_front_levels[station_id])
            self.hist_back_levels[station_id].append(back)
            self.hist_front_levels[station_id].append(front)
            
            # Efficiency
            # Since we might not have _actual_unit_metrics easily, we can just use total station flow and head to estimate efficiency
            # or just default to 0 for plotting if not available
            eff = float(actions[station_id].predicted_efficiencies[0]) if hasattr(actions[station_id], 'predicted_efficiencies') and actions[station_id].predicted_efficiencies else 0.0
            self.hist_efficiencies[station_id].append(eff)
            
            # Errors
            self.hist_odd_flow_errors[station_id].append(float(decisions[station_id].flow_error))
            self.hist_odd_level_errors[station_id].append(float(decisions[station_id].level_error))
            
            self.hist_upper_flow_errors[station_id].append(0.0) # placeholders
            self.hist_lower_flow_errors[station_id].append(0.0)
            
            # Units
            station_snapshot = {}
            station = self.system_config.station_by_id[station_id]
            for unit in station.units:
                station_snapshot[unit.name] = {
                    "Status": int(actions[station_id].unit_status.get(unit.id, 0)),
                    "Opening": float(actions[station_id].unit_openings.get(unit.id, 0.0)),
                }
            snapshot[station_id] = station_snapshot
            
        self.hist_unit_status.append(snapshot)
        
        for pool_id in self.system_config.pool_ids:
            self.hist_pool_levels[pool_id].append(float(observation.pool_levels.get(pool_id, 0.0)))
            self.hist_disturbances[pool_id].append(float(transfer_bundles[self.system_config.station_ids[0]].disturbance_estimate.get(pool_id, 0.0)))
            
        # Build lower prediction plan
        lower_prediction_plan = {}
        for station_id in self.system_config.station_ids:
            reference_flow = [float(f) for f in upper_plan.flow_refs[station_id]]
            lower_prediction_plan[station_id] = [actions[station_id].selected_flow] + reference_flow[1:]
            
        # Call plot
        self._plot_step(
            step_index=step_index,
            current_time_hours=current_time_hours,
            lower_step_hours=lower_step_hours,
            upper_plan=upper_plan,
            lower_prediction_plan=lower_prediction_plan,
            hist_times=self.hist_times,
            hist_flows=self.hist_flows,
            hist_back_levels=self.hist_back_levels,
            hist_front_levels=self.hist_front_levels,
            hist_pool_levels=self.hist_pool_levels,
            hist_disturbances=self.hist_disturbances,
            hist_upper_flow_errors=self.hist_upper_flow_errors,
            hist_lower_flow_errors=self.hist_lower_flow_errors,
            hist_efficiencies=self.hist_efficiencies,
            hist_odd_flow_errors=self.hist_odd_flow_errors,
            hist_odd_level_errors=self.hist_odd_level_errors,
            actions=actions,
            decisions=decisions,
            hist_unit_status=self.hist_unit_status,
        )

    def _predicted_series(self, predicted_values, history_values, n_points):
        if predicted_values:
            res = list(predicted_values[:n_points])
            if len(res) < n_points:
                res.extend([res[-1]] * (n_points - len(res)))
            return res
        fallback = history_values[-1] if history_values else 0.0
        return [fallback] * n_points

    def _disturbance_reference_series(self):
        n_points = min(self.hours, len(self.demand_plan))
        times = np.arange(n_points, dtype=float)
        pool_ids = list(self.system_config.pool_ids)
        demand_series = {}
        rain_series = {pool_id: [] for pool_id in pool_ids}
        # Simplified for plot since we don't have the environment hidden plan
        for pool_id in pool_ids:
            demand_series[pool_id] = np.zeros(n_points, dtype=float)
            rain_series[pool_id] = np.zeros(n_points, dtype=float)
        return times, demand_series, {pool_id: np.asarray(values, dtype=float) for pool_id, values in rain_series.items()}

    def _current_mode_summary(self, actions) -> str:
        return " | ".join(
            [f"S{station_id}: {actions[station_id].mode}" for station_id in self.system_config.station_ids]
        )

    def _plot_step(
        self,
        step_index: int,
        current_time_hours: float,
        lower_step_hours: float,
        upper_plan,
        lower_prediction_plan,
        hist_times,
        hist_flows,
        hist_back_levels,
        hist_front_levels,
        hist_pool_levels,
        hist_disturbances,
        hist_upper_flow_errors,
        hist_lower_flow_errors,
        hist_efficiencies,
        hist_odd_flow_errors,
        hist_odd_level_errors,
        actions,
        decisions,
        hist_unit_status,
    ) -> None:
        station_ids = self.system_config.station_ids
        pool_ids = self.system_config.pool_ids
        n_stations = len(station_ids)
        segments = getattr(self.system_config.topology, 'channel_segments', []) if hasattr(self.system_config, 'topology') else []
        n_rows = n_stations + 1 + len(segments)
        fig = plt.figure(figsize=(34, 4.5 * n_rows + 5))
        gs = fig.add_gridspec(n_rows, 6)
        fig.suptitle(
            f"Step {step_index:03d} | Modes: {self._current_mode_summary(actions)}",
            fontsize=18,
            y=0.99,
        )
        times_hist = np.asarray(hist_times, dtype=float)
        plan_len = len(lower_prediction_plan[station_ids[0]]) if station_ids else 0
        upper_len = len(upper_plan.flow_refs[station_ids[0]]) if station_ids else 0
        times_plan = current_time_hours + np.arange(plan_len, dtype=float) * lower_step_hours
        times_upper = current_time_hours + np.arange(upper_len, dtype=float) * float(self.system_config.dt_hours)
        
        station_palette = plt.cm.tab10(np.linspace(0.2, 0.9, max(n_stations, 1)))
        cmap_cycle = [plt.cm.Blues, plt.cm.Greens, plt.cm.Reds, plt.cm.Purples, plt.cm.Oranges, plt.cm.Greys]
        station_palettes = {
            station.id: cmap_cycle[idx % len(cmap_cycle)](
                np.linspace(0.45, 0.9, len(station.units))
            )
            for idx, station in enumerate(self.system_config.stations)
        }
        
        for idx, station_id in enumerate(station_ids):
            color = station_palette[idx % len(station_palette)]
            station = self.system_config.station_by_id[station_id]
            action = actions[station_id]
            
            # 1. Flow
            ax_flow = fig.add_subplot(gs[idx, 0])
            ax_flow.plot(times_hist, hist_flows[station_id], color=color, linestyle="-", label="Actual Q")
            ax_flow.plot(times_plan, lower_prediction_plan[station_id], color=color, linestyle="--", alpha=0.5, label="Lower Pred")
            ax_flow.step(times_upper, upper_plan.flow_refs[station_id], color=color, linestyle=":", where="post", alpha=0.8, label="Upper Plan")
            ax_flow.set_title(f"S{station_id} Flow")
            ax_flow.set_ylabel("Flow (m3/s)")
            ax_flow.set_xlim([0, self.hours])
            ax_flow.legend(loc="upper right", fontsize=8)
            ax_flow.grid(True)
            
            # 2. Head
            ax_head = fig.add_subplot(gs[idx, 1])
            
            act_back_arr = np.array(hist_back_levels[station_id]) if hist_back_levels[station_id] else np.array([])
            act_front_arr = np.array(hist_front_levels[station_id]) if hist_front_levels[station_id] else np.array([])
            if act_back_arr.size > 0 and act_front_arr.size > 0:
                ax_head.plot(times_hist, act_back_arr - act_front_arr, color=color, linestyle="-", label="Actual Head")
                
            pred_back_arr = np.array(upper_plan.station_back_levels.get(station_id, []))
            pred_front_arr = np.array(upper_plan.station_front_levels.get(station_id, []))
            if pred_back_arr.size > 0 and pred_front_arr.size > 0:
                ax_head.step(times_upper, pred_back_arr - pred_front_arr, color=color, linestyle=":", alpha=0.8, where="post", label="Pred Head")
                
            ax_head.set_title(f"S{station_id} Head")
            ax_head.set_ylabel("Head (m)")
            ax_head.set_xlim([0, self.hours])
            ax_head.legend(loc="upper right", fontsize=8)
            ax_head.grid(True)
            
            # 3. Efficiency
            ax_eff = fig.add_subplot(gs[idx, 2])
            ax_eff.plot(times_hist, hist_efficiencies[station_id], color=color, linestyle="-", label="Efficiency %")
            ax_eff.plot(times_plan, self._predicted_series(action.predicted_efficiencies, hist_efficiencies[station_id], len(times_plan)), color=color, linestyle="--", alpha=0.5, label="Pred Eff")
            ax_eff.set_title(f"S{station_id} Efficiency")
            ax_eff.set_ylabel("Eff (%)")
            ax_eff.set_xlim([0, self.hours])
            ax_eff.set_ylim([0, 100])
            ax_eff.legend(loc="lower right", fontsize=8)
            ax_eff.grid(True)
            
            # 4. Blade Angles
            ax_angle = fig.add_subplot(gs[idx, 3])
            palette_st = station_palettes[station_id]
            for u_idx, unit in enumerate(station.units):
                actual_angles = [step_data[station_id][unit.name]["Opening"] for step_data in hist_unit_status]
                pred_angles = [float(action.unit_openings.get(unit.id, 0.0))] * len(times_plan)
                u_color = palette_st[u_idx]
                ax_angle.plot(times_hist, actual_angles, color=u_color, label=f"U{unit.id} Actual")
                ax_angle.plot(times_plan, pred_angles, "--", color=u_color, alpha=0.55)
            ax_angle.set_title(f"S{station_id} Blade Angles")
            ax_angle.set_ylabel("Angle")
            ax_angle.set_xlim([0, self.hours])
            ax_angle.legend(loc="upper right", ncol=2, fontsize=7)
            ax_angle.grid(True)
            
            # 5. ODD Domain
            ax_odd = fig.add_subplot(gs[idx, 4])
            odd3_boundary = max(float(self.odd3_flow_tolerance), float(self.odd1_flow_tolerance))
            ymax = max(
                odd3_boundary * 1.2,
                max(hist_odd_flow_errors[station_id]) if hist_odd_flow_errors[station_id] else odd3_boundary,
            )
            ax_odd.axhspan(0.0, self.odd1_flow_tolerance, color="#d9f2d9", alpha=0.55, label="ODD1")
            ax_odd.axhspan(self.odd1_flow_tolerance, odd3_boundary, color="#fff2cc", alpha=0.55, label="ODD2")
            ax_odd.axhspan(odd3_boundary, ymax, color="#fce5cd", alpha=0.55, label="ODD3")
            ax_odd.axhline(self.odd1_flow_tolerance, color="#6aa84f", linestyle=":")
            ax_odd.axhline(odd3_boundary, color="#bf9000", linestyle=":")
            
            ax_odd.plot(times_hist, hist_odd_flow_errors[station_id], color=color, linestyle="-", label="dQ Decision")
            if hist_odd_flow_errors[station_id]:
                ax_odd.scatter(times_hist[-1], hist_odd_flow_errors[station_id][-1], color=color, s=36, zorder=5)
            ax_odd.set_title(f"S{station_id} ODD Domain")
            ax_odd.set_ylabel("dQ (m3/s)")
            ax_odd.set_xlim([0, self.hours])
            ax_odd.set_ylim([0.0, ymax])
            ax_odd.legend(loc="upper right", fontsize=7)
            ax_odd.grid(True)
            
            # 6. Detailed Text Summary
            ax_text = fig.add_subplot(gs[idx, 5])
            ax_text.axis("off")
            
            up_q = self._fmt(upper_plan.flow_refs[station_id][0]) if len(upper_plan.flow_refs[station_id]) > 0 else "N/A"
            dn_q = self._fmt(lower_prediction_plan[station_id][0]) if len(lower_prediction_plan[station_id]) > 0 else "N/A"
            act_q = self._fmt(hist_flows[station_id][-1]) if hist_flows[station_id] else "N/A"
            act_eff = self._fmt(hist_efficiencies[station_id][-1]) if hist_efficiencies[station_id] else "N/A"
            dq = self._fmt(decisions[station_id].flow_error)
            dz = self._fmt(decisions[station_id].level_error)
            
            pred_back = upper_plan.station_back_levels[station_id][0] if station_id in upper_plan.station_back_levels and len(upper_plan.station_back_levels[station_id]) > 0 else None
            pred_front = upper_plan.station_front_levels[station_id][0] if station_id in upper_plan.station_front_levels and len(upper_plan.station_front_levels[station_id]) > 0 else None
            pred_h = self._fmt(pred_back - pred_front) if pred_back is not None and pred_front is not None else "N/A"
            
            act_back = hist_back_levels[station_id][-1] if hist_back_levels[station_id] else None
            act_front = hist_front_levels[station_id][-1] if hist_front_levels[station_id] else None
            act_h = self._fmt(act_back - act_front) if act_back is not None and act_front is not None else "N/A"
            
            text_lines = [
                f"S{station_id} Mode: {actions[station_id].mode}",
                f"Upper MPC  : Q={up_q}",
                f"Head(Pred/Act): {pred_h} / {act_h} m",
                f"Lower Pred : Q={dn_q}",
                f"Actual     : Q={act_q}, Eff={act_eff}%",
                f"Deviations : dQ={dq}, dZ={dz}",
                "-" * 30
            ]
            
            actual_snapshot = hist_unit_status[-1][station_id] if hist_unit_status else {}
            for unit in station.units:
                actual_payload = actual_snapshot.get(unit.name, {"Status": 0, "Opening": 0.0})
                actual_status = "ON" if int(actual_payload.get("Status", 0)) == 1 else "OFF"
                command_status = "ON" if int(action.unit_status.get(unit.id, 0)) == 1 else "OFF"
                actual_opening = float(actual_payload.get("Opening", 0.0))
                command_opening = float(action.unit_openings.get(unit.id, 0.0))
                
                text_lines.append(
                    f"U{unit.id}: {actual_status}({self._fmt(actual_opening):>5}) -> {command_status}({self._fmt(command_opening):>5})"
                )
                
            ax_text.text(
                0.02, 0.5,
                "\n".join(text_lines),
                transform=ax_text.transAxes,
                ha="left", va="center",
                fontsize=11, family="monospace",
                bbox={"boxstyle": "round", "facecolor": "#f8f9fa", "alpha": 0.9, "edgecolor": "#cccccc"}
            )
            
        ax_dist = fig.add_subplot(gs[n_stations, :])
        disturbance_times, demand_series, rain_series = self._disturbance_reference_series()
        disturbance_palette = plt.cm.tab20(np.linspace(0.1, 0.9, max(len(pool_ids), 1)))
        for p_idx, pool_id in enumerate(pool_ids):
            color = disturbance_palette[p_idx % len(disturbance_palette)]
            ax_dist.plot(times_hist, hist_disturbances[pool_id], color=color, linestyle="-", label=f"Pool{pool_id} Dist Est")
            ax_dist.plot(disturbance_times, demand_series.get(pool_id, np.zeros_like(disturbance_times)), color=color, alpha=0.6, label=f"Plan Pool{pool_id}")
            ax_dist.step(disturbance_times, rain_series.get(pool_id, np.zeros_like(disturbance_times)), where="post", color=color, linestyle="--", alpha=0.8, label=f"Rain Pool{pool_id}")
            
        series_for_limit = [
            *[np.asarray(hist_disturbances[pool_id]) for pool_id in pool_ids],
            *[np.asarray(demand_series.get(pool_id, np.zeros_like(disturbance_times))) for pool_id in pool_ids],
            *[np.asarray(rain_series.get(pool_id, np.zeros_like(disturbance_times))) for pool_id in pool_ids],
        ]
        non_empty = [series for series in series_for_limit if series.size]
        all_d = np.concatenate(non_empty) if non_empty else np.asarray([0.0])
        limit = max(np.max(np.abs(all_d)) * 1.1, 0.01)
        ax_dist.set_ylim([-limit, limit])
        ax_dist.set_title("System Disturbances (Estimates vs Plans)")
        ax_dist.set_ylabel("Disturbance")
        ax_dist.set_xlabel("Hour")
        ax_dist.set_xlim([0, self.hours])
        ax_dist.legend(loc="upper right", ncol=len(pool_ids), fontsize=8)
        ax_dist.grid(True)
        
        for p_idx, segment in enumerate(segments):
            ax_pool = fig.add_subplot(gs[n_stations + 1 + p_idx, :])
            up_st_id = segment.upstream_station_id
            dn_st_id = segment.downstream_station_id
            p_color = disturbance_palette[p_idx % len(disturbance_palette)] if len(disturbance_palette) > 0 else "blue"
            
            if up_st_id in hist_back_levels:
                ax_pool.plot(times_hist, hist_back_levels[up_st_id], color=p_color, linestyle="-", label=f"Actual Z_up (S{up_st_id} back)")
            if dn_st_id in hist_front_levels:
                ax_pool.plot(times_hist, hist_front_levels[dn_st_id], color=p_color, linestyle="--", alpha=0.7, label=f"Actual Z_dn (S{dn_st_id} front)")
                
            if up_st_id in upper_plan.station_back_levels and len(upper_plan.station_back_levels[up_st_id]) > 0:
                ax_pool.step(times_upper, upper_plan.station_back_levels[up_st_id], color=p_color, linestyle=":", alpha=0.6, where="post", label=f"Pred Z_up (S{up_st_id})")
            if dn_st_id in upper_plan.station_front_levels and len(upper_plan.station_front_levels[dn_st_id]) > 0:
                ax_pool.step(times_upper, upper_plan.station_front_levels[dn_st_id], color=p_color, linestyle="-.", alpha=0.6, where="post", label=f"Pred Z_dn (S{dn_st_id})")
                
            ax_pool.set_title(f"Pool {segment.id} Level (S{up_st_id} -> S{dn_st_id})")
            ax_pool.set_ylabel("Level (m)")
            ax_pool.set_xlim([0, self.hours])
            ax_pool.legend(loc="upper right", ncol=4, fontsize=8)
            ax_pool.grid(True)
        
        plt.tight_layout(rect=[0.0, 0.0, 1.0, 0.98])
        step_plot_path = self.steps_dir / f"step_{step_index:03d}.png"
        fig.savefig(step_plot_path, dpi=180)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"已生成在线单步状态图: {step_plot_path.absolute()}")
        plt.close(fig)
