"""
数字孪生仿真智能体示例。

本示例展示如何使用 TwinsSimulationAgent 基类实现一个具体的数字孪生仿真智能体。

该智能体执行与真实系统同步的高保真水力仿真。
"""

import logging
import os
import sys
import time
from typing import Optional, List, Dict

from hydros_agent_sdk.utils.yaml_loader import YamlLoader

# 将当前目录加入 Python 路径，便于导入 hydraulic_solver
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    setup_logging,
    SimCoordinationClient,
    MultiAgentCallback,
    ErrorCodes,
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
)
from hydros_agent_sdk.config_loader import load_env_config
from hydros_agent_sdk.factory import HydroAgentFactory
from hydros_agent_sdk.agents import TwinsSimulationAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    ObjectTimeSeries,
    CommandStatus,
)
from hydros_agent_sdk.utils import HydroObjectUtilsV2
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics

# 导入示例水力求解器实现
from hydraulic_solver import HydraulicSolver

# 配置日志（仅在作为主脚本运行时）
# 被 multi_agent_launcher 导入时，日志已完成配置
if __name__ == "__main__":
    # 获取 examples 目录（当前脚本向上两级）
    EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    # 部署身份必须来自 env.properties。
    env_config = load_env_config()
    hydros_cluster_id = env_config['hydros_cluster_id']
    hydros_node_id = env_config['hydros_node_id']

    setup_logging(
        level=logging.INFO,
        hydros_cluster_id=hydros_cluster_id,
        hydros_node_id=hydros_node_id,
        console=True,
        log_file=os.path.join(LOG_DIR, "hydros.log"),
        use_rolling=True
    )

logger = logging.getLogger(__name__)


class MyTwinsSimulationAgent(TwinsSimulationAgent):
    """
    数字孪生仿真智能体的具体实现。

    该智能体会：
    1. 加载水网拓扑
    2. 初始化水力求解器
    3. 在每个 tick 执行高保真仿真
    4. 处理来自外部源的边界条件更新
    5. 通过 MQTT 输出详细指标
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
        """初始化孪生仿真智能体。"""
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

        # 水力求解器
        self._hydraulic_solver: Optional[HydraulicSolver] = None

        logger.info(f"MyTwinsSimulationAgent created: {agent_id}")

    def _initialize_twins_model(self):
        """
        带错误处理地初始化数字孪生模型。

        该方法使用已加载拓扑初始化水力求解器。
        """
        logger.info("Initializing digital twins model...")
        idz_config_url = self.properties.get_property('idz_config_url')
        config = YamlLoader.from_url(idz_config_url)

        # 在错误上下文中创建水力求解器
        with AgentErrorContext(
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            self._hydraulic_solver = HydraulicSolver()

        if ctx.has_error:
            logger.error(f"Failed to create solver: {ctx.error_message}")
            raise RuntimeError(f"Solver creation failed: {ctx.error_message}")

        # 使用拓扑初始化求解器
        if self._topology:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code
            ) as ctx:
                self._hydraulic_solver.initialize(self._topology)

            if ctx.has_error:
                logger.error(f"Failed to initialize solver: {ctx.error_message}")
                raise RuntimeError(f"Solver initialization failed: {ctx.error_message}")

            logger.info("Hydraulic solver initialized with topology")
        else:
            logger.warning("No topology available for hydraulic solver")

        # 带错误处理地从配置加载求解器参数
        with AgentErrorContext(
            ErrorCodes.CONFIGURATION_LOAD_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            solver_params = {
                'time_step': self.properties.get_property('time_step', 60),  # 秒
                'convergence_tolerance': self.properties.get_property('convergence_tolerance', 1e-6),
                'max_iterations': self.properties.get_property('max_iterations', 100),
            }

        if ctx.has_error:
            logger.warning(f"Failed to load parameters, using defaults: {ctx.error_message}")
            solver_params = {
                'time_step': 60,
                'convergence_tolerance': 1e-6,
                'max_iterations': 100,
            }

        logger.info(f"Hydraulic solver parameters: {solver_params}")

    def _execute_twins_simulation(self, step: int) -> List[MqttMetrics]:
        """
        带完整错误处理地执行数字孪生仿真步。

        Args:
            step: 当前仿真步

        Returns:
            MqttMetrics 对象列表
        """
        logger.info(f"Executing digital twins simulation for step {step}")

        if not self._hydraulic_solver:
            logger.error("Hydraulic solver not initialized")
            return []

        # 带错误处理地采集边界条件
        with AgentErrorContext(
            ErrorCodes.BOUNDARY_CONDITION_ERROR,
            agent_name=self.agent_code
        ) as ctx:
            boundary_conditions = self._collect_boundary_conditions(step)

        if ctx.has_error:
            logger.error(f"Failed to collect boundary conditions: {ctx.error_message}")
            # 使用空边界条件兜底
            boundary_conditions = {}

        logger.debug(f"Boundary conditions: {len(boundary_conditions)} objects")

        # 带错误处理地执行水力求解器
        with AgentErrorContext(
            ErrorCodes.SIMULATION_EXECUTION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            results = self._hydraulic_solver.solve_step(step, boundary_conditions)

        if ctx.has_error:
            logger.error(f"Hydraulic solver failed: {ctx.error_message}")
            return []

        logger.info(f"Hydraulic solver completed for step {step}")

        # 带错误处理地将结果转换为指标
        with AgentErrorContext(
            ErrorCodes.METRICS_GENERATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            metrics_list = self._convert_results_to_metrics(results)

        if ctx.has_error:
            logger.error(f"Failed to convert results: {ctx.error_message}")
            return []

        logger.info(f"Generated {len(metrics_list)} metrics for step {step}")

        return metrics_list

    def _collect_boundary_conditions(self, step: int) -> Dict[int, Dict[str, float]]:
        """
        从时序缓存采集边界条件。

        Args:
            step: 当前仿真步

        Returns:
            边界条件 {object_id: {metrics_code: value}}
        """
        boundary_conditions = {}

        # 从配置获取边界条件指标编码
        bc_metrics = self.properties.get_property(
            'boundary_condition_metrics',
            ['inflow', 'upstream_water_level']
        )

        # 采集全部对象的边界条件
        if self._topology:
            for top_obj in self._topology.top_objects:
                for child in top_obj.children:
                    object_bc = {}

                    for metrics_code in bc_metrics:
                        # 从时间序列缓存获取值
                        value = self.time_series_cache.get_value(
                            child.object_id,
                            metrics_code,
                            step
                        )

                        if value is not None:
                            object_bc[metrics_code] = value

                    if object_bc:
                        boundary_conditions[child.object_id] = object_bc

        return boundary_conditions

    def _convert_results_to_metrics(
        self,
        results: Dict[int, Dict[str, float]]
    ) -> List[MqttMetrics]:
        """
        将求解器结果转换为指标列表。

        Args:
            results: 求解器结果 {object_id: {metrics_code: value}}

        Returns:
            MqttMetrics 对象列表
        """
        metrics_list = []

        object_names = {}
        if self._topology:
            for top_obj in self._topology.top_objects:
                for child in top_obj.children:
                    object_names[child.object_id] = child.object_name

        for object_id, values in results.items():
            object_name = object_names.get(object_id, f"Object_{object_id}")
            for metrics_code, value in values.items():
                metrics_list.append(create_mock_metrics(
                    source_id=self.agent_code,
                    job_instance_id=self.biz_scene_instance_id,
                    object_id=object_id,
                    object_name=object_name,
                    step_index=self._current_step,
                    metrics_code=metrics_code,
                    value=value
                ))

        return metrics_list

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        带错误处理地处理边界条件更新。

        外部边界条件更新时会调用该方法，例如来自现地测量、天气预报等。

        Args:
            time_series_list: 已更新的时序数据列表
        """
        logger.info(f"Updating digital twins with {len(time_series_list)} boundary conditions")

        # 带错误处理地记录边界条件更新
        for time_series in time_series_list:
            try:
                logger.info(
                    f"Boundary condition update: "
                    f"object={time_series.object_name}, "
                    f"metrics={time_series.metrics_code}, "
                    f"values={len(time_series.time_series)}"
                )

                # 如有需要则更新仿真状态
                if self._simulation_state and time_series.object_id:
                    state_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._simulation_state[state_key] = time_series

                    logger.debug(f"Updated simulation state: {state_key}")

            except Exception as e:
                logger.error(
                    f"Error updating boundary condition for {time_series.object_name}: {e}",
                    exc_info=True
                )
                # 继续处理其他更新


def main():
    """
    孪生仿真智能体服务主入口。
    """
    # 获取脚本目录
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 加载环境配置（支持回退到共享配置）
    ENV_FILE = os.path.join(script_dir, "env.properties")
    env_config = load_env_config(ENV_FILE)

    BROKER_URL = env_config['mqtt_broker_url']
    BROKER_PORT = int(env_config['mqtt_broker_port'])
    TOPIC = env_config['mqtt_topic']
    MQTT_USERNAME = env_config.get('mqtt_username')
    MQTT_PASSWORD = env_config.get('mqtt_password')

    # 智能体配置文件
    CONFIG_FILE = os.path.join(script_dir, "agent.properties")

    # 使用通用 HydroAgentFactory 创建智能体工厂
    agent_factory = HydroAgentFactory(
        agent_class=MyTwinsSimulationAgent,
        config_file=CONFIG_FILE,
        env_config=env_config
    )

    # 创建统一回调
    callback = MultiAgentCallback()
    callback.register_agent_factory("TWINS_SIMULATION_AGENT", agent_factory)

    # 创建协调客户端
    sim_coordination_client = SimCoordinationClient(
        broker_url=BROKER_URL,
        broker_port=BROKER_PORT,
        topic=TOPIC,
        sim_coordination_callback=callback,
        mqtt_username=MQTT_USERNAME,
        mqtt_password=MQTT_PASSWORD
    )

    # 设置客户端引用
    callback.set_client(sim_coordination_client)

    # 启动服务
    try:
        logger.info("="*70)
        logger.info("Starting Digital Twins Simulation Agent Service")
        logger.info("="*70)
        logger.info(f"Environment config: {ENV_FILE}")
        logger.info(f"Agent config: {CONFIG_FILE}")
        logger.info(f"MQTT Broker: {BROKER_URL}:{BROKER_PORT}")
        logger.info(f"MQTT Topic: {TOPIC}")
        logger.info("="*70)

        sim_coordination_client.start()

        logger.info("Service started successfully!")
        logger.info("Ready to create twins agent instances for incoming tasks...")
        logger.info("Press Ctrl+C to stop...")

        # 保持运行
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Stopping service...")
        sim_coordination_client.stop()
        logger.info("Service stopped")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sim_coordination_client.stop()


if __name__ == "__main__":
    main()
