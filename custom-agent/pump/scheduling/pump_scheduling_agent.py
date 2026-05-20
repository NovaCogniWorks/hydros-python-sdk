"""
中央调度智能体示例

本模块展示了如何基于 CentralSchedulingAgent 基类实现一个具体的中央调度智能体。
该智能体会在滚动时界（Rolling Horizon）上执行模型预测控制（MPC）优化。
"""

import logging
import os
import sys
import json
from scipy.optimize import differential_evolution
import numpy as np
import pandas as pd
from typing import Optional, List, Dict, Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    setup_logging, SimCoordinationClient, HydroAgentFactory, MultiAgentCallback,
    load_env_config, load_agent_config, ErrorCodes, handle_agent_errors,
    DeviceValueTypeEnum, HydroObjectType
)
from hydros_agent_sdk.agents import CentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import *
from hydros_agent_sdk.protocol.models import *

from flow_depart import generate_flow_depart

class PumpStation:
    def __init__(self, id, name):
        self.id = id; self.name = name; self.units = []
        self.init_up = 0.0; self.init_down = 0.0
        self.current_up = 0.0; self.current_down = 0.0
        self.current_flow = 0.0

class CanalPool:
    def __init__(self, id, area):
        self.id = id; self.area = area
    def predict_level(self, z0, q_in, q_out, q_disturb, dt):
        return z0 + (q_in - q_out + q_disturb) * dt / self.area

class DisturbanceObserver:
    def __init__(self, gain=0.35, smoothing=0.7):
        self.gain = gain; self.smoothing = smoothing
        self.d_hat = 0.0
    def update(self, q_actual, q_planned):
        self.d_hat = self.smoothing * self.d_hat + self.gain * (q_actual - q_planned)

class UnitMemory:
    def __init__(self, size, init_status=None, init_openings=None, config=None):
        init_age = 999
        if config and 'runtime' in config:
            init_age = config['runtime']['lower_controller'].get('station_memory_init_age', 999)
        self.last_act = [-init_age] * size
        self.last_switch = [-init_age] * size
        self.status = init_status if init_status else [1]*size
        self.openings = init_openings if init_openings else [0.0]*size
        
    def update(self, idx, current_step, switch=False, adjust=False, status=None, opening=None):
        if switch: self.last_switch[idx] = current_step
        if adjust: self.last_act[idx] = current_step
        if status is not None: self.status[idx] = status
        if opening is not None: self.openings[idx] = opening

class UpperMPC:
    def __init__(self, pools, tables, config):
        self.pools = pools; self.tables = tables
        self.target_q = config.get("scheduling", {}).get("target_avg_flow_last_station", 80)
        self.horizon = config.get("scheduling", {}).get("horizon_hours", 72)
        self.integral_error = 0.0
        
    def solve(self, cur_levels, demand_plan=None, observers=None, dt=3600):
        out = {"q_planned": {1:[], 2:[], 3:[]}, "z_planned": {1:[], 2:[]}}
        z = list(cur_levels)
        eff_q = {1: np.array(self.tables[1]['总流量(m³/s)'].dropna().unique()) if not self.tables[1].empty else np.array([0]),
                 2: np.array(self.tables[2]['总流量(m³/s)'].dropna().unique()) if not self.tables[2].empty else np.array([0]),
                 3: np.array(self.tables[3]['总流量(m³/s)'].dropna().unique()) if not self.tables[3].empty else np.array([0])}
        
        eff_target = self.target_q + self.integral_error
        last_q3 = min(eff_q[3], key=lambda x:abs(x-eff_target)) if len(eff_q[3]) else eff_target
        
        for t in range(self.horizon):
            d1 = demand_plan['station1-station2'].iloc[t] if demand_plan is not None and t < len(demand_plan) else 0
            d2 = demand_plan['station2-station3'].iloc[t] if demand_plan is not None and t < len(demand_plan) else 0
            
            q3 = last_q3
            q2 = min(eff_q[2], key=lambda x:abs(x-(q3+d2))) if len(eff_q[2]) else q3+d2
            q1 = min(eff_q[1], key=lambda x:abs(x-(q2+d1))) if len(eff_q[1]) else q2+d1
            
            d_hat1 = observers[1].d_hat if observers else 0
            d_hat2 = observers[2].d_hat if observers else 0
            
            z[0] = self.pools[0].predict_level(z[0], q1, q2, -d1 + d_hat1, dt)
            z[1] = self.pools[1].predict_level(z[1], q2, q3, -d2 + d_hat2, dt)
            
            out["q_planned"][1].append(q1); out["q_planned"][2].append(q2); out["q_planned"][3].append(q3)
            out["z_planned"][1].append(z[0]); out["z_planned"][2].append(z[1])
        return out

class LowerMPC:
    def __init__(self, st_id, units, config):
        self.st_id = st_id
        self.units = units
        self.config = config
        
        st_config = next((s for s in config['stations'] if s['id'] == st_id), None)
        init_status = [1] * len(units)
        # 默认开度取各机组物理角度中值，避免从 0.0 启动造成插值越界
        init_openings = [(u.angle_min + u.angle_max) / 2.0 for u in units]
        if st_config:
            init_status = [u.get('init_status', 1) for u in st_config['units']]
            cfg_openings = [u.get('init_opening', None) for u in st_config['units']]
            init_openings = [
                cfg_openings[i] if cfg_openings[i] is not None
                else (units[i].angle_min + units[i].angle_max) / 2.0
                for i in range(len(units))
            ]
            
        self.memory = UnitMemory(len(units), init_status, init_openings, config)
        
    def solve(self, ref_q_seq, ref_h_seq, step):
        horizon = len(ref_q_seq)
        N = len(self.units)
        
        # 1. 预计算在离散叶片角上的预测流量，对于相同的H只算一次以提升速度
        unit_angles = []
        for u in self.units:
            unit_angles.append(np.linspace(u.angle_min, u.angle_max, 25))
            
        pre_flows = np.zeros((horizon, N, 25))
        unique_h = np.unique(ref_h_seq)
        h_to_flow = {}
        for h in unique_h:
            fm_h = []
            for i, u in enumerate(self.units):
                fm_h.append([u.predict_flow(a, h) for a in unit_angles[i]])
            h_to_flow[h] = fm_h
            
        for t in range(horizon):
            h_val = ref_h_seq[t]
            for i in range(N):
                pre_flows[t, i, :] = h_to_flow[h_val][i]
                    
        # 2. 从配置获取惩罚权重
        W_q = self.config['runtime']['lower_controller'].get('lower_flow_weight', 3.0)
        W_sw = self.config['runtime']['lower_controller'].get('lower_switch_weight', 50.0)
        W_adj = self.config['runtime']['lower_controller'].get('lower_adjust_count_weight', 10.0)
        
        sim_status = list(self.memory.status)
        sim_openings = list(self.memory.openings)
        sim_last_act = list(self.memory.last_act)
        sim_last_switch = list(self.memory.last_switch)
        
        out_status = []; out_openings = []; out_effs = []; out_total = []
        
        for t in range(horizon):
            c_st = step + t
            ref_q = ref_q_seq[t]
            h_val = ref_h_seq[t]
            
            def obj_t(x):
                s_t = np.round(x[:N]).astype(int)
                a_t = x[N:]
                cost = 0.0
                q_total = 0.0
                
                for i in range(N):
                    # 启停惩罚衰减：反比惩罚，上次动作越远惩罚越轻
                    if s_t[i] != sim_status[i]:
                        dt = max(1, c_st - sim_last_switch[i])
                        cost += W_sw / dt
                        
                    if s_t[i] == 1:
                        # 叶片角调节惩罚衰减：只有调整幅度超过阈值0.5视作换挡
                        if abs(a_t[i] - sim_openings[i]) > 0.5:
                            dt = max(1, c_st - sim_last_act[i])
                            cost += W_adj / dt
                            
                        # 在预计算的特征表面快速内插插值获取流量
                        q_total += np.interp(a_t[i], unit_angles[i], pre_flows[t, i, :])
                        
                cost += W_q * (q_total - ref_q)**2
                return cost
                
            # 缩小搜寻空间到单步的 N 个变量，实现极速贪心解，根据各机组实际物理范围裁减边界
            bounds_t = [(0, 1)] * N + [(u.angle_min, u.angle_max) for u in self.units]
            res_t = differential_evolution(obj_t, bounds_t, maxiter=15, popsize=4, mutation=(0.5, 1.0), recombination=0.7)
            
            best_s = np.round(res_t.x[:N]).astype(int)
            best_a = res_t.x[N:]
            
            # 单步解确定后，立即坍缩（坍塌）并更新仿真记忆，作为下一步的基础状态
            q_tot = 0.0
            eff_t = []
            for i in range(N):
                if best_s[i] != sim_status[i]:
                    sim_last_switch[i] = c_st
                    sim_status[i] = best_s[i]
                    
                if best_s[i] == 1:
                    # 惩罚判断：幅度超过阈值才记录为一次"换挡"
                    if abs(best_a[i] - sim_openings[i]) > 0.5:
                        sim_last_act[i] = c_st
                    # 【修复】坍缩时无条件跟踪实际角度，不受幅度门槛约束
                    # 否则初始 0.0 永远不更新，优化器陷入假稳定态导致 0 流量
                    sim_openings[i] = best_a[i]
                    # 记录真实流量和效率
                    q = np.interp(best_a[i], unit_angles[i], pre_flows[t, i, :])
                    q_tot += q
                    e = self.units[i].predict_efficiency(q, h_val)
                    eff_t.append(float(e))
                else:
                    best_a[i] = 0.0
                    sim_openings[i] = 0.0
                    eff_t.append(0.0)
                    
            out_status.append(best_s.tolist())
            out_openings.append(best_a.tolist())
            out_effs.append(eff_t)
            out_total.append(q_tot)
            
        return {"status": out_status, "openings": out_openings, "effs": out_effs, "total_q": out_total}

logger = logging.getLogger(__name__)


class PumpCentralSchedulingAgent(CentralSchedulingAgent):
    """
    中央调度智能体的具体实现。

    该智能体的主要功能包括：
    1. 加载水网拓扑结构
    2. 初始化 MPC 优化模型
    3. 通过 MQTT 订阅现地实时指标（Field Metrics）
    4. 执行滚动时界（MPC）优化逻辑
    5. 为其他智能体（如泵站、闸门）生成调度控制指令
    """

    def __init__(
        self,
        sim_coordination_client,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        optimization_horizon: int = 10,
        **kwargs
    ):
        """
        初始化中央调度智能体。

        参数:
            optimization_horizon: 优化步长（每隔多少个 Tick 执行一次优化）
        """
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            optimization_horizon=optimization_horizon,
            **kwargs
        )

        logger.info(f"中央调度智能体实例已创建: {agent_id}")

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化智能体。该方法在任务启动时被调用。
        """
        logger.info(f"正在初始化智能体: {self.agent_id}")

        try:
            # 1. 加载智能体配置 (从 agent.properties)
            self.load_agent_configuration(request)

            # 2. 初始化梯级泵站和优化模型 (模拟)
            self._init_pump_system()

            # 3. 订阅现地指标（从环境配置 env.properties 获取基础主题并渲染变量）
            env_config = load_env_config()
            base_metrics_topic = env_config.get('metrics_topic')
            if base_metrics_topic:
                # 手动替换 {hydros_cluster_id} 变量
                cluster_id = env_config.get('hydros_cluster_id', 'default_cluster_25')
                base_metrics_topic = base_metrics_topic.replace('{hydros_cluster_id}', cluster_id)

                # 从上下文获取业务场景实例 ID (biz_scene_instance_id)
                task_id = self.context.biz_scene_instance_id

                # 拼接完整主题实现任务隔离：base_topic/task_id
                full_metrics_topic = f"{base_metrics_topic.rstrip('/')}/{task_id}"

                logger.info(f"订阅渲染后的现地数据主题: {full_metrics_topic}")
                self.subscribe_to_field_metrics(full_metrics_topic)

            # 4. 在状态管理器中注册
            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)

            # 5. 启动 agent command 客户端，后面就能直接发指令
            self._start_agent_command_client()

            logger.info(f"中央调度智能体初始化成功: {self.agent_id}")

            # 将智能体状态更新为 ACTIVE (活动)
            object.__setattr__(self, 'agent_status', AgentStatus.ACTIVE)

            return SimTaskInitResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                created_agent_instances=[self],
                managed_top_objects={},
                broadcast=False
            )
        except Exception:
            # 初始化失败就把客户端收掉，别把半拉资源留住
            self._shutdown_agent_command_client()
            raise

    def _init_pump_system(self):
        logger.info("初始化梯级泵站、外生变量、MPC调度器...")
        with open('data/config.json', 'r') as f:
            self._db_config = json.load(f)
            
        self.stations = []
        for s in self._db_config['stations']:
            st = PumpStation(s['id'], s['name'])
            st.init_up = s['init_level_up']
            st.init_down = s['init_level_down']
            st.current_up = st.init_up
            st.current_down = st.init_down
            st.units = [u['name'] for u in s['units']]
            self.stations.append(st)
            
        self.pools = [CanalPool(p['id'], p['area']) for p in self._db_config['canal_pools']]
        
        self.tables = {}
        for s in self.stations:
            df = generate_flow_depart(s.id, s.units, 'data/config.json')
            self.tables[s.id] = df
            
        try:
            self.demand_plan = pd.read_excel('data/inflow-demand-plan.xlsx', sheet_name=0)
        except Exception as e:
            logger.warning(f"未能加载需求计划，将被忽略: {e}")
            self.demand_plan = None
        
        # 扰动观察器对象
        self.observers = {
            1: DisturbanceObserver(self._db_config['runtime']['observer']['observer_gain'], self._db_config['runtime']['observer']['observer_smoothing']),
            2: DisturbanceObserver(self._db_config['runtime']['observer']['observer_gain'], self._db_config['runtime']['observer']['observer_smoothing'])
        }
        
        self.unit_objs = {}
        for s in self._db_config['stations']:
            from flow_depart import load_specific_station_data
            self.unit_objs[s['id']] = load_specific_station_data(s, 'data', [u['name'] for u in s['units']])
        
        # 上层和下层MPC对象
        self.upper_mpc = UpperMPC(self.pools, self.tables, self._db_config)
        self.lower_mpcs = {}
        for s in self.stations:
            self.lower_mpcs[s.id] = LowerMPC(s.id, self.unit_objs[s.id], self._db_config)
            
        self.mpc_output = {}

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        logger.info(f"--- 第 {step} 步：开始执行分布分层 MPC 滚动优化 ---")

        # ============= 上层 MPC 优化 =============
        # z_planned[1] = Pool1（S1出水侧，≈S1.current_up）
        # z_planned[2] = Pool2（S2出水侧，≈S2.current_up）
        # 必须传 [S1.current_up, S2.current_up]，否则水位初始化偏移一位
        cur_levels = [self.stations[0].current_up, self.stations[1].current_up]
        upper_res = self.upper_mpc.solve(cur_levels, self.demand_plan, self.observers, dt=3600)
        
        # ============= 下层 分布式 MPC 优化 =============
        lower_res = {}
        commands = []
        for s in self.stations:
            # 读取上层目标，形成序列
            horizon_lower = 10
            ref_q_seq = upper_res["q_planned"][s.id][:horizon_lower]
            
            # 逐站计算预测扬程序列 H = 出水侧水位 - 进水侧水位
            # S1: 从固定低位水源(current_down≈12.5m) 压入 Pool1(z_planned[1]≈14.5m)
            #     H = Pool1 - source = z_planned[1] - current_down
            # S2: 从 Pool1(z_planned[1]) 压入 Pool2(z_planned[2])，两侧均动态
            #     H = Pool2 - Pool1 = z_planned[2] - z_planned[1]
            # S3: 从 Pool2(z_planned[2]≈20.5m) 压入固定高位出水库(current_up≈22.7m)
            #     H = current_up - Pool2 = current_up - z_planned[2]
            if s.id == 1:
                ref_h_seq = [z - s.current_down for z in upper_res["z_planned"][1][:horizon_lower]]
            elif s.id == 2:
                ref_h_seq = [
                    upper_res["z_planned"][2][t] - upper_res["z_planned"][1][t]
                    for t in range(min(horizon_lower, len(upper_res["z_planned"][1])))
                ]
            else:
                ref_h_seq = [s.current_up - z for z in upper_res["z_planned"][2][:horizon_lower]]
            
            # 补齐长度
            if len(ref_q_seq) < horizon_lower:
                ref_q_seq.extend([ref_q_seq[-1]] * (horizon_lower - len(ref_q_seq)))
                ref_h_seq.extend([ref_h_seq[-1]] * (horizon_lower - len(ref_h_seq)))
                
            l_res = self.lower_mpcs[s.id].solve(ref_q_seq, ref_h_seq, step)
            lower_res[s.id] = l_res
            
            # 更新机组控制计数记忆，正式记录在0时刻的真正执行动作
            for i, st in enumerate(l_res["status"][0]):
                is_switch = (st != self.lower_mpcs[s.id].memory.status[i])
                is_adjust = (st == 1 and abs(l_res["openings"][0][i] - self.lower_mpcs[s.id].memory.openings[i]) > 0.5)
                self.lower_mpcs[s.id].memory.update(
                    i, step, switch=is_switch, adjust=is_adjust,
                    status=st, opening=l_res["openings"][0][i]
                )
                    
            # 可选：此处构造水泵下发控制指令 commands.append(pump_request)
            for i, st in enumerate(l_res["status"][0]):
                pump_request = self._build_station_target_value_request(
                    target_agent_code=f"STATION_{s.id}",
                    target_command_type=DeviceValueTypeEnum.BLADE_ANGLE.code,
                    target_value=l_res["openings"][0][i],
                    object_id=1000 + s.id * 10 + i, # Dummy ID
                    object_type=HydroObjectType.PUMP,
                )
                if pump_request: 
                    commands.append(pump_request)
                    
        self.mpc_output = {"upper": upper_res, "lower": lower_res}
        
        # 下发物理控制指令
        for cmd in commands:
            self.send_command(cmd)

        return commands

        return [
            {
                "target_agent_code": "STATION_AGENT",
                "target_command_type": DeviceValueTypeEnum.BLADE_ANGLE.code,
                "target_value": -6,
                "object_id": 1021,
                "object_type": HydroObjectType.PUMP,
            }
        ]

    def on_next(self, actual_levels, actual_flows, step):
        """
        接收环境/仿真器真实数据反馈。更新智能体内部观察期和上层积分器。
        """
        logger.info(f"第 {step} 步收到真实量测数据。通过闭环反馈校核模型状态...")
        
        # 1. 更新当前状态
        for i, s in enumerate(self.stations):
            s.current_flow = actual_flows[i]
            
        self.stations[1].current_up = actual_levels[0]
        self.stations[2].current_up = actual_levels[1]
        
        # 2. 估计渠道扰动 d_k = (z_k - z_{k-1})*S/dt - (q_{in} - q_{out})
        if "upper" in self.mpc_output:
            q_plan = self.mpc_output["upper"]["q_planned"]
            d1_plan = self.demand_plan['station1-station2'].iloc[step] if self.demand_plan is not None and step < len(self.demand_plan) else 0
            d2_plan = self.demand_plan['station2-station3'].iloc[step] if self.demand_plan is not None and step < len(self.demand_plan) else 0
            
            q1_actual = actual_flows[0]; q2_actual = actual_flows[1]; q3_actual = actual_flows[2]
            
            # 真实渠道流量差额计算
            actual_d1 = (actual_levels[0] - cur_levels_prev[0]) * self.pools[0].area / 3600 - (q1_actual - q2_actual) if 'cur_levels_prev' in locals() else 0
            actual_d2 = (actual_levels[1] - cur_levels_prev[1]) * self.pools[1].area / 3600 - (q2_actual - q3_actual) if 'cur_levels_prev' in locals() else 0
            
            self.observers[1].update(actual_d1, -d1_plan)
            self.observers[2].update(actual_d2, -d2_plan)
        
        # 3. 稳态补偿积分 (上层末站目标零静差)
        self.upper_mpc.integral_error += (actual_flows[2] - self.upper_mpc.target_q) * 0.1

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        处理时间序列数据更新（例如外部水位观测、边界条件等）。
        
        参数:
            request: 时间序列数据更新请求，包含新数据
        """
        logger.info(f"--- 收到时间序列数据更新：{request.command_id} ---")
        
        # 1. 获取变更的数据事件
        event = request.time_series_data_changed_event
        
        # 2. 遍历并处理数据
        for obj_ts in event.object_time_series:
            logger.info(f"对象 {obj_ts.object_name} 的指标 {obj_ts.metrics_code} 已更新")
            
            # 这里可以将数据存入本地缓存，或直接更新优化模型的边界条件
            # 例如更新模型的边界约束:
            # self.on_boundary_condition_update([obj_ts])
            
            # 打印部分数据供调试
            if obj_ts.time_series:
                first_val = obj_ts.time_series[0]
                logger.debug(f"  首个数据点: Step={first_val.step}, Value={first_val.value}")

        # 3. 返回成功响应
        return TimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False
        )

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest) -> OutflowTimeSeriesDataUpdateResponse:
        """
        处理出流时间序列数据更新。

        参数:
            request: 出流时间序列数据更新请求
        """
        logger.info(f"--- 收到出流量时间序列数据更新：{request.command_id} ---")

        # 1. 获取变更的数据事件
        event = request.outflow_time_series_data_changed_event

        if event and event.object_time_series:
            # 2. 遍历并处理数据
            for obj_ts in event.object_time_series:

                # 打印部分数据供调试
                if obj_ts.time_series:
                    first_val = obj_ts.time_series[0]
                    logger.debug(f"  首个数据点: Step={first_val.step}, Value={first_val.value}")

            # 3. 更新优化模型的边界条件（让 MPC 能够感知到这些计划外的流量变化）
            # self.on_boundary_condition_update(event.object_time_series)

        # 4. 返回成功响应
        return OutflowTimeSeriesDataUpdateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False
        )

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止智能体运行并清理资源。
        """
        logger.info(f"正在停止中央调度智能体: {self.agent_id}")

        # 清理资源
        self._shutdown_agent_command_client()
        self._optimization_model = None
        
        # 从状态管理器中注销
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False
        )


class CentralSchedulingAgentFactory(HydroAgentFactory):
    """
    中央调度智能体工厂类。用于动态创建智能体实例。
    """

    def create_agent(
        self,
        sim_coordination_client: SimCoordinationClient,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        **kwargs
    ):
        """创建一个新的中央调度智能体实例。"""
        return PumpCentralSchedulingAgent(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            **kwargs
        )


def main():
    """主入口函数。"""
    logger.info("=" * 60)
    logger.info("中央调度智能体示例程序启动")
    logger.info("=" * 60)
    
    try:
        # 加载环境和智能体配置
        env_config = load_env_config()
        agent_config = load_agent_config()

        # 创建协调客户端
        client = SimCoordinationClient(
            broker_url=env_config['mqtt_broker_url'],
            broker_port=env_config['mqtt_broker_port'],
            topic=env_config['mqtt_topic'],
            callback=MultiAgentCallback(CentralSchedulingAgentFactory()),
            hydros_cluster_id=env_config.get('hydros_cluster_id', 'default'),
            hydros_node_id=env_config.get('hydros_node_id', 'local')
        )

        # 连接到 MQTT 代理
        client.connect()
        logger.info("智能体已连接并进入就绪状态")

        # 保持运行
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("正在退出...")
            client.disconnect()

    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
