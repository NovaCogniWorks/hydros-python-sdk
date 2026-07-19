"""
中央调度智能体示例

本模块展示了如何基于 CentralSchedulingAgent 基类实现一个具体的中央调度智能体。
该智能体使用自定义 ODD-DMPC 调度算法，不装配 SDK 默认 MPC rolling runtime。
"""

import logging
import os
import sys
import pandas as pd
from typing import Optional, List, Dict, Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from hydros_agent_sdk import (
    ErrorCodes,
    handle_agent_errors,
)
from hydros_agent_sdk.utils import HydroObjectType, MetricsCodes
from hydros_agent_sdk.protocol.agent_common import DeviceValueTypeEnum
from hydros_agent_sdk.agents.central_scheduling_agent import CentralSchedulingAgent
from hydros_agent_sdk.mpc.mpc_result_factory import MpcResultFactory
from hydros_agent_sdk.mpc.task_state import MpcTaskState
from hydros_agent_sdk.mpc.task_state_lifecycle import MpcTaskStateLifecycle
from hydros_agent_sdk.protocol.commands import *
from hydros_agent_sdk.protocol.models import *

logger = logging.getLogger(__name__)


class PumpCentralSchedulingAgent(CentralSchedulingAgent):
    """
    中央调度智能体的具体实现。

    该智能体的主要功能包括：
    1. 加载水网拓扑结构
    2. 初始化自定义 ODD-DMPC 优化模型
    3. 通过 MQTT 订阅现地实时指标（Field Metrics）
    4. 执行自定义滚动调度优化逻辑
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
        **kwargs
    ):
        """初始化中央调度智能体。"""
        configured_mpc_config_url = kwargs.pop("mpc_config_url", None)
        configured_target_and_constrain_config_url = kwargs.pop(
            "target_and_constrain_config_url",
            None,
        )
        super().__init__(
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
        object.__setattr__(self, "_configured_mpc_config_url", configured_mpc_config_url)
        object.__setattr__(
            self,
            "_configured_target_and_constrain_config_url",
            configured_target_and_constrain_config_url,
        )
        self._mpc_task_state_lifecycle = MpcTaskStateLifecycle(
            context=context,
            get_current_step=self._get_current_scheduling_step,
            get_rolling_interval_steps=lambda: 1,
            get_total_steps=self._get_total_scheduling_steps,
            get_algorithm_config_url=lambda: self._configured_mpc_config_url,
            get_control_config_url=(
                lambda: self._configured_target_and_constrain_config_url
            ),
        )
        logger.info(f"中央调度智能体实例已创建: {agent_id}")

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[Any]]:
        """执行泵站自定义滚动调度，并下发生成的控制指令。"""
        self._ensure_mpc_task_state(request.step).current_step = request.step
        commands = self.on_optimization(request.step)
        if commands:
            self.dispatch_control_commands_and_await_execution(commands)
        return None

    def _resolve_config_path(self) -> str:
        return os.path.abspath(
            os.path.join(_SCRIPT_DIR, "..", "data", "config_xhh.yaml")
        )

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化智能体。该方法在任务启动时被调用。
        """
        logger.info(f"正在初始化智能体: {self.agent_id}")
        self._internal_opt_step = 0

        try:
            # 1. 加载智能体配置 (从 agent.properties)
            self.load_agent_configuration(request)

            # 2. 先订阅现地指标，避免后续耗时初始化期间错过水动力首帧数据
            self.subscribe_field_metrics()

            # 3. 初始化梯级泵站和优化模型 (模拟)
            self._lazy_init_odd_mpc()

            # 4. 启动 agent command 客户端，后面就能直接发指令
            self._agent_command_gateway.start()

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
            self._agent_command_gateway.shutdown()
            raise


    def _lazy_init_odd_mpc(self):
        if hasattr(self, 'odd_initialized') and self.odd_initialized:
            return
            
        import os
        from odd_dmpc.config import build_zero_demand_plan, load_runtime_context_from_payload
        from odd_dmpc.flow_service import FlowDepartService
        from odd_dmpc.local_controller import LocalController
        from odd_dmpc.observers import DisturbanceObserverBank
        from odd_dmpc.odd_supervisor import ODDSupervisor
        from odd_dmpc.upper_scheduler import UpperScheduler
        from odd_dmpc.types import LowerFeedback, StationMemory
        from odd_dmpc.environment import _boundary_plan_from_snapshot
        import pandas as pd
        
        from hydros_agent_sdk.mpc.config import MpcConfigResolver
        from hydros_agent_sdk.utils.yaml_loader import YamlLoader
        import os
        import yaml

        mpc_config = MpcConfigResolver.resolve(
            self.properties,
            configured_mpc_config_url=getattr(self, '_configured_mpc_config_url', None)
        )
        logger.info(f"解析得到的 mpc_config 对象内容: {mpc_config}")
        
        mpc_config_url = mpc_config.mpc_config_url
        payload = {}

        if mpc_config_url:
            logger.info(f"正在从 mpc_config_url 载入配置: {mpc_config_url}")
            try:
                if mpc_config_url.startswith("http://") or mpc_config_url.startswith("https://"):
                    payload = YamlLoader.from_url(mpc_config_url)
                else:
                    payload = YamlLoader.from_file(mpc_config_url)
            except Exception as e:
                logger.error(f"无法从 mpc_config_url 加载配置: {e}")

        if not payload or 'project' not in payload:
            logger.warning("未配置 mpc_config_url 或加载失败/缺少项目字段，回退到默认的 'custom-agent/pump/data/config_xhh.yaml'。")
            fallback_path = self._resolve_config_path()
            with open(fallback_path, 'r', encoding='utf-8') as f:
                payload = yaml.safe_load(f)
        context = load_runtime_context_from_payload(payload)
        self.response_metadata = payload.get("service_mapping", {}).get("response_metadata", {})
        self.system_config = context["system_config"]
        self.runtime = context["runtime"]
        
        self._init_dynamic_demand_plan(build_zero_demand_plan, payload)
        
        self.flow_service = FlowDepartService(self.system_config, config_dict=payload)
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
        
        self.total_startup_count = 0
        self.total_shutdown_count = 0
        self.total_blade_adjust_count = 0
        
        self.station_sensors = payload.get("service_mapping", {}).get("station_sensors", [])
        
        self.odd_initialized = True
        self.upper_scheduler = UpperScheduler(
            self.system_config,
            self.odd_demand_plan,
            self.runtime,
            self.flow_service,
            pd.DataFrame() # 后续会在 on_optimization 中更新
        )
        
        # 预先计算所有泵站的流量分配表，避免在首次 rolling optimization 时产生卡顿
        logger.info("========== 开始初始化所有泵站机组的离线流量分配表 ==========")
        for station in self.system_config.stations:
            available_ids = self.available_units_map.get(station.id, [])
            if available_ids:
                logger.info(f"正在初始化 Station ID: {station.id} 的流量分配组合 ...")
                self.flow_service.get_optimal_table(station.id, available_ids)
        logger.info("========== 所有泵站流量分配表初始化完成 ==========")

    def _init_dynamic_demand_plan(self, build_zero_demand_plan, payload):
        """
        初始化动态入流用水计划，替代原基于 Excel 文件的 demand_plan
        """
        # 构建 disturbance_node 与 column 映射，并初始列
        self._disturbance_node_to_col = {}
        self._disturbance_sensor_key_to_col = {}
        self._disturbance_sensor_key_to_sign = {}
        pool_id_to_col = {}
        for segment in self.system_config.topology.channel_segments:
            if getattr(segment, "disturbance_node", None):
                col_name = f"station{segment.upstream_station_id}-station{segment.downstream_station_id}"
                self._disturbance_node_to_col[str(segment.disturbance_node)] = col_name
        self._pool_id_to_col = {}
        for idx, pool_id in enumerate(self.system_config.pool_ids):
            if idx < len(self.system_config.station_ids) - 1:
                upstream_station_id = self.system_config.station_ids[idx]
                downstream_station_id = self.system_config.station_ids[idx + 1]
                self._pool_id_to_col[int(pool_id)] = f"station{upstream_station_id}-station{downstream_station_id}"
        pool_id_to_col = self._pool_id_to_col
        for sensor in payload.get("service_mapping", {}).get("disturbance_sensors", []):
            if not isinstance(sensor, dict):
                continue
            pool_id = sensor.get("pool_id")
            if pool_id is None:
                continue
            col_name = pool_id_to_col.get(int(pool_id))
            if not col_name:
                continue
            sensor_name = str(sensor.get("node_name") or sensor.get("object_name") or "")
            sign = self._disturbance_sensor_sign(sensor_name)
            for raw_key in (sensor.get("object_id"), sensor.get("node_id"), sensor.get("node_name"), sensor.get("object_name")):
                if raw_key is None:
                    continue
                key = str(raw_key)
                self._disturbance_sensor_key_to_col[key] = col_name
                self._disturbance_sensor_key_to_sign[key] = sign
        self.global_demand_plan = build_zero_demand_plan(self.system_config, length=200)
        self.global_rain_plan = build_zero_demand_plan(self.system_config, length=200)
        self.odd_demand_plan = build_zero_demand_plan(self.system_config)
        self._sync_dynamic_demand_plan()

    def _sync_dynamic_demand_plan(self) -> None:
        if hasattr(self, "upper_scheduler"):
            self.upper_scheduler.demand_plan = self.odd_demand_plan
        if hasattr(self, "plot_tracker"):
            self.plot_tracker.demand_plan = self.odd_demand_plan
            if hasattr(self, "global_rain_plan"):
                self.plot_tracker.global_rain_plan = self.global_rain_plan

    def _disturbance_sensor_sign(self, sensor_name: str) -> float:
        normalized_name = str(sensor_name).strip()
        if "入水" in normalized_name or "来水" in normalized_name:
            return 1.0
        return -1.0

    def _sync_station_memory_from_live_state(self, station_id: int, total_flow: float) -> None:
        if station_id not in self.station_memories:
            return
        station_memory = self.station_memories[station_id]
        station_memory.active_unit_ids = [
            unit_id
            for unit_id, status in station_memory.unit_status.items()
            if int(status) == 1
        ]
        station_memory.last_selected_flow = float(total_flow)

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        current_step = getattr(self, "_internal_opt_step", 0)
        logger.info(f"========== 开启第 {current_step} 步滚动优化 (外部触发 step={step}) ==========")
        self._outer_step = step
        
        if hasattr(self, "global_demand_plan"):
            horizon = self.system_config.horizon_hours
            opt_start_step = max(0, step - current_step)
            end_idx = opt_start_step + horizon
            if end_idx > len(self.global_demand_plan):
                import pandas as pd
                expand_len = max(100, end_idx - len(self.global_demand_plan))
                new_df = pd.DataFrame(0.0, index=range(len(self.global_demand_plan), len(self.global_demand_plan) + expand_len), columns=self.global_demand_plan.columns)
                self.global_demand_plan = pd.concat([self.global_demand_plan, new_df], ignore_index=True)
                if hasattr(self, "global_rain_plan"):
                    new_rain_df = pd.DataFrame(0.0, index=range(len(self.global_rain_plan), len(self.global_rain_plan) + expand_len), columns=self.global_rain_plan.columns)
                    self.global_rain_plan = pd.concat([self.global_rain_plan, new_rain_df], ignore_index=True)
            self.odd_demand_plan = self.global_demand_plan.iloc[opt_start_step:end_idx].copy().reset_index(drop=True)
            self._sync_dynamic_demand_plan()
            
        step_val = current_step
        self._internal_opt_step = current_step + 1
        
        self._lazy_init_odd_mpc()
        
        max_step = self.system_config.horizon_hours
        if current_step >= max_step:
            logger.info(f"当前内部 step ({current_step}) 已达到或超过系统配置的最大步数 ({max_step})，跳过本次优化。")
            if not getattr(self, "_summary_plot_generated", False):
                if hasattr(self, 'plot_tracker') and hasattr(self.plot_tracker, 'generate_summary_plot'):
                    self.plot_tracker.generate_summary_plot()
                self._summary_plot_generated = True
            return []
            
        # 首先打印 _metrics_data_cache 包含的组件数据
        # 调试示例：cache_dump = []
        # 调试示例：for key, data in self._metrics_data_cache.latest_metrics.items():
        # 调试示例：    cache_dump.append(f"  {key}: {data}")
        # 调试示例：logger.info(f"当前 _metrics_data_cache 中的所有最新组件数据:\n" + "\n".join(cache_dump))
        
        from odd_dmpc.types import EnvironmentObservation, StationMemory
        from odd_dmpc.local_controller import StationControlContext
        import pandas as pd
        
        from odd_dmpc.environment import _level_keys, _ordered_station_ids, resolve_pool_areas
        
        # 从自身跟踪状态初始化或更新记忆
        if not self.station_memories:
            for sid in self.system_config.station_ids:
                self.station_memories[sid] = StationMemory(
                    active_unit_ids=[],
                    unit_openings={u: 0.0 for u in self.available_units_map[sid]},
                    unit_status={u: 0 for u in self.available_units_map[sid]},
                    time_since_adjust={u: 999 for u in self.available_units_map[sid]},
                    time_since_switch={u: 999 for u in self.available_units_map[sid]},
                    last_selected_flow=0.0,
                    mode="ODD1"
                )
                
        mem_log = []
        for sid, mem in self.station_memories.items():
            mem_log.append(f"S{sid} 状态: {mem.unit_status}, 叶片角: {mem.unit_openings}")
        logger.info(f"当前Agent缓存机组工况:\n  " + "\n  ".join(mem_log))
        
        level_keys = _level_keys(self.system_config)
        station_ids = _ordered_station_ids(self.system_config)

        station_back_levels = {}
        station_front_levels = {}
        station_heads = {}
        station_flows = {}
        
        # 遍历每座泵站，从各机组获取实时数据
        pump_data_logs = []
        for sid in self.system_config.station_ids:
            uids = self.available_units_map.get(sid, [])
            if not uids:
                continue
            
            total_q = 0.0
            up_levels = []
            dn_levels = []
            
            for uid in uids:
                # 获取机组开度(100为关机)
                angle = self._metrics_data_cache.get_value(uid, "blade_angle")
                if angle is not None:
                    angle_val = float(angle)
                    status = 0 if abs(angle_val - 100.0) < 1e-3 else 1
                    # 同步到 Agent 缓存。注意：这里直接覆盖 status 和 openings
                    # 这个修改代表“从真实环境同步最新状态”，并没有修改 time_since_switch/time_since_adjust
                    # 所以这个同步行为不会错误地计入下层MPC决策的启停和调整次数，逻辑是正确的。
                    if self.station_memories and sid in self.station_memories:
                        self.station_memories[sid].unit_status[uid] = status
                        self.station_memories[sid].unit_openings[uid] = angle_val
                else:
                    angle_val = "None"
                    status = "None"
                
                # 获取机组流量 (强制从 attributes 或顶层 payload 提取 back_water_flow，不允许降级)
                q = self._metrics_data_cache.get_attribute_from_any_metric(uid, "back_water_flow")
                if q is None:
                    # 查找对应的组件名称
                    station = next((s for s in self.system_config.stations if s.id == sid), None)
                    station_name = station.name if station else f"S{sid}"
                    unit_name = station.unit_name_by_id.get(uid, f"U{uid}") if station else f"U{uid}"
                    raise ValueError(
                        f"取值失败！无法从 metrics_data_cache 提取泵站[{station_name}]-机组[{unit_name}] (ID: {sid}-{uid}) 的 back_water_flow 最新流量数据"
                    )
                total_q += float(q)
                
                # 获取机组水文(前后水位)，优先从 attributes 提取
                u_lvl = self._metrics_data_cache.get_attribute_from_any_metric(uid, "front_water_level")
                if u_lvl is None:
                    u_lvl = self._metrics_data_cache.get_value(uid, "up_water_level")
                    
                d_lvl = self._metrics_data_cache.get_attribute_from_any_metric(uid, "back_water_level")
                if d_lvl is None:
                    d_lvl = self._metrics_data_cache.get_value(uid, "down_water_level")
                if u_lvl is not None:
                    up_levels.append(float(u_lvl))
                if d_lvl is not None:
                    dn_levels.append(float(d_lvl))
                    
                pump_data_logs.append(
                    f"  泵S{sid}-U{uid}: 状态={status}, 开度={angle_val}, 流量={q}, "
                    f"前水位={u_lvl}, 后水位={d_lvl}"
                )
            
            # 前后平均水位作为实际前后水位
            f_val = sum(up_levels) / len(up_levels) if up_levels else None
            b_val = sum(dn_levels) / len(dn_levels) if dn_levels else None
            
            # 仿真模块异常，临时写死边界水位
            if sid == 20000 and (f_val is None or f_val < 0):
                f_val = 13.26
            if sid == 20600 and (b_val is None or b_val < 0):
                b_val = 23.093
            
            if f_val is None or b_val is None:
                raise ValueError(f"无法从 metrics_data_cache 提取 S{sid} 的最新水文数据")
                
            station_front_levels[sid] = float(f_val)
            station_back_levels[sid] = float(b_val)
            station_heads[sid] = float(b_val) - float(f_val)
            station_flows[sid] = total_q
            self._sync_station_memory_from_live_state(sid, total_q)
            
        logger.info("从 _metrics_data_cache 获取的各泵机组原始数据:\n" + "\n".join(pump_data_logs))
                
        summary_logs = []
        for sid in self.system_config.station_ids:
            station = next((s for s in self.system_config.stations if s.id == sid), None)
            station_name = station.name if station else f"S{sid}"
            summary_logs.append(
                f"  S{sid}({station_name}): 前池水位={station_front_levels.get(sid, 0.0):.3f}, 后池水位={station_back_levels.get(sid, 0.0):.3f}, 总流量={station_flows.get(sid, 0.0):.3f}"
            )
            
        logger.info("第一时间读取并传入当前工况值 (根据各泵机组平均和汇总):\n" + "\n".join(summary_logs))
                
        basin_levels = {}
        if station_ids and level_keys:
            basin_levels[level_keys[0]] = station_front_levels.get(station_ids[0], 0.0)
            for i in range(len(station_ids) - 1):
                s_up = station_ids[i]
                s_dn = station_ids[i+1]
                avg_lvl = (station_back_levels.get(s_up, 0.0) + station_front_levels.get(s_dn, 0.0)) / 2.0
                if i + 1 < len(level_keys):
                    basin_levels[level_keys[i + 1]] = avg_lvl
            if len(level_keys) > len(station_ids):
                basin_levels[level_keys[-1]] = station_back_levels.get(station_ids[-1], 0.0)
        
        pool_areas = resolve_pool_areas(self.system_config)
        pool_levels = {}
        if self.system_config.pool_ids:
            for i, pool_id in enumerate(self.system_config.pool_ids):
                if i + 1 < len(level_keys):
                    pool_levels[pool_id] = basin_levels.get(level_keys[i + 1], 0.0)
                    
        anchor_basin_levels = {}
        if level_keys:
            anchor_basin_levels[level_keys[0]] = basin_levels.get(level_keys[0], 0.0)
            anchor_basin_levels[level_keys[-1]] = basin_levels.get(level_keys[-1], 0.0)
        
        observation = EnvironmentObservation(
            time_index=step,
            time_hours=step * float(self.system_config.dt_hours),
            basin_levels=basin_levels,
            basin_volumes={},
            pool_areas=pool_areas,
            basin_profiles=None,
            anchor_basin_levels=anchor_basin_levels,
            boundary_nominal_flows={},
            station_back_levels=station_back_levels,
            station_front_levels=station_front_levels,
            station_heads=station_heads,
            station_flows=station_flows,
            pool_levels=pool_levels
        )
        
        # 计算观测器使用的时间步长
        # 每次调用optimization的间隔按系统配置的 dt_hours 计算
        last_opt_step = getattr(self, "last_opt_step", step - 1)
        step_hours = (step - last_opt_step) * float(self.system_config.dt_hours)
        if step_hours <= 0:
            step_hours = float(self.system_config.dt_hours)  # 避免首次调用时为0
        self.last_opt_step = step

        # 上层调度器
        logger.info(f"完整的需水计划表 (step={step}):\n{self.odd_demand_plan.to_string()}")
        demand_row = self.odd_demand_plan.iloc[min(max(step, 0), len(self.odd_demand_plan) - 1)]
        logger.info(f"误差观察器扰动计算时用到的需水计划值 (step={step}):\n{demand_row}")
        self.observers.update(
            prev_basin_levels=basin_levels,
            next_basin_levels=basin_levels, # 为简化 test_mpc，这里没有 prev
            actual_flows=station_flows,
            demand_row=demand_row,
            prev_basin_volumes=None,
            next_basin_volumes=None,
            prev_basin_profiles=None,
            next_basin_profiles=None,
            defer_visibility=False,
            step_hours=step_hours,
            pool_areas=pool_areas,
        )
        
        # 边界计划
        boundary_levels_dict = {}
        for node in self.system_config.topology.boundary_nodes:
            key = str(node.mpc_key or node.id or node.hydro_node)
            if node.mpc_key and node.mpc_key in basin_levels:
                boundary_levels_dict[key] = basin_levels[node.mpc_key]
            else:
                boundary_levels_dict[key] = basin_levels.get(key, 0.0)
        
        if not boundary_levels_dict and level_keys:
            boundary_levels_dict[level_keys[0]] = basin_levels.get(level_keys[0], 0.0)
            boundary_levels_dict[level_keys[-1]] = basin_levels.get(level_keys[-1], 0.0)
            
        from odd_dmpc.environment import _boundary_plan_from_snapshot
        boundary_level_plan = _boundary_plan_from_snapshot(self.system_config, boundary_levels_dict)
        self.upper_scheduler.boundary_level_plan = boundary_level_plan
        
        horizon = max(int(self.system_config.horizon_hours - step), 1)
        disturbance_forecast = self.observers.get_forecast(horizon=horizon, step_hours=float(self.system_config.dt_hours))
        
        observer_est = self.observers.get_estimate()
        logger.info(
            f"准备调用 Upper Scheduler (step={step}):\n"
            f"  各个渠道的误差观察器估计值: {observer_est}"
        )
        upper_plan_range = self.odd_demand_plan.iloc[step: step + horizon] if step < len(self.odd_demand_plan) else self.odd_demand_plan.iloc[-1:]
        logger.info(f"上层规划计算时用的需水计划值 (step={step} to {step+horizon-1}):\n{upper_plan_range.to_string()}")
        
        upper_plan = self.upper_scheduler.solve(
            now=0,
            # now=step,  #不要删，之前是step，不确定是否demand plan已经按step到72截好了
            env_snapshot=observation,
            demand_state={"delivered_last_station_total": float(self.cumulative_last_station_flow)},
            available_units_map=self.available_units_map,
            disturbance_forecast=disturbance_forecast,
            lower_feedback=self.lower_feedback,
        )
        
        q_next = {sid: round(refs[0], 2) for sid, refs in upper_plan.flow_refs.items() if refs}
        z_f_next = {sid: round(refs[0], 2) for sid, refs in upper_plan.station_front_levels.items() if refs}
        z_b_next = {sid: round(refs[0], 2) for sid, refs in upper_plan.station_back_levels.items() if refs}
        h_next = {sid: round(refs[0], 2) for sid, refs in upper_plan.station_heads.items() if refs}
        
        total_target_volume = self.system_config.target_avg_flow_last_station * self.system_config.horizon_hours
        remaining_target = max(total_target_volume - float(self.cumulative_last_station_flow), 0.0)
        
        logger.info(
            f"目标={total_target_volume:.2f}, 剩余目标={remaining_target:.2f}\n"
            f"上层预测(首步): 流量={q_next}, 预测前池={z_f_next}, 预测后池={z_b_next}, 预测扬程={h_next}"
        )
        
        # 下层控制器
        actions = {}
        decisions = {}
        upstream_selected_flows = {}
        transfer_bundles = {}
        
        # 首先预填充全部传输 bundle，使其可用于预测
        for station_id in self.system_config.station_ids:
            station_memory = self.station_memories[station_id]
            reference_flow = [float(f) for f in upper_plan.flow_refs[station_id]]
            reference_back_level = [float(f) for f in upper_plan.station_back_levels[station_id]]
            reference_front_level = [float(f) for f in upper_plan.station_front_levels[station_id]]
            reference_head = [float(f) for f in upper_plan.station_heads[station_id]]
            
            from odd_dmpc.types import TransferBundle
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

        for station_id in self.system_config.station_ids:
            station_model = self.flow_service.get_station_model(station_id, self.available_units_map[station_id])
            station_memory = self.station_memories[station_id]
            transfer_bundle = transfer_bundles[station_id]
            
            reference_flow = transfer_bundle.reference_flow
            reference_back_level = transfer_bundle.reference_back_level
            reference_front_level = transfer_bundle.reference_front_level
            reference_head = transfer_bundle.reference_head
            
            logger.info(f"开始执行下层 Lower Controller 优化: 泵站 S{station_id}, 参考目标流量={reference_flow[0]:.2f}, 参考目标后池水位={reference_back_level[0]:.2f}")
            
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
            decisions[station_id] = decision
            
            lower_plan_range = self.odd_demand_plan.iloc[min(max(step, 0), len(self.odd_demand_plan) - 1)]
            logger.info(f"下层计算时用的需水计划值 S{station_id} (step={step}):\n{lower_plan_range}")
            
            ctx = StationControlContext(
                station_id=station_id,
                station_model=station_model,
                available_unit_ids=self.available_units_map[station_id],
                basin_levels=observation.basin_levels.copy(),
                basin_profiles=None,
                pool_areas=observation.pool_areas.copy(),
                anchor_basin_levels=observation.anchor_basin_levels.copy(),
                boundary_nominal_flows={},
                current_back_level=observation.station_back_levels[station_id],
                current_front_level=observation.station_front_levels[station_id],
                current_head=observation.station_heads[station_id],
                upper_flow_refs={sid: tb.reference_flow for sid, tb in transfer_bundles.items()},
                flow_history={sid: self.station_flow_history[sid][:] for sid in self.station_flow_history},
                boundary_level_plan=boundary_level_plan,
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
            
            pf = round(action.predicted_front_level, 2) if action.predicted_front_level is not None else None
            pb = round(action.predicted_back_level, 2) if action.predicted_back_level is not None else None
            ph = round(action.predicted_head, 2) if action.predicted_head is not None else None
            logger.info(
                f"下层 S{station_id} 预测(首步): 流量={action.selected_flow:.2f}, 预测前池={pf}, 预测后池={pb}, 预测扬程={ph}, "
                f"叶片角={action.unit_openings}, 状态={action.unit_status}, 模式={action.mode}"
            )
            
            actions[station_id] = action
            upstream_selected_flows[station_id] = float(action.selected_flow)
            
            # 更新记忆
            new_active_ids = []
            for uid, st in action.unit_status.items():
                if st == 1: new_active_ids.append(uid)
                old_st = station_memory.unit_status.get(uid, 0)
                if st != old_st:
                    station_memory.time_since_switch[uid] = 0
                    if st == 1 and old_st == 0:
                        self.total_startup_count += 1
                    elif st == 0 and old_st == 1:
                        self.total_shutdown_count += 1
                else:
                    station_memory.time_since_switch[uid] += 1
                
                old_op = station_memory.unit_openings.get(uid, 0.0)
                new_op = action.unit_openings.get(uid, 0.0)
                if abs(new_op - old_op) > getattr(self.runtime, 'opening_change_threshold', 0.0):
                    station_memory.time_since_adjust[uid] = 0
                    self.total_blade_adjust_count += 1
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

        # 映射到 test_mpc 使用的旧输出格式
        lower_res = {}
        for sid in self.system_config.station_ids:
            action = actions[sid]
            horizon_len = len(action.predicted_openings) if getattr(action, "predicted_openings", None) else 1
            if horizon_len == 0:
                horizon_len = 1
                
            status_seq, openings_seq, effs_seq, total_q_seq = [], [], [], []
            unit_ids = self.available_units_map[sid]
            
            for step_idx in range(horizon_len):
                st_list = [
                    action.predicted_unit_status.get(u, [0]*horizon_len)[step_idx] if getattr(action, "predicted_unit_status", None) else action.unit_status.get(u, 0)
                    for u in unit_ids
                ]
                op_list = [
                    action.predicted_unit_openings.get(u, [0.0]*horizon_len)[step_idx] if getattr(action, "predicted_unit_openings", None) else action.unit_openings.get(u, 0.0)
                    for u in unit_ids
                ]
                eff_list = [
                    action.predicted_unit_efficiencies.get(u, [0.0]*horizon_len)[step_idx] if getattr(action, "predicted_unit_efficiencies", None) else 0.0
                    for u in unit_ids
                ]
                if getattr(action, "predicted_unit_flows", None):
                    t_q = sum(action.predicted_unit_flows.get(u, [0.0]*horizon_len)[step_idx] for u in unit_ids)
                else:
                    t_q = action.selected_flow
                
                status_seq.append(st_list)
                openings_seq.append(op_list)
                effs_seq.append(eff_list)
                total_q_seq.append(t_q)
                
            lower_res[sid] = {
                "status": status_seq,
                "openings": openings_seq,
                "effs": effs_seq,
                "total_q": total_q_seq
            }
            
        # 格式化 upper_res
        upper_res = {
            "q_planned": {sid: upper_plan.flow_refs[sid] for sid in self.system_config.station_ids},
            "z_planned": {sid: upper_plan.station_back_levels[sid] for sid in self.system_config.station_ids}
        }
            
        self.mpc_output = {"upper": upper_res, "lower": lower_res}
        
        # 绘图支持
        if not hasattr(self, "plot_tracker"):
            from plot_tracker import PlotHistoryTracker
            self.plot_tracker = PlotHistoryTracker(
                system_config=self.system_config,
                demand_plan=getattr(self, "odd_demand_plan", None),
                output_dir="output/agent_steps"
            )
            self.plot_tracker.step_predictions = []
            
        self.plot_tracker.step_predictions.append({
            "step": int(current_step),
            "upper": upper_res,
            "lower": lower_res
        })
        
        self.plot_tracker.update_and_plot(
            step_index=int(current_step),
            current_time_hours=float(current_step * self.system_config.dt_hours),
            lower_step_hours=float(self.system_config.dt_hours),
            upper_plan=upper_plan,
            actions=actions,
            decisions=decisions,
            observation=observation,
            transfer_bundles=transfer_bundles
        )
        
        # 按照用户要求，生成 MpcPredictionResultReport 并发送
        from hydros_agent_sdk.mpc.mpc_prediction_result_reporter import MpcPredictionResultReporter
        from hydros_agent_sdk.mpc.models import HorizonStep, ValueItem, DeviceResult

        try:
            first_sid = self.system_config.station_ids[0]
            plan_len = len(actions[first_sid].predicted_openings)
        except Exception:
            plan_len = 10
        
        horizon_step_list = []
        for i in range(plan_len):
            control_object_list = []
            predicted_result_list = []
            
            for sid in self.system_config.station_ids:
                st_action = actions[sid]
                
                # 全站水位预测从 upper_plan 中取
                st_front = upper_plan.station_front_levels[sid][i] if sid in upper_plan.station_front_levels and i < len(upper_plan.station_front_levels[sid]) else None
                st_back = upper_plan.station_back_levels[sid][i] if sid in upper_plan.station_back_levels and i < len(upper_plan.station_back_levels[sid]) else None
                
                # 单机组预测与控制
                for uid, op in st_action.unit_openings.items():
                    # 控制量（叶片角）
                    st = st_action.unit_status.get(uid, 0)
                    target_value = 100.0 if st == 0 else float(op)
                    
                    
                    # 单机组预测流量和效率
                    u_flow_list = st_action.predicted_unit_flows.get(uid, [])
                    u_eff_list = getattr(st_action, "predicted_unit_efficiencies", {}).get(uid, [])
                
                # 全站级预测
                if i == 0:
                    st_flow = float(st_action.selected_flow)
                else:
                    ref_flow_list = upper_plan.flow_refs.get(sid, [])
                    st_flow = float(ref_flow_list[i]) if i < len(ref_flow_list) else None
                
                # 全站平均效率预测
                st_eff_list = getattr(st_action, "predicted_efficiencies", [])
                st_eff_val = float(st_eff_list[i]) if i < len(st_eff_list) else None

                control_object_list.append(
                    MpcResultFactory.build_control_object_result(
                        object_id=sid,
                        object_type=HydroObjectType.PUMP_STATION.value,
                        target_value_list=[
                            ValueItem(value_type=MetricsCodes.WATER_FLOW, value=float(st_flow))
                        ] if st_flow is not None else [],
                    )
                )

                predicted_result_list.append(
                    self._build_station_predicted_result(
                        sid=sid,
                        st_front=st_front,
                        st_back=st_back,
                        st_flow=st_flow,
                        st_eff_val=st_eff_val,
                        st_action=st_action,
                        horizon_idx=i,
                    )
                )

            horizon_step_list.append(
                HorizonStep(
                    horizon_step=i + 1,
                    control_object_list=control_object_list,
                    predicted_result_list=predicted_result_list
                )
            )

        commands = self._build_station_flow_control_commands(
            horizon_step_list=horizon_step_list,
            current_step=step,
        )

        try:
            reporter = MpcPredictionResultReporter(sim_coordination_client=self.sim_coordination_client)
            reporter.publish_customize_report(
                source_agent_instance=self,
                mpc_task_state=self._ensure_mpc_task_state(step),
                horizon_step=horizon_step_list,
                plan_type="optimal"
            )

        except Exception as e:
            logger.error(f"MPC customize report publish failed: {e}")
            import traceback
            traceback.print_exc()

        if step >= self.system_config.horizon_hours - 1:
            delivered = self.cumulative_last_station_flow
            target_flow_hour = float(self.system_config.target_avg_flow_last_station) * float(self.system_config.horizon_hours)
            target_volume = target_flow_hour * 3600.0
            actual_volume = delivered * 3600.0
            completion_ratio = delivered / max(target_flow_hour, 1e-9)
            
            logger.info("")
            logger.info("========== 仿真汇总 ==========")
            logger.info(f"模拟时长: {self.system_config.horizon_hours}")
            logger.info(f"末站目标调水量(m3): {target_volume:.3f}")
            logger.info(f"末站实际调水量(m3): {actual_volume:.3f}")
            logger.info(f"完成率: {completion_ratio:.3f}")
            logger.info(f"叶片调节总次数: {self.total_blade_adjust_count}")
            logger.info(f"启机总次数: {self.total_startup_count}")
            logger.info(f"停机总次数: {self.total_shutdown_count}")

        return commands

    @staticmethod
    def _build_station_flow_control_commands(
        horizon_step_list: List[Any],
        current_step: int,
    ) -> List[Dict[str, Any]]:
        """将首个预测步的 PumpStation 水流目标转换为 edge 控制命令。

        ``control_object_list`` 是 MPC 的可执行控制事实；``predicted_result_list``
        仅用于展示和回放。本方法只消费第一个 horizon，避免把未来规划步提前
        下发到 edge。该 step 内的所有泵站目标归入同一 control group，由
        ``STATION_AGENT`` 的 remote DMPC 会话统一执行。
        """
        if not horizon_step_list:
            logger.warning("MPC 未生成 horizon 控制结果，跳过泵站水流指令下发")
            return []

        current_horizon = horizon_step_list[0]
        commands: List[Dict[str, Any]] = []
        for control_object in current_horizon.control_object_list or []:
            if (
                control_object.object_id is None
                or control_object.object_type != HydroObjectType.PUMP_STATION.value
            ):
                continue
            for target_value in control_object.target_value_list or []:
                if target_value.value_type != MetricsCodes.WATER_FLOW:
                    continue
                water_flow = target_value.numeric_value()
                if water_flow is None:
                    logger.warning(
                        "跳过非数值泵站水流控制目标: stationId=%s, targetValue=%s",
                        control_object.object_id,
                        target_value.value,
                    )
                    continue
                commands.append(
                    {
                        "target_agent_code": "GATE_STATION_AGENT",
                        "target_command_type": DeviceValueTypeEnum.WATER_FLOW.code,
                        "target_value": str(round(water_flow, 2)),
                        "object_id": int(control_object.object_id),
                        "object_type": control_object.object_type,
                    }
                )

        if not commands:
            logger.warning("首个 MPC horizon 没有可下发的 PumpStation water_flow 控制目标")
            return []

        group_id = f"pump-station-flow:{current_step}"
        for command in commands:
            command["group_id"] = group_id
            command["group_size"] = len(commands)
            command["main_step_index"] = current_step

        logger.info(
            "生成了 %s 条 PumpStation water_flow 控制指令准备下发: groupId=%s",
            len(commands),
            group_id,
        )
        return commands

    def _get_current_scheduling_step(self) -> int:
        if hasattr(self, "_outer_step"):
            return self._outer_step
        return self._current_step

    def _get_total_scheduling_steps(self) -> int:
        if hasattr(self, "system_config"):
            return self.system_config.horizon_hours
        return 0

    def _ensure_mpc_task_state(self, step: int) -> MpcTaskState:
        return self._mpc_task_state_lifecycle.ensure_task_state(step)

    def _activate_mpc_task_state_from_event(
        self,
        event,
        step: Optional[int] = None,
    ) -> Optional[MpcTaskState]:
        task_state = self._mpc_task_state_lifecycle.activate_from_event(event, step=step)
        if task_state is None:
            return None

        logger.info(
            "Pump scheduling task state activated: bizSceneInstanceId=%s, currentStep=%s, eventSource=%s, timeSeriesCount=%s",
            self.context.biz_scene_instance_id,
            task_state.current_step,
            getattr(event, "hydro_event_source_type", None),
            len(getattr(event, "object_time_series", None) or []),
        )
        return task_state


    def _build_station_predicted_result(
        self,
        sid: int,
        st_front,
        st_back,
        st_flow,
        st_eff_val,
        st_action,
        horizon_idx: int,
    ):
        """为单个站点的一个 horizon step 构造符合契约的 PredictedResult。

        输出符合 MpcResultContractModel 结构：
        - predicted_value_list：front_water_level、back_water_level、out_flow、efficiency
        - target_value：water_flow 表示站点目标流量
        - device_result_list：各泵组的 blade_angle、flow、efficiency
        """
        from hydros_agent_sdk.mpc.models import ValueItem, DeviceResult

        # --- 查询站点名称 ---
        station_name = None
        unit_name_map = {}
        if hasattr(self, "system_config") and hasattr(self.system_config, "stations"):
            for station in self.system_config.stations:
                if station.id == sid:
                    station_name = station.name
                    for unit in getattr(station, "units", []):
                        unit_name_map[unit.id] = getattr(unit, "name", None)
                    break

        # --- 站点预测值列表 ---
        predicted_value_list = []
        if st_front is not None:
            predicted_value_list.append(
                ValueItem(value_type="front_water_level", value=float(st_front))
            )
        if st_back is not None:
            predicted_value_list.append(
                ValueItem(value_type="back_water_level", value=float(st_back))
            )
        if st_flow is not None:
            predicted_value_list.append(
                ValueItem(value_type="out_flow", value=float(st_flow))
            )
        if st_eff_val is not None:
            predicted_value_list.append(
                ValueItem(value_type="efficiency", value=float(st_eff_val))
            )

        # --- 站点级流量目标 ---
        target_value = None
        if st_flow is not None:
            target_value = ValueItem(
                value_type="water_flow", value=float(st_flow)
            )

        # --- 设备结果列表：各泵组预测值 ---
        device_result_list = []
        for uid in self._device_ids_for_station(sid, st_action):
            uv_list = []

            # 根据预测开度生成叶片角
            blade_angle = self._get_predicted_value(
                st_action, "predicted_unit_openings", uid, horizon_idx
            )
            if blade_angle is not None:
                uv_list.append(ValueItem(value_type="blade_angle", value=float(blade_angle)))

            # 泵组流量
            # u_flow = self._get_predicted_value(
            #     st_action, "predicted_unit_flows", uid, horizon_idx
            # )
            # if u_flow is not None:
            #     uv_list.append(ValueItem(value_type="flow", value=float(u_flow)))

            # 泵组效率
            # u_eff = self._get_predicted_value(
            #     st_action, "predicted_unit_efficiencies", uid, horizon_idx
            # )
            # if u_eff is not None:
            #     uv_list.append(ValueItem(value_type="efficiency", value=float(u_eff)))

            if uv_list:
                device_result_list.append(
                    DeviceResult(
                        object_id=int(uid),
                        object_type="PUMP",
                        object_name=unit_name_map.get(uid),
                        value_list=uv_list,
                    )
                )

        return MpcResultFactory.build_predicted_result(
            object_id=int(sid),
            object_type="PUMP_STATION",
            predicted_value_list=predicted_value_list,
            target_value=target_value,
            object_name=station_name,
            device_result_list=device_result_list if device_result_list else None,
        )

    @staticmethod
    def _device_ids_for_station(sid: int, st_action) -> list:
        """从站点动作中收集泵组 ID。"""
        ids = []
        for attr in ("unit_openings", "predicted_unit_openings", "unit_status"):
            mapping = getattr(st_action, attr, None)
            if isinstance(mapping, dict):
                ids.extend(mapping.keys())
        return list(dict.fromkeys(ids))  # 去重并保持原有顺序

    @staticmethod
    def _get_predicted_value(st_action, attr_name: str, uid: int, horizon_idx: int):
        """安全读取某个泵组在指定 horizon index 的预测值。"""
        mapping = getattr(st_action, attr_name, None)
        if not isinstance(mapping, dict):
            return None
        values = mapping.get(uid)
        if not values or horizon_idx >= len(values):
            return None
        return values[horizon_idx]


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
        self._activate_mpc_task_state_from_event(event)
        
        from hydros_agent_sdk.protocol.hydro_event_type import AgentEventType
        
        event_source_type = getattr(event, "hydro_event_source_type", "")
        from hydros_agent_sdk.protocol.hydro_event_type import AgentEventType
        val = getattr(event_source_type, "value", event_source_type) if event_source_type else ""
        is_water_use = (val == getattr(AgentEventType, "WATER_USE", "WATER_USE") or val == "WATER_USE")
        is_weather_forecast = (val == getattr(AgentEventType, "WEATHER_FORECAST", "WEATHER_FORECAST") or val == "WEATHER_FORECAST")

        outer_step = getattr(self, "_outer_step", 0)

        if is_water_use and hasattr(self, "_disturbance_node_to_col") and hasattr(self, "global_demand_plan"):
            
            for obj_ts in event.object_time_series:
                raw_values = [getattr(ts_val, "value", None) for ts_val in obj_ts.time_series] if obj_ts.time_series else []
                
                candidate_keys = [
                    str(getattr(obj_ts, "object_id", "")),
                    str(getattr(obj_ts, "object_name", "")),
                ]
                col_name = None
                for key in candidate_keys:
                    if not key:
                        continue
                    col_name = self._disturbance_sensor_key_to_col.get(key)
                    if col_name:
                        break
                    col_name = self._disturbance_node_to_col.get(key)
                    if not col_name and key.isdigit() and hasattr(self, "_pool_id_to_col"):
                        col_name = self._pool_id_to_col.get(int(key))
                    if col_name:
                        break
                        
                if col_name:
                    logger.info("==========【时间序列更新 - 并入需水计划(WATER_USE)】==========")
                    logger.info(f"当前外层步数(outer_step): {outer_step}")
                    logger.info(f"成功将对象匹配到拓扑边界: {obj_ts.object_name} (ID: {obj_ts.object_id}) -> {col_name}")
                    logger.info(f"原始数组序列: {raw_values}")
                    
                    if not obj_ts.time_series:
                        logger.info("==================================================")
                        continue
                        
                    for idx, ts_val in enumerate(obj_ts.time_series):
                        target_idx = getattr(ts_val, "step", None)
                        if target_idx is None:
                            target_idx = outer_step + idx
                        else:
                            target_idx = outer_step + int(target_idx)
                        target_idx = int(target_idx)
                        
                        # 动态扩展 DataFrame
                        if target_idx >= len(self.global_demand_plan):
                            import pandas as pd
                            expand_len = max(100, target_idx - len(self.global_demand_plan) + 1)
                            new_df = pd.DataFrame(0.0, index=range(len(self.global_demand_plan), len(self.global_demand_plan) + expand_len), columns=self.global_demand_plan.columns)
                            self.global_demand_plan = pd.concat([self.global_demand_plan, new_df], ignore_index=True)
                            self._sync_dynamic_demand_plan()
                            
                        # 强制正负号转换（反转符号），不设置多余的判断条件
                        self.global_demand_plan.loc[target_idx, col_name] += -float(ts_val.value)
                        
                    logger.info(f"已成功将事件并入当前预测范围的用水计划中 (当前外层步数: {outer_step})")
                    logger.info("当前外层需水计划表 (global_demand_plan):")
                    logger.info("\n" + str(self.global_demand_plan.head(outer_step + self.system_config.horizon_hours)))
                    logger.info("==================================================")
                else:
                    logger.info("==========【时间序列更新 - 未映射指标】==========")
                    logger.info(f"对象 {obj_ts.object_name} 的指标 {obj_ts.metrics_code} 已更新 (未配置到边界扰动映射中)")
                    logger.info(f"原始数组序列: {raw_values}")
                    logger.info("================================================")
                    
        elif is_weather_forecast and hasattr(self, "_disturbance_node_to_col") and hasattr(self, "global_rain_plan"):
            for obj_ts in event.object_time_series:
                raw_values = [getattr(ts_val, "value", None) for ts_val in obj_ts.time_series] if obj_ts.time_series else []
                candidate_keys = [
                    str(getattr(obj_ts, "object_id", "")),
                    str(getattr(obj_ts, "object_name", "")),
                ]
                col_name = None
                for key in candidate_keys:
                    if not key: continue
                    col_name = self._disturbance_sensor_key_to_col.get(key) or self._disturbance_node_to_col.get(key)
                    if not col_name and key.isdigit() and hasattr(self, "_pool_id_to_col"):
                        col_name = self._pool_id_to_col.get(int(key))
                    if col_name: break
                        
                if col_name:
                    logger.info("==========【时间序列更新 - 并入降水预测(WEATHER_FORECAST)】==========")
                    logger.info(f"当前外层步数(outer_step): {outer_step}")
                    logger.info(f"将对象匹配到拓扑边界: {obj_ts.object_name} -> {col_name}")
                    
                    if not obj_ts.time_series:
                        continue
                        
                    for idx, ts_val in enumerate(obj_ts.time_series):
                        target_idx = getattr(ts_val, "step", None)
                        if target_idx is None:
                            target_idx = outer_step + idx
                        else:
                            target_idx = outer_step + int(target_idx)
                        target_idx = int(target_idx)
                        
                        if target_idx >= len(self.global_rain_plan):
                            import pandas as pd
                            expand_len = max(100, target_idx - len(self.global_rain_plan) + 1)
                            new_df = pd.DataFrame(0.0, index=range(len(self.global_rain_plan), len(self.global_rain_plan) + expand_len), columns=self.global_rain_plan.columns)
                            self.global_rain_plan = pd.concat([self.global_rain_plan, new_df], ignore_index=True)
                            self._sync_dynamic_demand_plan()
                            
                        self.global_rain_plan.loc[target_idx, col_name] += -float(ts_val.value)
                    
                    logger.info("==========================================================")

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
        self._activate_mpc_task_state_from_event(event)

        if event and event.object_time_series:
            # 2. 遍历并处理数据
            for obj_ts in event.object_time_series:

                # 打印部分数据供调试
                if obj_ts.time_series:
                    first_val = obj_ts.time_series[0]
                    logger.debug(f"  首个数据点: Step={first_val.step}, Value={first_val.value}")

            # 3. 更新优化模型的边界条件（让 MPC 能够感知到这些计划外的流量变化）
            self.on_boundary_condition_update(event.object_time_series)

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
        self.discard_control_execution_waiters()
        self._mpc_task_state_lifecycle.clear()
        self._agent_command_gateway.shutdown()
        self._optimization_model = None
        
        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False
        )
