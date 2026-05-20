import re

with open("custom-agent/pump/scheduling/pump_scheduling_agent.py", "r") as f:
    content = f.read()

# We need to insert _lazy_init_odd_mpc and rewrite on_optimization

lazy_init_code = """
    def _lazy_init_odd_mpc(self):
        if hasattr(self, 'odd_initialized') and self.odd_initialized:
            return
            
        import os
        from .odd_dmpc.config import load_runtime_context
        from .odd_dmpc.flow_service import FlowDepartService
        from .odd_dmpc.local_controller import LocalController
        from .odd_dmpc.observers import DisturbanceObserverBank
        from .odd_dmpc.odd_supervisor import ODDSupervisor
        from .odd_dmpc.upper_scheduler import UpperScheduler
        from .odd_dmpc.types import LowerFeedback, StationMemory
        from .odd_dmpc.environment import _boundary_plan_from_snapshot
        import pandas as pd
        
        # Determine the data directory
        config_path = "data/config_odd.yaml"
        if not os.path.exists(config_path):
            config_path = "../../../data/config_odd.yaml"
            
        context = load_runtime_context(config_path)
        self.system_config = context["system_config"]
        self.runtime = context["runtime"]
        
        self.odd_demand_plan = context["demand_plan"]
        
        self.flow_service = FlowDepartService(self.system_config, config_path=config_path)
        self.local_controller = LocalController(self.system_config, self.runtime, self.flow_service)
        self.supervisor = ODDSupervisor(self.runtime)
        self.observers = DisturbanceObserverBank(self.system_config, self.runtime)
        
        self.available_units_map = {
            station.id: [unit.id for unit in station.units]
            for station in self.system_config.stations
        }
        
        self.lower_feedback = LowerFeedback(
            available_units_map={station_id: ids[:] for station_id, ids in self.available_units_map.items()},
            feasible_flow_ranges={station.id: [0.0, 0.0] for station in self.system_config.stations},
            current_modes={station.id: "ODD1" for station in self.system_config.stations},
            plan_execution_errors={station.id: 0.0 for station in self.system_config.stations},
            reconfigured_stations={station.id: False for station in self.system_config.stations},
        )
        
        self.station_flow_history = {
            station.id: []
            for station in self.system_config.stations
        }
        
        self.cumulative_last_station_flow = 0.0
        self.station_memories = {}
        
        self.odd_initialized = True
        self.upper_scheduler = UpperScheduler(
            self.system_config,
            self.odd_demand_plan,
            self.runtime,
            self.flow_service,
            pd.DataFrame()
        )
"""

on_opt_code = """
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        self._lazy_init_odd_mpc()
        
        from .odd_dmpc.types import EnvironmentObservation, StationMemory
        from .odd_dmpc.local_controller import StationControlContext
        import pandas as pd
        
        station_back_levels = {s.id: s.current_up for s in self.stations}
        station_front_levels = {s.id: s.current_down for s in self.stations}
        station_heads = {s.id: s.current_up - s.current_down for s in self.stations}
        
        basin_levels = {
            "b0": station_front_levels[1],
            "b1": station_back_levels[1],
            "b2": station_back_levels[2],
            "b3": station_back_levels[3]
        }
        
        station_flows = {
            s.id: (self.station_flow_history[s.id][-1] if self.station_flow_history[s.id] else 0.0)
            for s in self.stations
        }
        
        pool_areas = {p.id: p.area for p in self.pools}
        pool_levels = {p.id: basin_levels[f"b{p.id}"] for p in self.pools}
        
        observation = EnvironmentObservation(
            time_index=step,
            time_hours=step * float(self.system_config.dt_hours),
            basin_levels=basin_levels,
            basin_volumes={},
            pool_areas=pool_areas,
            basin_profiles={},
            anchor_basin_levels={"b0": basin_levels["b0"], "b3": basin_levels["b3"]},
            boundary_nominal_flows={},
            station_back_levels=station_back_levels,
            station_front_levels=station_front_levels,
            station_heads=station_heads,
            station_flows=station_flows,
            pool_levels=pool_levels
        )
        
        # Init or update memories from our own self tracked state
        if not self.station_memories:
            for s in self.stations:
                self.station_memories[s.id] = StationMemory(
                    active_unit_ids=[],
                    unit_openings={u: 0.0 for u in self.available_units_map[s.id]},
                    unit_status={u: 0 for u in self.available_units_map[s.id]},
                    time_since_adjust={u: 999 for u in self.available_units_map[s.id]},
                    time_since_switch={u: 999 for u in self.available_units_map[s.id]},
                    last_selected_flow=0.0,
                    mode="ODD1"
                )
                
        # Upper Scheduler
        demand_row = self.odd_demand_plan.iloc[min(max(step, 0), len(self.odd_demand_plan) - 1)]
        self.observers.update(
            prev_basin_levels=basin_levels,
            next_basin_levels=basin_levels, # for test_mpc simplicity, we don't have prev
            actual_flows=station_flows,
            demand_row=demand_row,
            prev_basin_volumes={},
            next_basin_volumes={},
            prev_basin_profiles={},
            next_basin_profiles={},
            defer_visibility=False,
            step_hours=float(self.system_config.dt_hours),
            pool_areas=pool_areas,
        )
        
        horizon = max(int(self.system_config.horizon_hours - step), 1)
        disturbance_forecast = self.observers.get_forecast(horizon=horizon, step_hours=float(self.system_config.dt_hours))
        
        upper_plan = self.upper_scheduler.solve(
            now=step,
            env_snapshot=observation,
            demand_state={"delivered_last_station_total": float(self.cumulative_last_station_flow)},
            available_units_map=self.available_units_map,
            disturbance_forecast=disturbance_forecast,
            lower_feedback=self.lower_feedback,
        )
        
        # Lower Controllers
        actions = {}
        upstream_selected_flows = {}
        transfer_bundles = {}
        
        for station_id in self.system_config.station_ids:
            station_model = self.flow_service.get_station_model(station_id, self.available_units_map[station_id])
            station_memory = self.station_memories[station_id]
            
            reference_flow = [float(f) for f in upper_plan.flow_refs[station_id]]
            reference_back_level = [float(f) for f in upper_plan.station_back_levels[station_id]]
            reference_front_level = [float(f) for f in upper_plan.station_front_levels[station_id]]
            reference_head = [float(f) for f in upper_plan.station_heads[station_id]]
            
            from .odd_dmpc.types import TransferBundle
            transfer_bundle = TransferBundle(
                station_id=station_id,
                reference_flow=reference_flow,
                reference_back_level=reference_back_level,
                reference_front_level=reference_front_level,
                reference_head=reference_head,
                active_unit_ids=station_memory.active_unit_ids[:],
                time_since_adjust=station_memory.time_since_adjust.copy(),
                time_since_switch=station_memory.time_since_switch.copy(),
                disturbance_estimate=self.observers.get_estimate(),
            )
            transfer_bundles[station_id] = transfer_bundle
            
            decision = self.supervisor.select_mode(
                station_id=station_id,
                env_snapshot=observation,
                upper_plan=upper_plan,
                station_model=station_model,
                station_memory=station_memory,
                available_unit_ids=self.available_units_map[station_id],
                force_reconfiguration=False,
                reference_flow=reference_flow[0],
                reference_back=reference_back_level[0],
                reference_front=reference_front_level[0],
            )
            
            ctx = StationControlContext(
                station_id=station_id,
                station_model=station_model,
                available_unit_ids=self.available_units_map[station_id],
                basin_levels=observation.basin_levels.copy(),
                basin_profiles={},
                pool_areas=observation.pool_areas.copy(),
                anchor_basin_levels=observation.anchor_basin_levels.copy(),
                boundary_nominal_flows={},
                current_back_level=observation.station_back_levels[station_id],
                current_front_level=observation.station_front_levels[station_id],
                current_head=observation.station_heads[station_id],
                upper_flow_refs={sid: tb.reference_flow for sid, tb in transfer_bundles.items()},
                flow_history={sid: self.station_flow_history[sid][:] for sid in self.station_flow_history},
                boundary_level_plan=pd.DataFrame(),
                start_time_hours=float(observation.time_hours),
                step_hours=float(self.system_config.dt_hours),
                demand_plan=self.odd_demand_plan,
            )
            
            action = self.local_controller.solve(
                mode=decision.mode,
                station_ctx=ctx,
                upstream_prediction=upstream_selected_flows,
                disturbance_forecast=disturbance_forecast,
                transfer_bundle=transfer_bundle,
                station_memory=station_memory,
            )
            
            actions[station_id] = action
            upstream_selected_flows[station_id] = float(action.selected_flow)
            
            # Update memory
            new_active_ids = []
            for uid, st in action.unit_status.items():
                if st == 1: new_active_ids.append(uid)
                if st != station_memory.unit_status.get(uid, 0):
                    station_memory.time_since_switch[uid] = 0
                else:
                    station_memory.time_since_switch[uid] += 1
                
                old_op = station_memory.unit_openings.get(uid, 0.0)
                new_op = action.unit_openings.get(uid, 0.0)
                if abs(new_op - old_op) > 0.0: # simplified threshold
                    station_memory.time_since_adjust[uid] = 0
                else:
                    station_memory.time_since_adjust[uid] += 1
                    
            station_memory.active_unit_ids = new_active_ids
            station_memory.unit_status = action.unit_status.copy()
            station_memory.unit_openings = action.unit_openings.copy()
            station_memory.last_selected_flow = float(action.selected_flow)
            station_memory.mode = action.mode
            
            self.station_flow_history[station_id].append(float(action.selected_flow))
            
            flow_min, flow_max = station_model.feasible_flow_range(observation.station_heads[station_id])
            self.lower_feedback.feasible_flow_ranges[station_id] = [flow_min, flow_max]
            self.lower_feedback.current_modes[station_id] = action.mode
            self.lower_feedback.plan_execution_errors[station_id] = float(action.selected_flow - reference_flow[0])

        self.cumulative_last_station_flow += float(actions[self.system_config.last_station_id].selected_flow) * float(self.system_config.dt_hours)

        # map to previous output format for test_mpc
        lower_res = {}
        for s in self.stations:
            action = actions[s.id]
            st_list = [action.unit_status.get(u, 0) for u in self.available_units_map[s.id]]
            op_list = [action.unit_openings.get(u, 0.0) for u in self.available_units_map[s.id]]
            eff_list = [0.0] * len(st_list) # mock effs
            lower_res[s.id] = {
                "status": [st_list],
                "openings": [op_list],
                "effs": [eff_list],
                "total_q": [action.selected_flow]
            }
            
        # format upper_res
        upper_res = {
            "q_planned": {sid: upper_plan.flow_refs[sid] for sid in self.system_config.station_ids},
            "z_planned": {sid: upper_plan.station_back_levels[sid] for sid in self.system_config.station_ids}
        }
            
        self.mpc_output = {"upper": upper_res, "lower": lower_res}
        
        commands = []
        return self.mpc_output
"""

# Replace on_optimization entirely
import ast
class FuncFinder(ast.NodeVisitor):
    def __init__(self):
        self.on_opt_node = None
    def visit_FunctionDef(self, node):
        if node.name == 'on_optimization':
            self.on_opt_node = node
        self.generic_visit(node)

tree = ast.parse(content)
finder = FuncFinder()
finder.visit(tree)

lines = content.split('\n')
if finder.on_opt_node:
    start = finder.on_opt_node.lineno - 1
    # find end of function
    end = start
    while end < len(lines):
        if end > start and lines[end].startswith('    def '):
            break
        end += 1
    
    # We replace from start to end
    new_content = '\n'.join(lines[:start]) + '\n' + lazy_init_code + '\n' + on_opt_code + '\n' + '\n'.join(lines[end:])
    
    with open("custom-agent/pump/scheduling/pump_scheduling_agent.py", "w") as f:
        f.write(new_content)
    print("Successfully replaced on_optimization!")
else:
    print("Could not find on_optimization")

