"""
本体仿真智能体示例。

本示例展示如何使用 OntologySimulationAgent 基类实现一个具体的本体仿真智能体。

该智能体通过基于规则的逻辑执行本体驱动水网仿真。
"""

import logging
import os
import sys
import time
from typing import Optional, List, Dict

# 将当前目录加入 Python 路径，便于导入 ontology_rule_engine
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
from hydros_agent_sdk.agents import OntologySimulationAgent
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
)
from hydros_agent_sdk.utils import HydroObjectUtilsV2
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics

# 导入示例本体规则引擎实现
from ontology_rule_engine import OntologyRuleEngine

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


class MyOntologySimulationAgent(OntologySimulationAgent):
    """
    本体仿真智能体的具体实现。

    该智能体会：
    1. 加载水网拓扑
    2. 初始化本体规则引擎
    3. 在每个 tick 执行基于本体的仿真
    4. 处理边界条件更新
    5. 通过 MQTT 输出指标
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
        """初始化本体仿真智能体。"""
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

        # 本体规则引擎
        self._rule_engine: Optional[OntologyRuleEngine] = None

        logger.info(f"MyOntologySimulationAgent created: {agent_id}")

    def _initialize_ontology_model(self):
        """
        带错误处理地初始化本体模型。

        该方法使用已加载拓扑初始化本体规则引擎。
        """
        logger.info("Initializing ontology model...")

        # 在错误上下文中创建本体规则引擎
        with AgentErrorContext(
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            self._rule_engine = OntologyRuleEngine()

        if ctx.has_error:
            logger.error(f"Failed to create rule engine: {ctx.error_message}")
            raise RuntimeError(f"Rule engine creation failed: {ctx.error_message}")

        # 从拓扑加载本体
        if self._topology:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code
            ) as ctx:
                self._rule_engine.load_ontology(self._topology)

            if ctx.has_error:
                logger.error(f"Failed to load ontology: {ctx.error_message}")
                raise RuntimeError(f"Ontology load failed: {ctx.error_message}")

            logger.info("Ontology model initialized with topology")
        else:
            logger.warning("No topology available for ontology model")

        # 带错误处理地从配置加载本体参数
        with AgentErrorContext(
            ErrorCodes.CONFIGURATION_LOAD_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            ontology_params = {
                'reasoning_mode': self.properties.get_property('reasoning_mode', 'forward_chaining'),
                'rule_file': self.properties.get_property('rule_file', None),
                'inference_depth': self.properties.get_property('inference_depth', 3),
            }

        if ctx.has_error:
            logger.warning(f"Failed to load parameters, using defaults: {ctx.error_message}")
            ontology_params = {
                'reasoning_mode': 'forward_chaining',
                'rule_file': None,
                'inference_depth': 3,
            }

        logger.info(f"Ontology parameters: {ontology_params}")

    def _execute_ontology_simulation(self, step: int) -> List[MqttMetrics]:
        """
        带完整错误处理地执行基于本体的仿真步。

        Args:
            step: 当前仿真步

        Returns:
            MqttMetrics 对象列表
        """
        logger.info(f"Executing ontology simulation for step {step}")

        if not self._rule_engine:
            logger.error("Ontology rule engine not initialized")
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

        # 带错误处理地应用本体规则
        with AgentErrorContext(
            ErrorCodes.SIMULATION_EXECUTION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            results = self._rule_engine.apply_rules(step, boundary_conditions)

        if ctx.has_error:
            logger.error(f"Ontology reasoning failed: {ctx.error_message}")
            return []

        logger.info(f"Ontology reasoning completed for step {step}")

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
        将推理结果转换为指标列表。

        Args:
            results: 推理结果 {object_id: {metrics_code: value}}

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


def main():
    """
    本体仿真智能体服务主入口。
    """
    # 获取脚本目录
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 加载环境配置
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
        agent_class=MyOntologySimulationAgent,
        config_file=CONFIG_FILE,
        env_config=env_config
    )

    # 创建统一回调
    callback = MultiAgentCallback()
    callback.register_agent_factory("ONTOLOGY_SIMULATION_AGENT", agent_factory)

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
        logger.info("Starting Ontology Simulation Agent Service")
        logger.info("="*70)
        logger.info(f"Environment config: {ENV_FILE}")
        logger.info(f"Agent config: {CONFIG_FILE}")
        logger.info(f"MQTT Broker: {BROKER_URL}:{BROKER_PORT}")
        logger.info(f"MQTT Topic: {TOPIC}")
        logger.info("="*70)

        sim_coordination_client.start()

        logger.info("Service started successfully!")
        logger.info("Ready to create ontology agent instances for incoming tasks...")
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
