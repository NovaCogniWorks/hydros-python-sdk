"""
Hydraulic Solver - Implementation using corelib HydroSimulator.

This implements a hydraulic simulation for digital twins using the corelib
HydroSimulator, which provides high-fidelity hydraulic calculations.

Reference: examples/agents/idz/test.py
"""

import logging
import os
from typing import Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote, urlparse, urlunparse
import threading

# Add current directory to path for local imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in __import__('sys').path:
    __import__('sys').path.insert(0, _SCRIPT_DIR)

# Add idz directory to path for corelib import
_idz_dir = os.path.join(os.path.dirname(__file__), '..', 'idz')
if _idz_dir not in __import__('sys').path:
    __import__('sys').path.insert(0, _idz_dir)

# Import corelib modules
from corelib.core.hydro_simulator import HydroSimulator
from simulation_states import DeviceControl, BoundaryState

logger = logging.getLogger(__name__)


class HydraulicSolver:
    """
    Hydraulic solver using corelib HydroSimulator.

    Workflow:
    1. Initialize: Create simulator, get initial states, set up controls and boundaries
    2. Solve Step: Execute one simulation step using the simulator

    Supports concurrent simulations via job_instance_id.
    """

    # 类级别的求解器字典，用于管理多个并发仿真
    # {job_instance_id: HydraulicSolver}
    _solvers: Dict[str, 'HydraulicSolver'] = {}
    _lock = threading.RLock()

    @classmethod
    def get_or_create(cls, job_instance_id: str) -> 'HydraulicSolver':
        """
        获取或创建指定 job_instance_id 的求解器实例。

        Args:
            job_instance_id: 任务实例ID

        Returns:
            HydraulicSolver 实例
        """
        with cls._lock:
            if job_instance_id not in cls._solvers:
                solver = cls(job_instance_id)
                cls._solvers[job_instance_id] = solver
                logger.info(f"创建新的求解器实例: {job_instance_id}")
            return cls._solvers[job_instance_id]

    @classmethod
    def remove(cls, job_instance_id: str) -> None:
        """
        移除指定 job_instance_id 的求解器实例。

        Args:
            job_instance_id: 任务实例ID
        """
        with cls._lock:
            if job_instance_id in cls._solvers:
                solver = cls._solvers.pop(job_instance_id)
                # 清理求解器资源
                if hasattr(solver, 'sim') and solver.sim:
                    try:
                        # 如果 HydroSimulator 有 cleanup 方法
                        if hasattr(solver.sim, 'cleanup'):
                            solver.sim.cleanup()
                    except Exception as e:
                        logger.warning(f"清理求解器资源时出错: {e}")

                # 删除 idz_config 配置文件
                cls._cleanup_idz_config(job_instance_id)

                logger.info(f"已移除求解器实例: {job_instance_id}")

    @classmethod
    def _cleanup_idz_config(cls, job_instance_id: str) -> None:
        """
        删除指定任务实例的 IDZ 配置文件。

        Args:
            job_instance_id: 任务实例ID
        """
        # 使用绝对路径，确保从任何目录都能找到文件
        # hydros-python-sdk/examples/data/idz_config_{job_instance_id}.yml
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.abspath(os.path.join(script_dir, "..", "..", "data"))
        filename = f"idz_config_{job_instance_id}.yml"
        file_path = os.path.join(data_dir, filename)

        logger.info(f"尝试删除 IDZ 配置文件: {file_path}")
        logger.info(f"当前工作目录: {os.getcwd()}")
        logger.info(f"文件是否存在: {os.path.exists(file_path)}")

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"✓ 已删除 IDZ 配置文件: {file_path}")
            else:
                logger.warning(f"IDZ 配置文件不存在: {file_path}")
                # 列出 data 目录中的所有文件以便调试
                try:
                    existing_files = [f for f in os.listdir(data_dir) if f.startswith("idz_config_")]
                    logger.info(f"现有的 idz_config 文件: {existing_files}")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"删除 IDZ 配置文件时出错: {e}", exc_info=True)

    @classmethod
    def get(cls, job_instance_id: str) -> Optional['HydraulicSolver']:
        """
        获取指定 job_instance_id 的求解器实例（不存在则返回 None）。

        Args:
            job_instance_id: 任务实例ID

        Returns:
            HydraulicSolver 实例或 None
        """
        with cls._lock:
            return cls._solvers.get(job_instance_id)

    def __init__(self, job_instance_id: str):
        """
        初始化液压求解器。

        Args:
            job_instance_id: 任务实例ID，用于标识并发仿真
        """
        self.job_instance_id = job_instance_id
        self.sim = None                # HydroSimulator 实例
        self.simulation_states = {}       # 当前仿真状态
        self.controls = {}               # 设备控制量
        self.boundary_params = {}         # 边界条件参数
        self.initial_states = {}          # 初始状态（用于重置）

        # 简单的状态映射（向后兼容）
        self.state = {}
        logger.info(f"Hydraulic solver initialized for job: {job_instance_id}")

    def initialize(self, topology, agent_configuration_url):
        """
        初始化算法及初始参数。

        步骤：
        1. 通过 agent_configuration_url 下载配置并获取 idz_config_url
        2. 下载 idz_config.yml 文件到 examples/data 目录
        3. 创建 HydroSimulator 仿真器
        4. 获取初始状态
        5. 构造设备控制量
        6. 构造边界条件参数

        Args:
            topology: 水网拓扑结构
            agent_configuration_url: 代理配置文件 URL
        """
        logger.info("Initializing hydraulic solver with topology")

        # ========== 第1步：下载代理配置并获取 idz_config_url ==========
        logger.debug("第1步：下载代理配置并获取 idz_config_url")
        idz_config_file = self._download_idz_config(agent_configuration_url)
        if not idz_config_file:
            # 下载yaml文件失败，抛出异常停止后续仿真
            error_msg = "无法下载 IDZ 配置文件，仿真初始化失败"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
            
        # ========== 第2步：创建仿真器 ==========
        logger.debug("第2步：创建仿真器")
        self.sim = HydroSimulator(idz_config_file)
        logger.info(f"✓ 仿真器创建成功，节点数量: {self.sim.num_nodes}")

        # ========== 第3步：获取初始状态 ==========
        logger.debug("第3步：获取初始状态")

        self.initial_states = self.sim.get_initial_states()
        self.simulation_states = self.sim.get_initial_states()
        logger.info(f"获取到 {len(self.simulation_states)} 个节点的初始状态")

        # 显示前3个节点的状态
        for node_id, state in list(self.simulation_states.items())[:3]:
            logger.debug(f"  节点{node_id}: h={state.station_state.h_i_t:.2f}m, "
                        f"qtot={state.station_state.qtot_i_t:.2f}m³/s")

        # ========== 第4步：构造控制量 ==========
        logger.debug("第4步：构造控制量")

        all_node_ids = sorted(self.simulation_states.keys())
        self.controls = {}

        for node_id in all_node_ids:
            state = self.simulation_states[node_id]
            self.controls[node_id] = {}

            # 为每个节点的每个设备创建控制量（默认开度65%）
            for device_name in state.device_states.keys():
                self.controls[node_id][device_name] = DeviceControl(
                    device_name=device_name,
                    e_i_t=65.0,  # 默认开度65%
                    n_i_t=1,
                )

        logger.info(f"构造了 {len(self.controls)} 个节点的控制量")
        logger.info("Hydraulic solver 初始化完成")

    def solve_step(
        self,
        step: int,
        boundary_conditions: Dict[int, Dict[str, float]]
    ) -> Dict[int, Dict[str, float]]:
        """
        执行当前步的仿真任务。

        步骤：
        1. 更新边界条件（根据输入参数）
        2. 调用 sim.step() 执行仿真
        3. 更新内部状态
        4. 返回仿真结果

        Args:
            step: 当前仿真步数
            boundary_conditions: 边界条件 {object_id: {metrics_code: value}}

        Returns:
            仿真结果 {object_id: {metrics_code: value}}
        """
        logger.debug(f"执行第 {step} 步仿真")

        # ========== 更新边界条件 ==========
        if boundary_conditions:
            for object_id, bc_values in boundary_conditions.items():
                if object_id in self.boundary_params:
                    # 更新上游边界
                    if 'upstream_boundary' in self.boundary_params[object_id]:
                        upstream = self.boundary_params[object_id]['upstream_boundary']
                        if 'h_i_t' in bc_values:
                            upstream.h_i_t = bc_values['h_i_t']
                        if 'Inflow_i_t' in bc_values:
                            upstream.Inflow_i_t = bc_values['Inflow_i_t']
                        if 'qtot_i_t' in bc_values:
                            upstream.qtot_i_t = bc_values['qtot_i_t']

                    # 更新下游边界
                    if 'downstream_boundary' in self.boundary_params[object_id]:
                        downstream = self.boundary_params[object_id]['downstream_boundary']
                        if 'h_i_t' in bc_values:
                            downstream.h_i_t = bc_values['h_i_t']
                        if 'Inflow_i_t' in bc_values:
                            downstream.Inflow_i_t = bc_values['Inflow_i_t']
                        if 'qtot_i_t' in bc_values:
                            downstream.qtot_i_t = bc_values['qtot_i_t']

            logger.debug(f"更新了 {len(boundary_conditions)} 个节点的边界条件")

        # ========== 执行仿真步骤 ==========
        try:
            new_states, results = self.sim.step(
                controls=self.controls,
                boundary_params=self.boundary_params,
                simulation_states=self.simulation_states
            )

            # 更新仿真状态（用于下一步）
            self.simulation_states = new_states

            # 转换仿真结果为标准格式
            output_results = {}
            for node_id, result in results.items():
                state = new_states[node_id]

                # 提取关键指标
                output_results[node_id] = {
                    'water_level': state.station_state.h_i_t,
                    'water_flow': state.station_state.qtot_i_t,
                    # 'gate_opening': 65.0,  # 默认开度
                }

            # 更新简单状态映射（向后兼容）
            for object_id in self.state:
                if object_id in output_results:
                    self.state[object_id].update({
                        'water_level': output_results[object_id]['water_level'],
                        'water_flow': output_results[object_id]['water_flow'],
                        # 'gate_opening': output_results[object_id]['gate_opening'],
                    })

            logger.info(f"✓ 第 {step} 步仿真完成，更新了 {len(output_results)} 个节点")
            return output_results

        except Exception as e:
            logger.error(f"第 {step} 步仿真失败: {e}")
            return {}

    def update_controls(self, controls_update: Dict[int, Dict[str, DeviceControl]]):
        """
        更新特定节点的设备控制量。

        Args:
            controls_update: 新控制量 {node_id: {device_name: DeviceControl}}
        """
        for node_id, device_controls in controls_update.items():
            if node_id not in self.controls:
                self.controls[node_id] = {}
            self.controls[node_id].update(device_controls)
        logger.info(f"更新了 {len(controls_update)} 个节点的控制量")

    def update_boundary_params(self, boundary_update: Dict[int, Dict[str, BoundaryState]]):
        """
        更新特定节点的边界条件参数。

        Args:
            boundary_update: 新边界条件 {node_id: {boundary_type: BoundaryState}}
        """
        for node_id, boundaries in boundary_update.items():
            if node_id not in self.boundary_params:
                self.boundary_params[node_id] = {}
            self.boundary_params[node_id].update(boundaries)
        logger.info(f"更新了 {len(boundary_update)} 个节点的边界条件")

    def _download_idz_config(self, agent_configuration_url: str) -> Optional[str]:
        """
        从代理配置 URL 下载 IDZ 配置文件。

        Args:
            agent_configuration_url: 代理配置文件 URL

        Returns:
            下载的 IDZ 配置文件路径，失败则返回 None
        """
        try:
            # 导入 AgentConfigLoader
            from hydros_agent_sdk.agent_config import AgentConfigLoader

            logger.info(f"加载代理配置: {agent_configuration_url}")
            agent_config = AgentConfigLoader.from_url(agent_configuration_url)

            # 获取 idz_config_url
            idz_config_url = agent_config.get_idz_config_url()
            if not idz_config_url:
                logger.warning("代理配置中未找到 idz_config_url")
                return None

            logger.info(f"找到 IDZ 配置 URL: {idz_config_url}")

            # 编码 URL 以处理非 ASCII 字符
            parsed = urlparse(idz_config_url)
            encoded_path = quote(parsed.path, safe='/:@!$&\'()*+,;=')
            encoded_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                encoded_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))

            # 下载 IDZ 配置文件
            logger.info(f"下载 IDZ 配置文件: {encoded_url}")
            request = Request(encoded_url)
            request.add_header('User-Agent', 'Hydros-Agent-SDK/0.1.3')

            with urlopen(request, timeout=30) as response:
                content = response.read().decode('utf-8')

            # 解析 YAML 并修改节点名
            try:
                import yaml
                data = yaml.safe_load(content)

                # 将 objects 节点名改为 components
                if 'objects' in data:
                    data['components'] = data.pop('objects')
                    logger.info("✓ 已将 'objects' 节点名改为 'components'")

                # 转换回 YAML 字符串
                content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
            except ImportError:
                logger.warning("未安装 PyYAML，跳过节点名修改")
            except Exception as e:
                logger.warning(f"修改节点名时出错: {e}，使用原始内容")

            # 保存到 examples/data 目录，使用 job_instance_id 区分不同任务
            # 使用绝对路径，确保从任何目录都能找到文件
            script_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.abspath(os.path.join(script_dir, "..", "..", "data"))
            os.makedirs(data_dir, exist_ok=True)

            # 使用 job_instance_id 生成唯一文件名，避免多任务冲突
            filename = f"idz_config_{self.job_instance_id}.yml"
            output_path = os.path.join(data_dir, filename)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"✓ IDZ 配置文件已保存到: {output_path}")
            return output_path

        except ImportError as e:
            logger.error(f"缺少依赖: {e}")
            return None
        except (HTTPError, URLError) as e:
            logger.error(f"下载 IDZ 配置失败: {e}")
            return None
        except Exception as e:
            logger.error(f"处理 IDZ 配置时出错: {e}")
            return None
