import pandas as pd
import numpy as np
import os
import math
import json
import yaml
import warnings
from scipy.optimize import minimize
from scipy.spatial import Delaunay
from scipy.interpolate import LinearNDInterpolator
from itertools import product
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression

# Suppress warnings
warnings.filterwarnings('ignore')

from pump_unit import PumpUnit


def optimize_single_case(total_Q, target_H, units, rho, g):
    avail_units = [u for u in units if u.h_min <= target_H <= u.h_max]
    n_avail = len(avail_units)
    
    if n_avail == 0: 
        return None, None

    best_eff = -float('inf')
    best_details = None
    found_solution = False

    for state in product([0, 1], repeat=n_avail):
        if sum(state) == 0: continue

        active_indices = [i for i, s in enumerate(state) if s == 1]
        active_units = [avail_units[i] for i in active_indices]
        
        sum_q_min = sum([u.q_min for u in active_units])
        sum_q_max = sum([u.q_max for u in active_units])
        
        if not (sum_q_min <= total_Q <= sum_q_max): 
            continue

        num_active = len(active_units)
        x0 = [total_Q / num_active] * num_active
        cons = ({'type': 'eq', 'fun': lambda x: sum(x) - total_Q})
        bnds = [(u.q_min, u.q_max) for u in active_units]

        def objective(x):
            effs = []
            for i, q_val in enumerate(x):
                unit = active_units[i]
                if not unit.is_feasible(q_val, target_H): return 1e6
                effs.append(unit.predict_efficiency(q_val, target_H))
            return -1 * (sum(effs) / len(effs))

        sol = minimize(objective, x0, method='SLSQP', bounds=bnds, constraints=cons)

        if sol.success:
            avg_eff = -sol.fun
            if 0 < avg_eff <= 100:
                if avg_eff > best_eff:
                    best_eff = avg_eff
                    found_solution = True
                    details = {}
                    for u in units:
                        details[u.name] = {"Status": 0, "Q": 0, "Eff": 0, "Open": 0}
                    for i, q_val in enumerate(sol.x):
                        u = active_units[i]
                        details[u.name] = {
                            "Status": 1,
                            "Q": q_val, 
                            "Eff": u.predict_efficiency(q_val, target_H),
                            "Open": u.predict_opening(q_val, target_H)
                        }
                    best_details = details

    if not found_solution:
        return None, None
    
    return best_eff, best_details


def load_specific_station_data(station_config, data_dir, target_unit_names):
    """
    Loads data only for the specified units in the given station configuration.
    Supports optional q_min/q_max override from config.
    """
    station_name = station_config["name"]
    
    units = []
    
    # Build a lookup dict for unit config
    unit_config_map = {}
    for u_cfg in station_config.get("units", []):
        unit_config_map[u_cfg["name"]] = u_cfg
        
    import pandas as pd
    for sheet in target_unit_names:
        if sheet not in unit_config_map:
            print(f"  [!] Warning: Unit '{sheet}' missing in station config, skipping.")
            continue
            
        u_cfg = unit_config_map[sheet]
        
        if "table_e" not in u_cfg or "table_r" not in u_cfg:
            print(f"  [!] Warning: Unit '{sheet}' missing table_e or table_r in config, skipping.")
            continue
            
        df_e = pd.DataFrame(u_cfg["table_e"]["rows"], columns=u_cfg["table_e"]["columns"])
        df_r = pd.DataFrame(u_cfg["table_r"]["rows"], columns=u_cfg["table_r"]["columns"])
        
        u = PumpUnit(sheet, df_e, df_r)
        
        # Override q_min/q_max from config if provided
        if "q_min" in u_cfg:
            u.q_min = u_cfg["q_min"]
        if "q_max" in u_cfg:
            u.q_max = u_cfg["q_max"]
            
        units.append(u)
        print(f"  [√] Loaded Unit '{sheet}' -> Q range: [{u.q_min:.2f}, {u.q_max:.2f}], H range: [{u.h_min:.2f}, {u.h_max:.2f}]")
        
    return units


def generate_flow_depart(station_id, units, step_q=1.0, step_h=0.1, rho=1000, g=9.81):
    """
    Generate flow depart table dynamically based on station configuration and memory PumpUnit objects.
    """
    import math
    import numpy as np
    import pandas as pd
    
    print(f"\n{'='*10} Starting Flow Depart Calculation {'='*10}")
    print(f"Station ID: {station_id}")
    
    if not units:
        print("Error: No valid units provided. Aborting process.")
        return None
        
    target_unit_names = [u.name for u in units]
    print(f"Target Units: {', '.join(target_unit_names)}")
    
    # Calculate Range specifically for the loaded units
    global_h_min = min([u.h_min for u in units])
    global_h_max = max([u.h_max for u in units])
    global_q_min = min([u.q_min for u in units]) 
    global_q_max = sum([u.q_max for u in units])

    calc_q_min = math.floor(global_q_min)
    calc_q_max = math.ceil(global_q_max)
    calc_h_min = math.floor(global_h_min * 10) / 10.0 
    calc_h_max = math.ceil(global_h_max * 10) / 10.0 
    
    q_vals = np.arange(calc_q_min, calc_q_max + 1e-5, step_q)
    h_vals = np.arange(calc_h_min, calc_h_max + 1e-5, step_h)
    
    total_cases = len(q_vals) * len(h_vals)
    print(f"\nCalculated Grid Range:")
    print(f"  Q Range [{calc_q_min}, {calc_q_max}] step {step_q}")
    print(f"  H Range [{calc_h_min}, {calc_h_max}] step {step_h}")
    print(f"  Total conditions to evaluate: {total_cases}")
    
    # Batch calculation
    results = []
    count = 0
    
    for h in h_vals:
        for q in q_vals:
            count += 1
            if count % 100 == 0: 
                print(f"Progress: {count}/{total_cases}...", end='\r')
            
            avg_eff, details = optimize_single_case(q, h, units, rho, g)
            
            row = {
                "总流量(m³/s)": round(q, 3),
                "扬程(m)": round(h, 3),
                "平均效率(%)": round(avg_eff, 4) if avg_eff else "-"
            }
            
            for idx, unit_obj in enumerate(units):
                prefix = f"泵_{unit_obj.name}"
                sheet_name = unit_obj.name
                
                if details and sheet_name in details:
                    d = details[sheet_name]
                    if d['Status'] == 1:
                        p_kw = rho * g * d['Q'] * h / 1000.0
                        row[f"{prefix}_状态"] = "true"
                        row[f"{prefix}_流量"] = round(d['Q'], 4)
                        row[f"{prefix}_有用功(kW)"] = round(p_kw, 4)
                        row[f"{prefix}_效率(%)"] = round(d['Eff'], 2)
                        row[f"{prefix}_开度"] = round(d['Open'], 2)
                    else:
                        row[f"{prefix}_状态"] = "false"
                        row[f"{prefix}_流量"] = "-"
                        row[f"{prefix}_有用功(kW)"] = "-"
                        row[f"{prefix}_效率(%)"] = "-"
                        row[f"{prefix}_开度"] = "-"
                else:
                    row[f"{prefix}_状态"] = "false"
                    row[f"{prefix}_流量"] = "-"
                    row[f"{prefix}_有用功(kW)"] = "-"
                    row[f"{prefix}_效率(%)"] = "-"
                    row[f"{prefix}_开度"] = "-"
            
            results.append(row)
            
    df_res = pd.DataFrame(results)
    print("\nFlow depart completed.")
    
    return df_res

