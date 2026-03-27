"""
Digital Twins Simulation Agent Example

This example demonstrates how to implement a concrete digital twins simulation agent
using the TwinsSimulationAgent base class.

The agent performs high-fidelity hydraulic simulation synchronized with real-world systems.
"""

import logging
import os
import sys
import time
from typing import Optional, List, Dict

from hydros_agent_sdk.utils.yaml_loader import YamlLoader

# Add current directory to Python path for hydraulic_solver import
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    setup_logging,
    SimCoordinationClient,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
    ErrorCodes,
    handle_agent_errors,
    safe_execute,
    AgentErrorContext,
)
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

# Import example hydraulic solver implementation
from hydraulic_solver import HydraulicSolver

# Configure logging (only when running as main script)
# When imported by multi_agent_launcher, logging is already configured
if __name__ == "__main__":
    # Get the examples directory (two levels up from this script)
    EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    # Load env config to get cluster_id and node_id for logging
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


class MyTwinsSimulationAgent(TwinsSimulationAgent):
    """
    Concrete implementation of digital twins simulation agent.

    This agent:
    1. Loads water network topology
    2. Initializes hydraulic solver
    3. Executes high-fidelity simulation at each tick
    4. Handles boundary condition updates from external sources
    5. Outputs detailed metrics via MQTT
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
        """Initialize twins simulation agent."""
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

        # Hydraulic solver is managed by job_instance_id via class methods
        # Not storing instance variable, using HydraulicSolver.get_or_create() and HydraulicSolver.get()
        self._hydraulic_solver: Optional[HydraulicSolver] = None

        logger.info(f"MyTwinsSimulationAgent created: {agent_id}")

    def _initialize_twins_model(self):
        """
        Initialize digital twins model with error handling.

        This method initializes the hydraulic solver with the loaded topology.
        使用 biz_scene_instance_id (即 job_instance_id) 来支持多任务并发仿真。
        """
        logger.info("Initializing digital twins model...")
        idz_config_url = self.properties.get_property('idz_config_url')
        # config = YamlLoader.from_url(idz_config_url)

        # 使用 biz_scene_instance_id (即 job_instance_id) 获取或创建求解器
        # 这样可以支持多个任务并发运行，每个任务有独立的求解器实例
        with AgentErrorContext(
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            self._hydraulic_solver = HydraulicSolver.get_or_create(self.biz_scene_instance_id)

        if ctx.has_error:
            logger.error(f"Failed to create solver: {ctx.error_message}")
            raise RuntimeError(f"Solver creation failed: {ctx.error_message}")

        # Initialize solver with topology
        if self._topology:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code
            ) as ctx:
                self._hydraulic_solver.initialize(self._topology, idz_config_url)

            if ctx.has_error:
                logger.error(f"Failed to initialize solver: {ctx.error_message}")
                raise RuntimeError(f"Solver initialization failed: {ctx.error_message}")

            logger.info("Hydraulic solver initialized with topology")
        else:
            logger.warning("No topology available for hydraulic solver")

        # Load solver parameters from configuration with error handling
        with AgentErrorContext(
            ErrorCodes.CONFIGURATION_LOAD_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            solver_params = {
                'time_step': self.properties.get_property('time_step', 60),  # seconds
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
        Execute digital twins simulation step with comprehensive error handling.

        Args:
            step: Current simulation step

        Returns:
            List of MqttMetrics objects
        """
        logger.info(f"Executing digital twins simulation for step {step}")

        if not self._hydraulic_solver:
            logger.error("Hydraulic solver not initialized")
            return []

        # Collect boundary conditions with error handling
        with AgentErrorContext(
            ErrorCodes.BOUNDARY_CONDITION_ERROR,
            agent_name=self.agent_code
        ) as ctx:
            boundary_conditions = self._collect_boundary_conditions(step)

        if ctx.has_error:
            logger.error(f"Failed to collect boundary conditions: {ctx.error_message}")
            # Use empty boundary conditions as fallback
            boundary_conditions = {}

        logger.debug(f"Boundary conditions: {len(boundary_conditions)} objects")

        # Execute hydraulic solver with error handling
        with AgentErrorContext(
            ErrorCodes.SIMULATION_EXECUTION_FAILURE,
            agent_name=self.agent_code
        ) as ctx:
            results = self._hydraulic_solver.solve_step(step, boundary_conditions)

        if ctx.has_error:
            logger.error(f"Hydraulic solver failed: {ctx.error_message}")
            return []

        logger.info(f"Hydraulic solver completed for step {step}")

        # Convert results to metrics with error handling
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
        Collect boundary conditions from time series cache.

        Args:
            step: Current simulation step

        Returns:
            Boundary conditions {object_id: {metrics_code: value}}
        """
        boundary_conditions = {}

        # Get boundary condition metrics codes from configuration
        bc_metrics = self.properties.get_property(
            'boundary_condition_metrics',
            ['inflow', 'upstream_water_level']
        )

        # Collect boundary conditions for all objects
        if self._topology:
            for top_obj in self._topology.top_objects:
                for child in top_obj.children:
                    object_bc = {}

                    for metrics_code in bc_metrics:
                        # Get value from time series cache
                        value = self.get_time_series_value(
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
        Convert solver results to metrics list.

        根据节点类型决定发送策略：
        - DisturbanceNode（分水口、退水闸）：直接发送节点数据
        - Pipe、GateStation（倒虹吸、节制闸）：为每个断面发送数据

        Args:
            results: Solver results {object_id: {metrics_code: value}}

        Returns:
            List of MqttMetrics objects
        """
        metrics_list = []

        # 构建节点信息映射：{node_id: {type, name, cross_section_children}}
        node_info = {}
        cross_section_info = {}

        if self._topology:
            for top_obj in self._topology.top_objects:
                # 处理顶级对象
                node_info[top_obj.object_id] = {
                    'type': top_obj.object_type,
                    'name': top_obj.object_name,
                    'cross_section_children': []
                }

                cross_section_ids = []
                # 处理子对象
                for child in top_obj.children:
                    node_info[child.object_id] = {
                        'type': child.object_type,
                        'name': child.object_name,
                        'cross_section_children': []
                    }

                   
                    # 对于 Pipe 和 GateStation，收集断面信息
                    if top_obj.object_type in ['Pipe', 'GateStation']:
                        if child.object_type in ['CrossSection', 'CrossSectionNode']:
                                cross_section_ids.append(child.object_id)

                node_info[top_obj.object_id]['cross_section_children'] = cross_section_ids

        # 遍历结果，根据节点类型发送数据
        for node_id, values in results.items():
            if node_id not in node_info:
                logger.warning(f"Node {node_id} not found in topology, skipping")
                continue

            node_type = node_info[node_id]['type']

            if node_type in ['DisturbanceNode']:
                # 分水口、退水闸：直接发送节点数据
                self._send_disturbance_node_metrics(
                    node_id=node_id,
                    node_info=node_info[node_id],
                    values=values,
                    metrics_list=metrics_list
                )

            elif node_type in ['Pipe', 'GateStation']:
                # 倒虹吸、节制闸：为每个断面发送数据
                self._send_pipe_gate_metrics(
                    node_id=node_id,
                    node_info=node_info[node_id],
                    cross_section_info=cross_section_info,
                    values=values,
                    metrics_list=metrics_list
                )
            else:
                # 其他类型：直接发送节点数据
                self._send_default_metrics(
                    node_id=node_id,
                    node_info=node_info[node_id],
                    values=values,
                    metrics_list=metrics_list
                )

        return metrics_list

    def _send_disturbance_node_metrics(
        self,
        node_id: int,
        node_info: Dict,
        values: Dict[str, float],
        metrics_list: List[MqttMetrics]
    ):
        """
        发送 DisturbanceNode（分水口、退水闸）的指标数据

        Args:
            node_id: 节点ID
            node_info: 节点信息
            values: 指标值
            metrics_list: 指标列表（用于追加）
        """
        node_name = node_info['name']

        # 发送水位数据
        if 'water_level' in values or 'h_i_t' in values:
            water_level = values.get('water_level', values.get('h_i_t', 0))
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=node_id,
                object_name=node_name,
                step_index=self._current_step,
                metrics_code="water_level",
                value=water_level
            ))

        # 发送流量数据
        if 'water_flow' in values or 'qtot_i_t' in values or 'q_out' in values:
            water_flow = values.get('water_flow', values.get('qtot_i_t', values.get('q_out', 0)))
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=node_id,
                object_name=node_name,
                step_index=self._current_step,
                metrics_code="water_flow",
                value=water_flow
            ))

    def _send_pipe_gate_metrics(
        self,
        node_id: int,
        node_info: Dict,
        cross_section_info: Dict,
        values: Dict[str, float],
        metrics_list: List[MqttMetrics]
    ):
        """
        发送 Pipe/GateStation（倒虹吸、节制闸）的指标数据

        获取当前节点下的 cross_section_children 下的节点发送水位和流量数据：
        - 遍历 cross_section_children 列表
        - 为每个断面发送水位数据（使用节点的水位值）
        - 第一个断面发送入口流量，其他断面发送出口流量

        Args:
            node_id: 节点ID（Pipe或GateStation的ID）
            node_info: 节点信息
            cross_section_info: 断面信息映射 {cs_id: {name, parent_id, parent_type}}
            values: 指标值（节点级别的水位和流量数据）
            metrics_list: 指标列表（用于追加）
        """
        # 获取当前节点的 cross_section_children
        cross_section_ids = node_info.get('cross_section_children', [])

        if not cross_section_ids:
            logger.warning(f"Node {node_id} ({node_info['name']}) has no cross sections, sending as default node")
            self._send_default_metrics(node_id, node_info, values, metrics_list)
            return

        logger.info(f"Processing {node_info['name']}: found {len(cross_section_ids)} cross sections")

        # 提取节点级别的数据
        node_water_level = values.get('water_level', values.get('h_i_t', 0))
        q_in = values.get('q_in', values.get('water_flow', 0))
        q_out = values.get('q_out', values.get('water_flow', 0))

        # 遍历 cross_section_children，为每个断面发送数据
        for index, cs_id in enumerate(cross_section_ids):
            # 从 cross_section_info 中获取断面名称
            cs_info = cross_section_info.get(cs_id, {})
            cs_name = cs_info.get('name', f"CS_{cs_id}")

            logger.debug(f"  - Cross section {index + 1}: ID={cs_id}, Name={cs_name}")

            # 发送水位数据（所有断面使用相同的水位）
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=cs_id,  # 使用断面ID作为object_id
                object_name=cs_name,
                step_index=self._current_step,
                metrics_code="water_level",
                value=node_water_level
            ))

            # 根据断面索引决定发送入口流量还是出口流量
            if index == 0:
                # 第一个断面：发送入口流量
                flow_value = q_in
                logger.debug(f"    Sending inlet flow: {flow_value}")
            else:
                # 其他断面：发送出口流量
                flow_value = q_out
                logger.debug(f"    Sending outlet flow: {flow_value}")

            # 发送流量数据
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=cs_id,  # 使用断面ID作为object_id
                object_name=cs_name,
                step_index=self._current_step,
                metrics_code="water_flow",
                value=flow_value
            ))

    def _send_default_metrics(
        self,
        node_id: int,
        node_info: Dict,
        values: Dict[str, float],
        metrics_list: List[MqttMetrics]
    ):
        """
        发送默认类型的节点指标数据

        Args:
            node_id: 节点ID
            node_info: 节点信息
            values: 指标值
            metrics_list: 指标列表（用于追加）
        """
        node_name = node_info['name']

        for metrics_code, value in values.items():
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=node_id,
                object_name=node_name,
                step_index=self._current_step,
                metrics_code=metrics_code,
                value=value
            ))

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        Handle boundary condition updates with error handling.

        This method is called when external boundary conditions are updated
        (e.g., from field measurements, weather forecasts, etc.).

        Args:
            time_series_list: List of updated time series data
        """
        logger.info(f"Updating digital twins with {len(time_series_list)} boundary conditions")

        # Log boundary condition updates with error handling
        for time_series in time_series_list:
            try:
                logger.info(
                    f"Boundary condition update: "
                    f"object={time_series.object_name}, "
                    f"metrics={time_series.metrics_code}, "
                    f"values={len(time_series.time_series)}"
                )

                # Update simulation state if needed
                if self._simulation_state and time_series.object_id:
                    state_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._simulation_state[state_key] = time_series

                    logger.debug(f"Updated simulation state: {state_key}")

            except Exception as e:
                logger.error(
                    f"Error updating boundary condition for {time_series.object_name}: {e}",
                    exc_info=True
                )
                # Continue with other updates

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止数字孪生仿真代理并清理求解器资源。

        重写父类方法以添加 HydraulicSolver 的清理逻辑，使用 biz_scene_instance_id
        来移除对应任务的求解器实例，支持多任务并发场景下的资源管理。

        Args:
            request: 任务终止请求

        Returns:
            任务终止响应
        """
        logger.info("="*70)
        logger.info(f"TERMINATING DIGITAL TWINS SIMULATION AGENT: {self.biz_scene_instance_id}")
        logger.info("="*70)

        # 清理 HydraulicSolver 资源
        if hasattr(self, '_hydraulic_solver') and self._hydraulic_solver is not None:
            logger.info(f"Cleaning up hydraulic solver for job: {self.biz_scene_instance_id}")
            try:
                HydraulicSolver.remove(self.biz_scene_instance_id)
                self._hydraulic_solver = None
                logger.info("Hydraulic solver cleaned up successfully")
            except Exception as e:
                logger.error(f"Error cleaning up hydraulic solver: {e}", exc_info=True)

        # 调用父类的终止方法以执行其他清理
        return super().on_terminate(request)


def main():
    """
    Main entry point for twins simulation agent service.
    """
    # Get script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load environment configuration (with fallback to shared config)
    ENV_FILE = os.path.join(script_dir, "env.properties")
    env_config = load_env_config(ENV_FILE)

    BROKER_URL = env_config['mqtt_broker_url']
    BROKER_PORT = int(env_config['mqtt_broker_port'])
    TOPIC = env_config['mqtt_topic']
    MQTT_USERNAME = env_config.get('mqtt_username')
    MQTT_PASSWORD = env_config.get('mqtt_password')

    # Agent configuration file
    CONFIG_FILE = os.path.join(script_dir, "agent.properties")

    # Create agent factory using generic HydroAgentFactory
    agent_factory = HydroAgentFactory(
        agent_class=MyTwinsSimulationAgent,
        config_file=CONFIG_FILE,
        env_config=env_config
    )

    # Create unified callback
    callback = MultiAgentCallback(node_id=os.getenv("HYDROS_NODE_ID", "LOCAL"))
    callback.register_agent_factory("TWINS_SIMULATION_AGENT", agent_factory)

    # Create coordination client
    sim_coordination_client = SimCoordinationClient(
        broker_url=BROKER_URL,
        broker_port=BROKER_PORT,
        topic=TOPIC,
        sim_coordination_callback=callback,
        mqtt_username=MQTT_USERNAME,
        mqtt_password=MQTT_PASSWORD
    )

    # Set client reference
    callback.set_client(sim_coordination_client)

    # Start service
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

        # Keep running
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
