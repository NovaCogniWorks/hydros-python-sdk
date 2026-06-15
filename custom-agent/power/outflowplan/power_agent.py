"""
中央调度电力智能体。

该智能体为电力系统实现模型预测控制（MPC）优化。它继承
MpcCentralSchedulingAgent，并提供发电和配电调度的优化逻辑。

该智能体会：
1. 加载电力系统拓扑
2. 初始化电力调度优化模型
3. 订阅现地指标（发电、用电等）
4. 在指定滚动视界执行 MPC 优化
5. 向电力系统组件发送控制指令
"""

import logging
import os
import sys
import time
from typing import Optional, List, Dict, Any

# 将当前目录加入 Python 路径，便于按需导入 power_solver
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
from hydros_agent_sdk.agents import MpcCentralSchedulingAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    ObjectTimeSeries,
)
from hydros_agent_sdk.utils import HydroObjectUtilsV2

# 尝试导入可用的电力优化求解器
try:
    from power_solver import PowerOptimizationSolver
    HAS_POWER_SOLVER = True
except ImportError:
    HAS_POWER_SOLVER = False
    PowerOptimizationSolver = None

# 配置日志（仅在作为主脚本运行时）
# 被 multi_agent_launcher 导入时，日志已完成配置
if __name__ == "__main__":
    # 获取项目目录（当前脚本向上两级）
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    EXAMPLES_DIR = os.path.join(PROJECT_DIR, "examples")
    LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    # 加载 env 配置，用于获取日志中的 cluster_id 和 node_id
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


class PowerSchedulingAgent(MpcCentralSchedulingAgent):
    """
    面向电力系统的中央调度智能体具体实现。

    该智能体会：
    1. 加载电力系统拓扑
    2. 初始化电力优化模型
    3. 订阅现地指标（发电、负荷等）
    4. 执行电力调度 MPC 优化
    5. 向发电机和负荷发送控制指令
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
        """初始化电力调度智能体。"""
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

        # 电力优化求解器
        self._power_solver: Optional[PowerOptimizationSolver] = None

        # 电力系统拓扑
        self._topology = None

        # 优化参数
        self._optimization_params = {}

        logger.info(f"PowerSchedulingAgent created: {agent_id}")

    def _planning_horizon_steps(self) -> int:
        return self._mpc_rolling_runtime.get_roll_steps()

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        """
        带错误处理地初始化电力调度智能体。

        Args:
            request: 任务初始化请求

        Returns:
            任务初始化响应
        """
        logger.info("Initializing power scheduling agent...")

        # 1. 加载智能体配置（不在 agent_list 中则跳过）
        self.load_agent_configuration(request)

        # 2. 如果配置了拓扑，则加载电力系统拓扑
        topology_url = self.properties.get_property('hydros_objects_modeling_url')
        if topology_url:
            logger.info(f"Loading power system topology from: {topology_url}")

            success, topology, error_msg = safe_execute(
                HydroObjectUtilsV2.build_waterway_topology,
                ErrorCodes.TOPOLOGY_LOAD_FAILURE,
                self.agent_code,
                topology_url
            )

            if success:
                self._topology = topology
                logger.info(f"Power system topology loaded: {len(topology.top_objects)} top objects")
            else:
                logger.warning(f"Failed to load topology: {error_msg}")
                logger.warning("Continuing without topology...")

        # 3. 初始化电力优化求解器
        logger.info("Initializing power optimization solver...")

        if HAS_POWER_SOLVER:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code
            ) as ctx:
                self._power_solver = PowerOptimizationSolver()
                if self._topology:
                    self._power_solver.initialize(self._topology)

            if ctx.has_error:
                logger.error(f"Failed to initialize power solver: {ctx.error_message}")
                # 无求解器时继续执行，后续使用模拟优化
                self._power_solver = None
            else:
                logger.info("Power optimization solver initialized")
        else:
            logger.warning("PowerOptimizationSolver not available, using dummy optimization")

        # 4. 加载优化参数
        self._optimization_params = {
            'time_horizon': self.properties.get_property('optimization_time_horizon', 24),  # 小时
            'time_step': self.properties.get_property('optimization_time_step', 1),  # 小时
            'objective': self.properties.get_property('optimization_objective', 'minimize_cost'),
            'constraints': self.properties.get_property('optimization_constraints', []),
        }
        logger.info(f"Optimization parameters: {self._optimization_params}")

        # 5. 订阅现地指标，获取实时电力数据
        metrics_topic = self.properties.get_property(
            'field_metrics_topic',
            f"/hydros/metrics/power/{self.hydros_cluster_id}"
        )

        try:
            self._metrics_subscriber.subscribe(metrics_topic)
            logger.info(f"Subscribed to field metrics: {metrics_topic}")
        except Exception as e:
            logger.warning(f"Failed to subscribe to metrics topic: {e}")

        # 6. 注册到状态管理器
        self.state_manager.init_task(self.context, [self])
        self.state_manager.add_local_agent(self)

        logger.info("Power scheduling agent initialized successfully")

        # 7. 返回初始化响应
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status="SUCCESS",
            source_agent_instance=self,
            created_agent_instances=[self],
            managed_top_objects={}
        )

    def on_optimization(self, step: int) -> Optional[List[Dict[str, Any]]]:
        """
        执行电力调度 MPC 优化。

        该方法实现核心优化逻辑：
        1. 采集当前系统状态（负荷、发电、约束）
        2. 收集现地指标（实时测量）
        3. 运行优化模型
        4. 生成面向电力系统组件的控制指令

        Args:
            step: 当前仿真步

        Returns:
            要发送给电力系统智能体的控制指令列表
        """
        logger.info(f"Executing power scheduling optimization at step {step}")

        # 1. 采集系统状态
        system_state = self._collect_system_state(step)
        logger.info(
            f"System state collected: {len(system_state.get('loads', []))} loads, "
            f"{len(system_state.get('generators', []))} generators"
        )

        # 2. 收集现地指标
        field_metrics = self._collect_field_metrics()
        logger.debug(f"Field metrics collected: {len(field_metrics)} measurements")

        # 3. 运行优化
        optimization_results = self._run_optimization(step, system_state, field_metrics)

        # 4. 生成控制指令
        control_commands = self._generate_control_commands(optimization_results)

        logger.info(f"Optimization completed: {len(control_commands)} control commands generated")

        return control_commands

    def _collect_system_state(self, step: int) -> Dict[str, Any]:
        """
        采集当前电力系统状态。

        Args:
            step: 当前仿真步

        Returns:
            包含系统状态信息的字典
        """
        system_state = {
            'step': step,
            'loads': [],
            'generators': [],
            'storage': [],
            'constraints': {},
        }

        # 如果有拓扑，则从拓扑提取信息
        if self._topology:
            for top_obj in self._topology.top_objects:
                for child in top_obj.children:
                    # 按类型划分对象
                    if 'load' in child.object_name.lower() or 'demand' in child.object_name.lower():
                        system_state['loads'].append({
                            'id': child.object_id,
                            'name': child.object_name,
                            'type': 'load',
                        })
                    elif 'gen' in child.object_name.lower() or 'generator' in child.object_name.lower():
                        system_state['generators'].append({
                            'id': child.object_id,
                            'name': child.object_name,
                            'type': 'generator',
                        })
                    elif 'storage' in child.object_name.lower() or 'battery' in child.object_name.lower():
                        system_state['storage'].append({
                            'id': child.object_id,
                            'name': child.object_name,
                            'type': 'storage',
                        })

        # 将边界条件作为约束加入
        constraints = self._collect_boundary_constraints(step)
        if constraints:
            system_state['constraints'] = constraints

        return system_state

    def _collect_boundary_constraints(self, step: int) -> Dict[str, Any]:
        """
        采集优化用边界约束。

        Args:
            step: 当前仿真步

        Returns:
            约束字典
        """
        constraints = {}

        # 示例：获取用于约束的时间序列数据
        # 真实数据会从 time_series_cache 填充
        constraint_metrics = ['max_generation', 'min_generation', 'max_load', 'min_load']

        for metric in constraint_metrics:
            # 这里是占位实现，真实实现应查询时间序列缓存
            constraints[metric] = None

        return constraints

    def _collect_field_metrics(self) -> Dict[str, float]:
        """
        从缓存采集现地指标。

        Returns:
            现地指标字典 {object_id_metric: value}
        """
        field_metrics = {}

        # 从现地指标缓存获取指标（由 MQTT 订阅填充）
        for cache_key, metrics_data in self._field_metrics_cache.items():
            field_metrics[cache_key] = metrics_data.get('value')

        return field_metrics

    def _run_optimization(
        self,
        step: int,
        system_state: Dict[str, Any],
        field_metrics: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        运行电力优化。

        Args:
            step: 当前仿真步
            system_state: 当前系统状态
            field_metrics: 现地测量值

        Returns:
            优化结果
        """
        # 如有可用电力求解器则使用
        if self._power_solver and HAS_POWER_SOLVER:
            try:
                logger.info("Running optimization with PowerOptimizationSolver")

                with AgentErrorContext(
                    ErrorCodes.SIMULATION_EXECUTION_FAILURE,
                    agent_name=self.agent_code
                ) as ctx:
                    results = self._power_solver.optimize(
                        step=step,
                        system_state=system_state,
                        field_metrics=field_metrics,
                        horizon=self._planning_horizon_steps(),
                        params=self._optimization_params
                    )

                if ctx.has_error:
                    logger.error(f"Optimization solver failed: {ctx.error_message}")
                    # 回退到模拟优化
                    return self._dummy_optimization(step, system_state, field_metrics)

                return results

            except Exception as e:
                logger.error(f"Error in optimization solver: {e}", exc_info=True)
                return self._dummy_optimization(step, system_state, field_metrics)
        else:
            # 使用模拟优化
            logger.info("Using dummy optimization (no solver available)")
            return self._dummy_optimization(step, system_state, field_metrics)

    def _dummy_optimization(
        self,
        step: int,
        system_state: Dict[str, Any],
        field_metrics: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        用于演示的模拟优化。

        Args:
            step: 当前仿真步
            system_state: 当前系统状态
            field_metrics: 现地测量值

        Returns:
            模拟优化结果
        """
        logger.debug("Running dummy optimization")

        # 简单规则调度
        results = {
            'step': step,
            'schedule': {},
            'total_cost': 0.0,
            'constraints_violated': False,
        }

        # 生成简单计划
        for generator in system_state.get('generators', []):
            gen_id = generator['id']
            results['schedule'][gen_id] = {
                'power_output': 50.0,  # 兆瓦
                'cost': 45.0,  # $/MWh
                'status': 'online',
            }

        for load in system_state.get('loads', []):
            load_id = load['id']
            results['schedule'][load_id] = {
                'power_demand': 30.0,  # 兆瓦
                'priority': 'normal',
                'sheddable': True,
            }

        results['total_cost'] = len(system_state.get('generators', [])) * 50.0 * 45.0

        return results

    def _generate_control_commands(
        self,
        optimization_results: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        根据优化结果生成控制指令。

        Args:
            optimization_results: 优化结果

        Returns:
            控制指令列表
        """
        control_commands = []

        schedule = optimization_results.get('schedule', {})

        # 为发电机生成指令
        for object_id, schedule_info in schedule.items():
            if 'power_output' in schedule_info:
                # 发电机控制指令
                command = {
                    'target_agent': f"GENERATOR_AGENT_{object_id}",
                    'command_type': 'SET_POWER_OUTPUT',
                    'parameters': {
                        'object_id': object_id,
                        'power_output': schedule_info['power_output'],
                        'step': optimization_results.get('step', 0),
                        'duration': self._planning_horizon_steps(),
                    }
                }
                control_commands.append(command)

            elif 'power_demand' in schedule_info:
                # 负荷控制指令
                command = {
                    'target_agent': f"LOAD_AGENT_{object_id}",
                    'command_type': 'SET_POWER_DEMAND',
                    'parameters': {
                        'object_id': object_id,
                        'power_demand': schedule_info['power_demand'],
                        'step': optimization_results.get('step', 0),
                        'sheddable': schedule_info.get('sheddable', False),
                    }
                }
                control_commands.append(command)

        logger.debug(f"Generated {len(control_commands)} control commands")

        return control_commands

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        """
        处理电力优化的边界条件更新。

        Args:
            time_series_list: 已更新的时序数据列表
        """
        logger.info(f"Updating power optimization with {len(time_series_list)} boundary conditions")

        for time_series in time_series_list:
            try:
                logger.info(
                    f"Power boundary condition update: "
                    f"object={time_series.object_name}, "
                    f"metrics={time_series.metrics_code}, "
                    f"values={len(time_series.time_series)}"
                )

                # 如有求解器，则更新优化模型约束
                if self._power_solver:
                    self._power_solver.update_constraints(
                        object_id=time_series.object_id,
                        metrics_code=time_series.metrics_code,
                        time_series=time_series.time_series
                    )

            except Exception as e:
                logger.error(
                    f"Error updating boundary condition for {time_series.object_name}: {e}",
                    exc_info=True
                )

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止电力调度智能体。

        Args:
            request: 任务终止请求

        Returns:
            任务终止响应
        """
        logger.info("Terminating power scheduling agent...")

        # 1. 清理电力求解器
        if self._power_solver:
            logger.info("Cleaning up power solver...")

        # 2. 清理状态管理器
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        # 3. 返回终止响应
        logger.info("Power scheduling agent termination complete")

        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status="SUCCESS",
            source_agent_instance=self
        )


def main():
    """
    电力调度智能体服务主入口。
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
        agent_class=PowerSchedulingAgent,
        config_file=CONFIG_FILE,
        env_config=env_config
    )

    # 创建统一回调
    callback = MultiAgentCallback(node_id=os.getenv("HYDROS_NODE_ID", "LOCAL"))
    callback.register_agent_factory("CENTRAL_SCHEDULING_AGENT_POWER01", agent_factory)

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
        logger.info("=" * 70)
        logger.info("Starting Power Scheduling Agent Service")
        logger.info("=" * 70)
        logger.info(f"Environment config: {ENV_FILE}")
        logger.info(f"Agent config: {CONFIG_FILE}")
        logger.info(f"MQTT Broker: {BROKER_URL}:{BROKER_PORT}")
        logger.info(f"MQTT Topic: {TOPIC}")
        logger.info("=" * 70)

        sim_coordination_client.start()

        logger.info("Service started successfully!")
        logger.info("Ready to create power scheduling agent instances for incoming tasks...")
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
