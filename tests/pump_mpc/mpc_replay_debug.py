import json
import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize_scalar

REPO_ROOT = Path(__file__).resolve().parents[2]
PUMP_SCHEDULING_DIR = REPO_ROOT / "custom-agent" / "pump" / "scheduling"
sys.path.insert(0, str(PUMP_SCHEDULING_DIR))

from pump_scheduling_agent import PumpCentralSchedulingAgent, PumpStation, CanalPool
from flow_depart import load_specific_station_data

def angle_to_flow(unit, target_angle, H):
    if target_angle == 0.0 or target_angle == "-":
        return 0.0
    def obj(q):
        pred_angle = unit.predict_opening(q, H)
        # Handle nan gracefully if interpolation goes out of bounds
        if np.isnan(pred_angle):
            return 1e6
        return (pred_angle - target_angle)**2
    res = minimize_scalar(obj, bounds=(unit.q_min, unit.q_max), method='bounded')
    return res.x if res.success else 0.0

class MockStorageModel:
    def __init__(self, pools, stations, db_config):
        self.pools = pools
        self.stations = stations
        self.levels = [stations[0].init_up, stations[1].init_up, stations[2].init_up]
        
        # Load pump units for physical inverse simulation
        self.units = {}
        for s in db_config['stations']:
            units_loaded = load_specific_station_data(s, 'data', [u['name'] for u in s['units']])
            self.units[s['id']] = units_loaded
        
    def simulate_flow(self, lower_res, current_levels):
        # Inverse simulation: Angle, Head -> actual Q
        actual_flows = {1: 0.0, 2: 0.0, 3: 0.0}
        actual_effs = {1: [], 2: [], 3: []}
        actual_angles = {1: [], 2: [], 3: []}
        
        for sid in [1, 2, 3]:
            # Current head (simplified, assuming fixed downstream level for simplicity)
            H = current_levels[sid-1] - self.stations[sid-1].init_down 
            if sid == 1: H = current_levels[0] - self.stations[0].init_down
            if sid == 2: H = current_levels[1] - self.stations[1].init_down
            if sid == 3: H = current_levels[2] - self.stations[2].init_down

            status = lower_res[sid]['status'][0]
            openings = lower_res[sid]['openings'][0]
            
            sq = 0.0
            effs = []
            angles = []
            for i, st in enumerate(status):
                if st == 1:
                    q = angle_to_flow(self.units[sid][i], openings[i], H)
                    sq += q
                    eff = self.units[sid][i].predict_efficiency(q, H)
                    effs.append(eff)
                    angles.append(openings[i])
                else:
                    effs.append(0.0)
                    angles.append(0.0)
            actual_flows[sid] = sq
            actual_effs[sid] = effs
            actual_angles[sid] = angles
            
        return actual_flows, actual_effs, actual_angles

    def step(self, flows, dt=3600):
        z1 = self.levels[0]
        z2 = self.pools[0].predict_level(self.levels[1], flows[1], flows[2], 0, dt)
        z3 = self.pools[1].predict_level(self.levels[2], flows[2], flows[3], 0, dt)
        self.levels = [z1, z2, z3]
        return self.levels

class MockContext:
    def __init__(self):
        self.biz_scene_instance_id = "test_scene"

class MockClient:
    def __init__(self):
        self.state_manager = self
    def send_command(self, req): pass
    def subscribe(self, topic): pass
    def init_task(self, ctx, agents): pass
    def add_local_agent(self, agent): pass

def plot_step(step, steps, results_hist, predictions, db_config):
    fig = plt.figure(figsize=(20, 16))
    
    # Grid layout: 
    # Row 1: Flow (Upper MPC), Level (Upper/Actual)
    # Row 2: Efficiency (Lower MPC)
    # Row 3: Angles St1 & St2
    # Row 4: Angles St3
    
    # 1. Flow (Upper and Lower MPC)
    ax1 = plt.subplot(4, 2, 1)
    ax1.plot(range(step), results_hist['q1'], 'b-', label='Act Q1')
    ax1.plot(range(step), results_hist['q2'], 'g-', label='Act Q2')
    ax1.plot(range(step), results_hist['q3'], 'r-', label='Act Q3')
    
    if predictions['upper']:
        time_u = range(step, step + len(predictions['upper']['q_planned'][1]))
        ax1.plot(time_u, predictions['upper']['q_planned'][1], 'b--', alpha=0.5, label='Up Q1')
        ax1.plot(time_u, predictions['upper']['q_planned'][2], 'g--', alpha=0.5, label='Up Q2')
        ax1.plot(time_u, predictions['upper']['q_planned'][3], 'r--', alpha=0.5, label='Up Q3')
        
    if predictions.get('lower'):
        time_l = range(step, step + len(predictions['lower'][1]['total_q']))
        ax1.plot(time_l, predictions['lower'][1]['total_q'], 'b.-', alpha=0.7, label='Low Q1')
        ax1.plot(time_l, predictions['lower'][2]['total_q'], 'g.-', alpha=0.7, label='Low Q2')
        ax1.plot(time_l, predictions['lower'][3]['total_q'], 'r.-', alpha=0.7, label='Low Q3')
        
    ax1.set_xlim(0, steps + 10)
    ax1.set_ylabel('Flow (m³/s)')
    ax1.set_title('Flow Tracking (Upper vs Lower MPC)')
    ax1.axhline(80, color='k', linestyle=':', label='Target Q3=80')
    ax1.legend(loc='upper right', fontsize=8, ncol=2)
    
    # 2. Levels
    ax2 = plt.subplot(4, 2, 2)
    ax2.plot(range(step), results_hist['z2'], 'b-', label='Act Level 2')
    ax2.plot(range(step), results_hist['z3'], 'g-', label='Act Level 3')
    
    if predictions['upper']:
        time_u = range(step, step + len(predictions['upper']['z_planned'][1]))
        ax2.plot(time_u, predictions['upper']['z_planned'][1], 'b--', alpha=0.5, label='Up Level 2')
        ax2.plot(time_u, predictions['upper']['z_planned'][2], 'g--', alpha=0.5, label='Up Level 3')
        
    if predictions.get('pred_z_lower') and len(predictions['pred_z_lower'][2]) > 0:
        time_l = range(step, step + len(predictions['pred_z_lower'][2]))
        ax2.plot(time_l, predictions['pred_z_lower'][2], 'b.-', alpha=0.7, label='Low Level 2')
        ax2.plot(time_l, predictions['pred_z_lower'][3], 'g.-', alpha=0.7, label='Low Level 3')
        
    ax2.set_xlim(0, steps + 10)
    ax2.set_ylabel('Level (m)')
    ax2.set_title('Level Tracking (Upper vs Lower MPC)')
    ax2.legend(loc='upper right', fontsize=8, ncol=2)
    
    # 3. Efficiency
    ax3 = plt.subplot(4, 2, 3)
    ax3.set_title("Lower MPC Average Unit Efficiency Tracking")
    ax3.set_ylabel("Efficiency (%)")
    
    # Averages over units
    eff_hist1 = [np.mean([e for e in h if e>0]) if any(e>0 for e in h) else 0 for h in results_hist['eff1']]
    eff_hist2 = [np.mean([e for e in h if e>0]) if any(e>0 for e in h) else 0 for h in results_hist['eff2']]
    eff_hist3 = [np.mean([e for e in h if e>0]) if any(e>0 for e in h) else 0 for h in results_hist['eff3']]
    
    ax3.plot(range(step), eff_hist1, 'b-', label='Act Eff1')
    ax3.plot(range(step), eff_hist2, 'g-', label='Act Eff2')
    ax3.plot(range(step), eff_hist3, 'r-', label='Act Eff3')
    
    if predictions['lower']:
        time_l = range(step, step + len(predictions['lower'][1]['effs']))
        pred_eff1 = [np.mean([e for e in p if e>0]) if any(e>0 for e in p) else 0 for p in predictions['lower'][1]['effs']]
        pred_eff2 = [np.mean([e for e in p if e>0]) if any(e>0 for e in p) else 0 for p in predictions['lower'][2]['effs']]
        pred_eff3 = [np.mean([e for e in p if e>0]) if any(e>0 for e in p) else 0 for p in predictions['lower'][3]['effs']]
        ax3.plot(time_l, pred_eff1, 'b--', alpha=0.5)
        ax3.plot(time_l, pred_eff2, 'g--', alpha=0.5)
        ax3.plot(time_l, pred_eff3, 'r--', alpha=0.5)
    ax3.set_xlim(0, steps + 10)
    ax3.legend()

    # 4. Blade Angles
    colors = ['c', 'm', 'y', 'k', 'orange']
    # Station 1
    ax4 = plt.subplot(4, 2, 5)
    ax4.set_title("Station 1 Angles")
    for u in range(5):
        hist_ang = [h[u] for h in results_hist['ang1']]
        ax4.plot(range(step), hist_ang, color=colors[u], label=f'U{u+1}')
        if predictions['lower']:
            pred_ang = [p[u] for p in predictions['lower'][1]['openings']]
            time_l = range(step, step + len(pred_ang))
            ax4.plot(time_l, pred_ang, color=colors[u], linestyle='--')
    ax4.set_xlim(0, steps + 10)
    ax4.legend()
    
    # Station 2
    ax5 = plt.subplot(4, 2, 6)
    ax5.set_title("Station 2 Angles")
    for u in range(4):
        hist_ang = [h[u] for h in results_hist['ang2']]
        ax5.plot(range(step), hist_ang, color=colors[u], label=f'U{u+1}')
        if predictions['lower']:
            pred_ang = [p[u] for p in predictions['lower'][2]['openings']]
            time_l = range(step, step + len(pred_ang))
            ax5.plot(time_l, pred_ang, color=colors[u], linestyle='--')
    ax5.set_xlim(0, steps + 10)
    ax5.legend()
    
    # Station 3
    ax6 = plt.subplot(4, 2, 7)
    ax6.set_title("Station 3 Angles")
    for u in range(4):
        hist_ang = [h[u] for h in results_hist['ang3']]
        ax6.plot(range(step), hist_ang, color=colors[u], label=f'U{u+1}')
        if predictions['lower']:
            pred_ang = [p[u] for p in predictions['lower'][3]['openings']]
            time_l = range(step, step + len(pred_ang))
            ax6.plot(time_l, pred_ang, color=colors[u], linestyle='--')
    ax6.set_xlim(0, steps + 10)
    ax6.legend()
    
    plt.tight_layout()
    os.makedirs('output/frames', exist_ok=True)
    plt.savefig(f'output/frames/step_{step:03d}.png')
    plt.close(fig)

def main():
    os.chdir(PUMP_SCHEDULING_DIR)
    with open('data/config.json') as f: db_config = json.load(f)
    print("Initializing test MPC...")
    
    agent = PumpCentralSchedulingAgent(
        sim_coordination_client=MockClient(),
        agent_id="test_id", agent_code="test_code", agent_type="CENTRAL",
        agent_name="Test Agent", context=MockContext(),
        hydros_cluster_id="local", hydros_node_id="local"
    )
    # Override methods to avoid noisy SDK logs
    agent.control_command_dispatcher.send_command = lambda cmd: None
    agent.control_command_dispatcher.build_station_target_value_request = lambda **kwargs: "mock_request"
    
    # Init logic
    agent._init_pump_system()
    
    # Storage simulation environment
    env = MockStorageModel(agent.pools, agent.stations, db_config)
    
    results_hist = {
        'z2': [], 'z3': [], 'q1': [], 'q2': [], 'q3': [], 
        'eff1': [], 'eff2': [], 'eff3': [],
        'ang1': [], 'ang2': [], 'ang3': []
    }
    
    steps = 72
    dt = 3600
    
    for step in range(steps):
        print(f"\n--- Simulating Step {step} ---")
        out = agent.on_optimization(step)
        
        # Upper and Lower predictions
        upper_res = agent.mpc_output['upper']
        lower_res = agent.mpc_output['lower']
        
        # Simulate physics based on lower_res angles
        actual_flows, actual_effs, actual_angles = env.simulate_flow(lower_res, env.levels)
        
        for sid in [1, 2, 3]:
            uq = upper_res['q_planned'][sid][0] if upper_res and sid in upper_res['q_planned'] else 0.0
            lq = lower_res[sid]['total_q'][0] if lower_res and sid in lower_res else 0.0
            aq = actual_flows.get(sid, 0.0)
            if step == 29: print(f"[Debug] SID {sid} angles: {lower_res[sid]['openings'][0]}, states: {lower_res[sid]['status'][0]}, actual env qs: {actual_flows.get(sid)}")
            print(f"  Station {sid} | Upper MPC: {uq:>6.2f} m³/s | Lower MPC: {lq:>6.2f} m³/s | Actual Env: {aq:>6.2f} m³/s")
        
        # Env steps (Levels updating)
        levels = env.step(actual_flows, dt)
        
        # Agent reads actual
        agent.on_next(levels[1:], list(actual_flows.values()), step)
        
        # Log history
        results_hist['q1'].append(actual_flows[1])
        results_hist['q2'].append(actual_flows[2])
        results_hist['q3'].append(actual_flows[3])
        results_hist['z2'].append(levels[1])
        results_hist['z3'].append(levels[2])
        
        results_hist['eff1'].append(actual_effs[1])
        results_hist['eff2'].append(actual_effs[2])
        results_hist['eff3'].append(actual_effs[3])
        
        results_hist['ang1'].append(actual_angles[1])
        results_hist['ang2'].append(actual_angles[2])
        results_hist['ang3'].append(actual_angles[3])
        
        # Calculate Lower MPC predicted levels
        pred_z2_lower = []
        pred_z3_lower = []
        if lower_res and 1 in lower_res:
            temp_z2 = levels[1]
            temp_z3 = levels[2]
            horizon_l = len(lower_res[1]['total_q'])
            for t in range(horizon_l):
                q1 = lower_res[1]['total_q'][t]
                q2 = lower_res[2]['total_q'][t]
                q3 = lower_res[3]['total_q'][t]
                
                temp_z2 = env.pools[0].predict_level(temp_z2, q1, q2, 0, dt)
                temp_z3 = env.pools[1].predict_level(temp_z3, q2, q3, 0, dt)
                
                pred_z2_lower.append(temp_z2)
                pred_z3_lower.append(temp_z3)
                
        # Plot Frame
        predictions = {
            'upper': upper_res, 
            'lower': lower_res,
            'pred_z_lower': {2: pred_z2_lower, 3: pred_z3_lower}
        }
        plot_step(step + 1, steps, results_hist, predictions, db_config)
        
    print(f"\nSimulation complete. {steps} frames plotted in output/frames/")

if __name__ == "__main__":
    main()
