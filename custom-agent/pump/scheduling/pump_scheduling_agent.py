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
            self._lazy_init_odd_mpc()

            # 3. 订阅现地指标（从环境配置 env.properties 获取基础主题并渲染变量）
            env_config = load_env_config()
            base_metrics_topic = env_config.get('metrics_topic')
            if base_metrics_topic:
                # 手动替换 {hydros_cluster_id} 变量
                cluster_id = env_config.get('hydros_cluster_id')
                if not cluster_id:
                    cluster_id = 'default_cluster_25'
                    logger.warning("在 env_config 中未找到 'hydros_cluster_id' 参数，默认使用 'default_cluster_25'。")
                base_metrics_topic = base_metrics_topic.replace('{hydros_cluster_id}', cluster_id)

                # 从上下文获取业务场景实例 ID (biz_scene_instance_id)
                task_id = self.context.biz_scene_instance_id

                # 拼接完整主题实现任务隔离：base_topic/task_id
                full_metrics_topic = f"{base_metrics_topic.rstrip('/')}/{task_id}"

                logger.info(f"订阅渲染后的现地数据主题: {full_metrics_topic}")
                self._metrics_subscriber.subscribe(full_metrics_topic)

            # 4. 在状态管理器中注册
            self.state_manager.init_task(self.context, [self])
            self.state_manager.add_local_agent(self)

            # 5. 启动 agent command 客户端，后面就能直接发指令
            self.agent_command_gateway.start()

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
            self.agent_command_gateway.shutdown()
            raise


    def _lazy_init_odd_mpc(self):
        if hasattr(self, 'odd_initialized') and self.odd_initialized:
            return
            
        import os
        from odd_dmpc.config import load_runtime_context_from_payload
        from odd_dmpc.flow_service import FlowDepartService
        from odd_dmpc.local_controller import LocalController
        from odd_dmpc.observers import DisturbanceObserverBank
        from odd_dmpc.odd_supervisor import ODDSupervisor
        from odd_dmpc.upper_scheduler import UpperScheduler
        from odd_dmpc.types import LowerFeedback, StationMemory
        from odd_dmpc.environment import _boundary_plan_from_snapshot
        import pandas as pd
        
        # 从 agent_config（被加载到了 self.properties 中）获取载荷
        payload = dict(self.properties) if self.properties else {}
        if not payload or 'project' not in payload:
            logger.warning("Agent properties 似乎未正确加载或缺少项目字段，回退到默认的 'data/config_xhh.yaml'。")
            import yaml
            import os
            fallback_path = 'data/config_xhh.yaml'
            if not os.path.exists(fallback_path):
                fallback_path = './data/config_xhh.yaml'
            with open(fallback_path, 'r', encoding='utf-8') as f:
                payload = yaml.safe_load(f)
        context = load_runtime_context_from_payload(payload)
        self.system_config = context["system_config"]
        self.runtime = context["runtime"]
        
        self.odd_demand_plan = context["demand_plan"]
        
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
        
        self.current_up_levels = {station.id: float(station.level_back_min) for station in self.system_config.stations}
        self.current_down_levels = {station.id: float(station.level_front_min) for station in self.system_config.stations}
        
        self.odd_initialized = True
        self.upper_scheduler = UpperScheduler(
            self.system_config,
            self.odd_demand_plan,
            self.runtime,
            self.flow_service,
            pd.DataFrame() # this will be updated in on_optimization
        )


    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        self._lazy_init_odd_mpc()
        
        from odd_dmpc.types import EnvironmentObservation, StationMemory
        from odd_dmpc.local_controller import StationControlContext
        import pandas as pd
        
        from odd_dmpc.environment import _level_keys, _ordered_station_ids, resolve_pool_areas
        level_keys = _level_keys(self.system_config)
        station_ids = _ordered_station_ids(self.system_config)

        station_back_levels = self.current_up_levels
        station_front_levels = self.current_down_levels
        station_heads = {sid: self.current_up_levels[sid] - self.current_down_levels[sid] for sid in self.current_up_levels}
        
        basin_levels = {}
        if station_ids and level_keys:
            basin_levels[level_keys[0]] = station_front_levels.get(station_ids[0], 0.0)
            for i, sid in enumerate(station_ids):
                if i + 1 < len(level_keys):
                    basin_levels[level_keys[i + 1]] = station_back_levels.get(sid, 0.0)
        
        station_flows = {
            sid: (self.station_flow_history[sid][-1] if self.station_flow_history[sid] else 0.0)
            for sid in self.system_config.station_ids
        }
        
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
        
        # Init or update memories from our own self tracked state
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
                
        # Upper Scheduler
        demand_row = self.odd_demand_plan.iloc[min(max(step, 0), len(self.odd_demand_plan) - 1)]
        self.observers.update(
            prev_basin_levels=basin_levels,
            next_basin_levels=basin_levels, # for test_mpc simplicity, we don't have prev
            actual_flows=station_flows,
            demand_row=demand_row,
            prev_basin_volumes=None,
            next_basin_volumes=None,
            prev_basin_profiles=None,
            next_basin_profiles=None,
            defer_visibility=False,
            step_hours=float(self.system_config.dt_hours),
            pool_areas=pool_areas,
        )
        
        # Boundary plan
        boundary_levels_dict = {}
        for node in self.system_config.topology.boundary_nodes:
            key = str(node.mpc_key or node.id or node.hydro_node)
            if node.mpc_key and node.mpc_key in basin_levels:
                boundary_levels_dict[node.id] = basin_levels[node.mpc_key]
            else:
                boundary_levels_dict[node.id] = basin_levels.get(key, 0.0)
        
        if not boundary_levels_dict and level_keys:
            boundary_levels_dict["upstream"] = basin_levels.get(level_keys[0], 0.0)
            boundary_levels_dict["downstream"] = basin_levels.get(level_keys[-1], 0.0)
            
        from odd_dmpc.environment import _boundary_plan_from_snapshot
        boundary_level_plan = _boundary_plan_from_snapshot(self.system_config, boundary_levels_dict)
        self.upper_scheduler.boundary_level_plan = boundary_level_plan
        
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
        
        # First, pre-populate all transfer bundles so they are available for predictions
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
        for sid in self.system_config.station_ids:
            action = actions[sid]
            st_list = [action.unit_status.get(u, 0) for u in self.available_units_map[sid]]
            op_list = [action.unit_openings.get(u, 0.0) for u in self.available_units_map[sid]]
            eff_list = [0.0] * len(st_list) # mock effs
            lower_res[sid] = {
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
        self.agent_command_gateway.shutdown()
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
