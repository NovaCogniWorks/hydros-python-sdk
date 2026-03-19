"""
外发流量计划智能体示例

该示例展示了如何基于 OutflowPlanAgent 基类实现一个具体的外发流量计划智能体。
该智能体通过响应水文事件来执行流量计划计算。
"""

import logging
import os
import sys
from typing import Optional, List, Dict

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
from hydros_agent_sdk.agents import OutflowPlanAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    OutflowTimeSeriesRequest,
    OutflowTimeSeriesResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    ObjectTimeSeries,
    TimeSeriesValue,
)

# 配置日志（仅在直接作为脚本运行时）
if __name__ == "__main__":
    EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    try:
        env_config = load_env_config()
        hydros_cluster_id = env_config.get('hydros_cluster_id', 'default_cluster')
        hydros_node_id = env_config.get('hydros_node_id', 'LOCAL')
    except Exception:
        hydros_cluster_id = 'default_cluster'
        hydros_node_id = os.getenv("HYDROS_NODE_ID", "LOCAL")

    setup_logging(
        level=logging.INFO,
        hydros_cluster_id=hydros_cluster_id,
        hydros_node_id=hydros_node_id,
        console=True,
        log_file=os.path.join(LOG_DIR, "hydros.log"),
        use_rolling=True
    )

logger = logging.getLogger(__name__)


class MyOutflowPlanAgent(OutflowPlanAgent):
    """
    外发流量计划智能体的具体实现。

    该智能体的主要功能包括：
    1. 加载水网拓扑
    2. 初始化流量计划模型
    3. 响应外发流量时间序列请求
    4. 根据水文事件生成下泄流量计划
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
        """初始化外发流量计划智能体实例。"""
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

        # 拓扑对象
        self._topology = None

        logger.info(f"MyOutflowPlanAgent created: {agent_id}")

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        处理外发流量时间序列请求。

        该方法：
        1. 从请求中提取事件信息
        2. 执行外发流量计划计算逻辑
        3. 生成 ObjectTimeSeries 格式的结果
        4. 将响应发送回协调器
        """
        logger.info(f"Received OutflowTimeSeriesRequest, commandId={request.command_id}")
        logger.info(f"Event: {request.hydro_event}")

        try:
            # 执行下泄计划计算
            outflow_plans = self._execute_outflow_planning(request.hydro_event)

            logger.info(f"Outflow planning completed, produced {len(outflow_plans)} time series")

            # 构造响应
            response = OutflowTimeSeriesResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                outflow_time_series_map={"Gate": outflow_plans},
                broadcast=False
            )

            # 发送响应
            self.send_response(response)

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=OutflowTimeSeriesResponse 到MQTT Topic={self.sim_coordination_client.topic}"
            )

        except Exception as e:
            logger.error(f"Error in outflow planning: {e}", exc_info=True)
            raise

    def _execute_outflow_planning(self, hydro_event) -> List[ObjectTimeSeries]:
        """
        执行具体的外发流量计划逻辑。

        在这里实现具体的流量调度或计划算法。

        参数:
            hydro_event: 触发计划计算的水文事件

        返回:
            包含流量计划的时间序列列表 (ObjectTimeSeries)
        """
        logger.info("Executing outflow planning...")

        # 示例：生成模拟的流量计划数据
        outflow_plans = []

        # 从配置中获取计划时界（预测时长）
        planning_horizon = self.properties.get_property('planning_horizon', 24)

        # 为每个相关对象生成流量计划
        if self._topology:
            for top_obj in self._topology.top_objects[:3]:  # 示例：仅取前3个对象
                time_series_values = []

                for step in range(planning_horizon):
                    # 在此处编写具体的计划逻辑
                    # 例如：优化算法、预测模型、基于规则的计划等
                    planned_outflow = self._calculate_planned_outflow(top_obj, step, hydro_event)

                    time_series_values.append(
                        TimeSeriesValue(
                            step=step,
                            value=planned_outflow
                        )
                    )

                # 创建对象的时间序列结果
                outflow_plan = ObjectTimeSeries(
                    time_series_name=f"{top_obj.object_name}_outflow_plan",
                    object_id=top_obj.object_id,
                    object_type=top_obj.object_type,
                    object_name=top_obj.object_name,
                    metrics_code="planned_outflow",
                    time_series=time_series_values
                )

                outflow_plans.append(outflow_plan)

        logger.info(f"Generated {len(outflow_plans)} outflow plans")
        return outflow_plans

    def _calculate_planned_outflow(self, hydro_object, step: int, hydro_event) -> float:
        """
        计算特定对象在特定时间步长的计划流量。

        这是一个占位方法 - 请在此处实现实际的计划算法。
        """
        # 示例：简单的线性变化计划
        base_outflow = 100.0
        variation = step * 5.0

        return base_outflow + variation

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止外发流量计划智能体运行。

        该方法：
        1. 清理计划资源
        2. 在状态管理器中注销
        3. 返回终止响应
        """
        logger.info(f"Terminating outflow plan agent: {self.agent_id}")

        # 清理资源
        self._topology = None
        self._plan_config = {}

        # 在状态管理器中注销
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        logger.info(f"Outflow plan agent terminated: {self.agent_id}")

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False
        )


# ============================================================================
# 智能体工厂类
# ============================================================================

class OutflowPlanAgentFactory(HydroAgentFactory):
    """用于创建外发流量计划智能体实例的工厂。"""

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
        """创建一个新的外发流量计划智能体实例。"""
        return MyOutflowPlanAgent(
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


# ============================================================================
# 主入口
# ============================================================================

def main():
    """外发流量计划智能体的主入口函数。"""
    logger.info("=" * 80)
    logger.info("Starting Outflow Plan Agent")
    logger.info("=" * 80)

    try:
        # 加载配置
        env_config = load_env_config()
        agent_config = load_agent_config()

        # 提取配置参数
        mqtt_broker_url = env_config['mqtt_broker_url']
        mqtt_broker_port = env_config['mqtt_broker_port']
        mqtt_topic = env_config['mqtt_topic']
        hydros_cluster_id = env_config.get('hydros_cluster_id', 'default_cluster')
        hydros_node_id = env_config.get('hydros_node_id', 'LOCAL')

        agent_code = agent_config['agent_code']
        agent_type = agent_config['agent_type']
        agent_name = agent_config['agent_name']

        logger.info(f"Agent Code: {agent_code}")
        logger.info(f"Agent Type: {agent_type}")
        logger.info(f"MQTT Broker: {mqtt_broker_url}:{mqtt_broker_port}")
        logger.info(f"MQTT Topic: {mqtt_topic}")

        # 创建工厂和回调
        factory = OutflowPlanAgentFactory()
        callback = MultiAgentCallback(factory)

        # 创建协调客户端
        client = SimCoordinationClient(
            broker_url=mqtt_broker_url,
            broker_port=mqtt_broker_port,
            topic=mqtt_topic,
            callback=callback,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id
        )

        # 启动连接
        client.connect()
        logger.info("Outflow plan agent connected and ready")

        # 保持运行状态
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            client.disconnect()

    except Exception as e:
        logger.error(f"Failed to start outflow plan agent: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
