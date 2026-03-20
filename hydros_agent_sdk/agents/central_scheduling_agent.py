"""
具备 MPC 优化能力的中央调度智能体。

该模块提供了 CentralSchedulingAgent 类，它扩展了 TickableAgent，
增加了模型预测控制（MPC）优化功能。
"""

import logging
from typing import Optional, List, Dict, Any
from abc import abstractmethod

from .tickable_agent import TickableAgent
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    AgentBizStatus,
    AgentDriveMode,
    ObjectTimeSeries,
)

logger = logging.getLogger(__name__)


class CentralSchedulingAgent(TickableAgent):
    """
    具备 MPC 优化能力的中央调度智能体。

    该智能体执行模型预测控制（MPC）优化：
    1. 在滚动优化时界（Rolling Horizon）上执行（步长周期的倍数）
    2. 通过 MQTT 订阅接收来自现地设备的实时指标
    3. 处理边界条件更新
    4. 执行 MPC 优化
    5. 发送智能体间的控制指令（未来实现）

    核心特性：
    - 滚动时界优化 (MPC)
    - 通过 MQTT 订阅实时现地指标
    - 边界条件处理
    - 基于优化的控制逻辑
    - 支持智能体间指令交互（未来支持）

    使用示例：
        ```python
        agent = CentralSchedulingAgent(
            sim_coordination_client=client,
            agent_id="CENTRAL_SCHEDULING_001",
            agent_code="CENTRAL_SCHEDULING_AGENT",
            agent_type="CENTRAL_SCHEDULING_AGENT",
            agent_name="Central Scheduling Agent",
            context=simulation_context,
            hydros_cluster_id="cluster_01",
            hydros_node_id="node_01",
            optimization_horizon=10  # 每 10 个 tick 优化一次
        )
        ```

    子类必须实现：
    - on_init(): 初始化智能体并加载优化模型
    - on_optimization(): 执行 MPC 优化逻辑
    - on_terminate(): 清理资源
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
        agent_biz_status: AgentBizStatus = AgentBizStatus.INIT,
        drive_mode: AgentDriveMode = AgentDriveMode.SIM_TICK_DRIVEN,
        agent_configuration_url: Optional[str] = None,
        **kwargs
    ):
        """
        初始化中央调度智能体。

        参数:
            sim_coordination_client: 必填的 MQTT 客户端
            agent_id: 唯一的智能体实例 ID
            agent_code: 智能体代码
            agent_type: 智能体类型
            agent_name: 智能体名称
            context: 仿真上下文
            hydros_cluster_id: 集群 ID
            hydros_node_id: 节点 ID
            optimization_horizon: 滚动优化周期（tick 数）
            agent_biz_status: 初始业务状态
            drive_mode: 智能体驱动模式（默认：SIM_TICK_DRIVEN）
            agent_configuration_url: 可选的配置 URL
            **kwargs: 其他关键字参数
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
            agent_biz_status=agent_biz_status,
            drive_mode=drive_mode,
            agent_configuration_url=agent_configuration_url,
            **kwargs
        )

        # MPC 配置
        self._optimization_horizon = optimization_horizon
        self._last_optimization_step = 0

        # 优化模型
        self._optimization_model = None
        self._topology = None

        # 实时指标缓存（来自现地设备）
        self._field_metrics_cache: Dict[str, Any] = {}

        # 用于现地指标的 MQTT 订阅主题
        self._metrics_subscription_topic = None

        logger.info(f"CentralSchedulingAgent initialized: {self.agent_id}")
        logger.info(f"Optimization horizon: {self._optimization_horizon} ticks")

    @abstractmethod
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        初始化中央调度智能体。

        子类应该：
        1. 使用 self.load_agent_configuration(request) 加载智能体配置
        2. 加载水网拓扑
        3. 初始化优化模型
        4. 通过 MQTT 订阅现地指标
        5. 在状态管理器中注册
        6. 返回 SimTaskInitResponse

        参数:
            request: 任务初始化请求

        返回:
            任务初始化响应
        """
        pass

    def subscribe_to_field_metrics(self, metrics_topic: str):
        """
        订阅 MQTT 主题以获取实时现地指标。

        该方法订阅现地设备发布其实时指标数据的主题。

        参数:
            metrics_topic: 现地指标的 MQTT 主题
        """
        logger.info(f"Subscribing to field metrics topic: {metrics_topic}")

        self._metrics_subscription_topic = metrics_topic

        # 使用 paho-mqtt 正确的方式将特定主题路由到回调
        self.sim_coordination_client.mqtt_client.message_callback_add(
            metrics_topic,
            lambda client, userdata, msg: self._on_field_metrics_received_wrapper(msg)
        )
        self.sim_coordination_client.mqtt_client.subscribe(metrics_topic)

        logger.info(f"Subscribed to field metrics: {metrics_topic}")

    def _on_field_metrics_received_wrapper(self, msg):
        """在调用业务逻辑回调之前解析 MQTT 消息负载的包装器。"""
        try:
            import json
            payload = json.loads(msg.payload.decode("utf-8"))
            self._on_field_metrics_received(msg.topic, payload)
        except Exception as e:
            logger.error(f"Error parsing field metrics payload on {msg.topic}: {e}")

    def _on_field_metrics_received(self, topic: str, payload: Dict[str, Any]):
        """
        通过 MQTT 接收现地指标的回调。

        当接收到现地指标时调用此方法。
        它更新内部缓存以用于优化。

        参数:
            topic: MQTT 主题
            payload: 指标负载
        """
        logger.debug(f"Received field metrics from topic: {topic}")

        try:
            # 提取指标信息
            object_id = payload.get('object_id')
            metrics_code = payload.get('metrics_code')
            value = payload.get('value')
            timestamp = payload.get('timestamp')

            if object_id and metrics_code:
                cache_key = f"{object_id}_{metrics_code}"
                self._field_metrics_cache[cache_key] = {
                    'object_id': object_id,
                    'metrics_code': metrics_code,
                    'value': value,
                    'timestamp': timestamp
                }

                logger.debug(f"Cached field metrics: {cache_key} = {value}")

        except Exception as e:
            logger.error(f"Error processing field metrics: {e}", exc_info=True)

    def on_tick_simulation(self, request: TickCmdRequest) -> Optional[List[MqttMetrics]]:
        """
        执行中央调度步骤。

        参数:
            request: 步进指令请求

        返回:
            要通过 MQTT 发送的 MqttMetrics 对象列表（可选）
        """
        logger.info(f"Central scheduling step {request.step}")

        try:
            # 检查是否应运行优化
            steps_since_last_optimization = request.step - self._last_optimization_step

            if steps_since_last_optimization >= self._optimization_horizon:
                logger.info(
                    f"Executing MPC optimization at step {request.step} "
                    f"(horizon: {self._optimization_horizon})"
                )

                # 执行优化
                control_commands = self.on_optimization(request.step)

                # 更新最后一次优化的步长
                self._last_optimization_step = request.step

                # 向智能体发送控制指令（未来实现）
                if control_commands:
                    self._send_control_commands(control_commands)

                logger.info(f"MPC optimization completed at step {request.step}")

            else:
                logger.debug(
                    f"Skipping optimization at step {request.step} "
                    f"(next optimization at step {self._last_optimization_step + self._optimization_horizon})"
                )

            # 返回可选指标
            return None

        except Exception as e:
            logger.error(f"Error in central scheduling step {request.step}: {e}", exc_info=True)
            return None

    @abstractmethod
    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        """
        执行 MPC 优化逻辑。

        子类必须实现此方法以执行其特定的 MPC 优化逻辑。

        参数:
            step: 当前仿真步长

        返回:
            发送给智能体的控制指令列表，或 None
            每个指令字典应包含：target_agent, command_type, parameters
        """
        pass

    def _send_control_commands(self, control_commands: List[Dict[str, Any]]):
        """
        向目标智能体发送控制指令。

        这是未来智能体间指令实现的占位符。

        参数:
            control_commands: 控制指令列表
        """
        logger.info(f"Sending {len(control_commands)} control commands to agents")

        for command in control_commands:
            target_agent = command.get('target_agent')
            command_type = command.get('command_type')
            parameters = command.get('parameters', {})

            logger.info(
                f"Control command: target={target_agent}, "
                f"type={command_type}, params={parameters}"
            )

            # TODO: 实现智能体间指令发送
            # 这将在未来版本中实现

    def get_field_metrics_value(
        self,
        object_id: int,
        metrics_code: str
    ) -> Optional[float]:
        """
        从缓存中获取现地指标值。

        参数:
            object_id: 对象 ID
            metrics_code: 指标代码

        返回:
            现地指标值，如果未找到则返回 None
        """
        cache_key = f"{object_id}_{metrics_code}"
        metrics_data = self._field_metrics_cache.get(cache_key)

        if metrics_data:
            return metrics_data.get('value')

        return None

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        处理优化的边界条件更新。

        该方法使用新的边界条件更新优化模型。

        参数:
            time_series_list: 更新后的时间序列数据列表
        """
        logger.info(f"Updating optimization model with {len(time_series_list)} boundary conditions")

        # 使用边界条件更新优化模型
        for time_series in time_series_list:
            logger.debug(
                f"Boundary condition: object={time_series.object_name}, "
                f"metrics={time_series.metrics_code}"
            )
            # TODO: 更新优化模型约束

    @abstractmethod
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止中央调度智能体。

        子类应该：
        1. 清理优化模型
        2. 取消订阅 MQTT 主题
        3. 从状态管理器中注销
        4. 返回 SimTaskTerminateResponse

        参数:
            request: 任务终止请求

        返回:
            任务终止响应
        """
        pass

    @property
    def optimization_horizon(self) -> int:
        """获取优化时界（tick 数）。"""
        return self._optimization_horizon

    @property
    def last_optimization_step(self) -> int:
        """获取最后一次优化步长。"""
        return self._last_optimization_step
