"""
中央调度智能体示例

本模块展示了如何基于 CentralSchedulingAgent 基类实现一个具体的中央调度智能体。
该智能体会在滚动时界（Rolling Horizon）上执行模型预测控制（MPC）优化。
"""

import logging
import os
import sys
from typing import Optional, List, Dict, Any

# 将当前目录添加到 Python 路径中
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    setup_logging,
    SimCoordinationClient,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
    load_agent_config,
    ErrorCodes,
    handle_agent_errors,
)
from hydros_agent_sdk.agents import CentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
)

logger = logging.getLogger(__name__)


class MyCentralSchedulingAgent(CentralSchedulingAgent):
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
        optimization_horizon: int = 5,
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

        # 1. 加载智能体配置 (从 agent.properties)
        self.load_agent_configuration(request)

        # 2. 初始化优化模型 (模拟)
        self._initialize_optimization_model()

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

        logger.info(f"中央调度智能体初始化成功: {self.agent_id}")

        # 将智能体状态更新为 ACTIVE (活动)
        object.__setattr__(self, 'agent_biz_status', AgentBizStatus.ACTIVE)

        return SimTaskInitResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={},
            broadcast=False
        )

    def _initialize_optimization_model(self):
        """
        初始化优化模型（模拟逻辑）。
        在实际应用中，这里会加载优化引擎（如 Gurobi, CPLEX 或自定义算法）。
        """
        logger.info("正在加载 MPC 优化模型...")
        self._optimization_model = {"status": "ready"}
        logger.info("优化模型已就绪")

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        """
        执行 MPC 优化逻辑。
        该方法由基类根据 optimization_horizon 自动触发。

        参数:
            step: 当前仿真步长
        
        返回:
            生成的控制指令列表，将发送给其他智能体
        """
        logger.info(f"--- 第 {step} 步：开始执行 MPC 滚动优化 ---")

        # 1. 获取输入数据（例如：从缓存中读取订阅到的水位数据）
        # water_level = self.get_field_metrics_value(101, "water_level")
        
        # 2. 调用优化算法（模拟运行）
        logger.info("求解器正在运行中...")
        
        # 3. 生成控制决策
        control_commands = [
            {
                "target_agent": "PUMP_AGENT_001",
                "command_type": "set_pump_speed",
                "parameters": {"speed": 85.5, "duration": 3600}
            },
            {
                "target_agent": "GATE_AGENT_002",
                "command_type": "set_gate_opening",
                "parameters": {"opening": 1.2}
            }
        ]

        logger.info(f"优化完成，生成了 {len(control_commands)} 条控制指令")
        return control_commands

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
        return MyCentralSchedulingAgent(
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
