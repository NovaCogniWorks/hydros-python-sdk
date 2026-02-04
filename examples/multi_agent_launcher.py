#!/usr/bin/env python3
"""
Multi-Agent Launcher - 在单个进程中运行多个 agents

用法:
    python multi_agent_launcher.py twins ontology
    python multi_agent_launcher.py --all
    python multi_agent_launcher.py --debug twins ontology  # 启用远程调试
"""

import sys
import os
import time
import logging
import signal
import importlib.util
import inspect
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 添加 examples 目录到 Python 路径
EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EXAMPLES_DIR)

from hydros_agent_sdk import (
    setup_logging,
    SimCoordinationClient,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
)
from hydros_agent_sdk.base_agent import BaseHydroAgent

# Debug 支持
DEBUG_MODE = False
DEBUG_PORT = 5678

# 配置统一日志
EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Load env config to get cluster_id and node_id for logging
try:
    env_config = load_env_config()
    hydros_cluster_id = env_config.get('hydros_cluster_id', 'default_cluster')
    hydros_node_id = env_config.get('hydros_node_id', 'LOCAL')
except Exception:
    # Fallback if env.properties not available yet
    hydros_cluster_id = 'default_cluster'
    hydros_node_id = os.getenv("HYDROS_NODE_ID", "LOCAL")

setup_logging(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    hydros_cluster_id=hydros_cluster_id,
    hydros_node_id=hydros_node_id,
    console=True,
    log_file=os.path.join(LOG_DIR, "agent.log")
)

logger = logging.getLogger(__name__)


def parse_properties(properties_file: str) -> Dict[str, str]:
    """
    解析 .properties 文件

    Args:
        properties_file: properties 文件路径

    Returns:
        包含所有配置项的字典
    """
    properties = {}

    if not os.path.exists(properties_file):
        raise FileNotFoundError(f"Properties file not found: {properties_file}")

    with open(properties_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # 跳过注释和空行
            if not line or line.startswith('#'):
                continue
            # 解析 key=value
            if '=' in line:
                key, value = line.split('=', 1)
                properties[key.strip()] = value.strip()

    return properties


def find_agent_class(agent_dir: str) -> Optional[type]:
    """
    在指定目录中查找 BaseHydroAgent 的子类

    Args:
        agent_dir: agent 目录路径

    Returns:
        找到的 Agent 类，如果没找到返回 None
    """
    # 扫描目录下的所有 Python 文件
    py_files = [f for f in os.listdir(agent_dir)
                if f.endswith('.py') and not f.startswith('__')]

    if not py_files:
        logger.warning(f"No Python files found in {agent_dir}")
        return None

    # 遍历每个 Python 文件
    for py_file in py_files:
        file_path = os.path.join(agent_dir, py_file)
        module_name = py_file[:-3]  # 去掉 .py 后缀

        try:
            # 动态导入模块
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 检查模块中的所有类
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # 检查是否是 BaseHydroAgent 的子类（但不是 BaseHydroAgent 本身）
                if (obj != BaseHydroAgent and
                    issubclass(obj, BaseHydroAgent) and
                    obj.__module__ == module_name):

                    # 优先选择不包含特殊标记的类（如 "With", "Test" 等）
                    if not any(marker in name for marker in ['With', 'Test', 'Mock', 'Demo']):
                        logger.debug(f"Found agent class: {name} in {py_file}")
                        return obj

        except Exception as e:
            logger.debug(f"Failed to import {py_file}: {e}")
            continue

    # 如果没找到标准类，再次扫描接受任何 BaseHydroAgent 子类
    for py_file in py_files:
        file_path = os.path.join(agent_dir, py_file)
        module_name = py_file[:-3]

        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (obj != BaseHydroAgent and
                    issubclass(obj, BaseHydroAgent) and
                    obj.__module__ == module_name):
                    logger.debug(f"Found agent class (fallback): {name} in {py_file}")
                    return obj

        except Exception as e:
            continue

    return None


def discover_all_agents() -> List[str]:
    """
    自动发现所有可用的 agents

    Returns:
        可用的 agent 名称列表
    """
    agents_dir = os.path.join(EXAMPLES_DIR, 'agents')

    if not os.path.exists(agents_dir):
        logger.warning(f"Agents directory not found: {agents_dir}")
        return []

    available_agents = []

    # 扫描所有子目录
    for item in os.listdir(agents_dir):
        item_path = os.path.join(agents_dir, item)

        # 跳过非目录和特殊目录
        if not os.path.isdir(item_path) or item.startswith('__'):
            continue

        # 检查是否有 agent.properties 文件
        props_file = os.path.join(item_path, 'agent.properties')
        if not os.path.exists(props_file):
            logger.debug(f"Skipping {item}: no agent.properties found")
            continue

        # 检查是否有 Python 实现文件
        py_files = [f for f in os.listdir(item_path)
                    if f.endswith('.py') and not f.startswith('__')]

        if not py_files:
            logger.debug(f"Skipping {item}: no Python implementation found")
            continue

        available_agents.append(item)
        logger.debug(f"Discovered agent: {item}")

    return sorted(available_agents)


def setup_debugpy(port: int = 5678, wait_for_client: bool = True):
    """
    设置 debugpy 远程调试

    Args:
        port: 调试端口
        wait_for_client: 是否等待调试器连接
    """
    try:
        import debugpy

        # 配置 debugpy
        debugpy.listen(("0.0.0.0", port))

        logger.info("=" * 70)
        logger.info("🐛 DEBUG MODE ENABLED")
        logger.info("=" * 70)
        logger.info(f"Debugpy listening on port {port}")
        logger.info("Connect your debugger to: localhost:{port}")
        logger.info("")
        logger.info("VS Code launch.json configuration:")
        logger.info("{")
        logger.info('  "name": "Attach to Hydros Agent",')
        logger.info('  "type": "python",')
        logger.info('  "request": "attach",')
        logger.info(f'  "connect": {{"host": "localhost", "port": {port}}},')
        logger.info('  "pathMappings": [')
        logger.info('    {')
        logger.info(f'      "localRoot": "${{workspaceFolder}}",')
        logger.info(f'      "remoteRoot": "{PROJECT_ROOT}"')
        logger.info('    }')
        logger.info('  ]')
        logger.info("}")
        logger.info("=" * 70)

        if wait_for_client:
            logger.info("⏳ Waiting for debugger to attach...")
            logger.info("   (Press Ctrl+C to skip and continue)")
            try:
                debugpy.wait_for_client()
                logger.info("✓ Debugger attached!")
            except KeyboardInterrupt:
                logger.info("⚠ Skipped waiting for debugger")

        logger.info("")

    except ImportError:
        logger.error("=" * 70)
        logger.error("❌ debugpy not installed!")
        logger.error("=" * 70)
        logger.error("Install debugpy to enable debug mode:")
        logger.error("  pip install debugpy")
        logger.error("=" * 70)
        sys.exit(1)


class MultiAgentCoordinator:
    """多 Agent 协调器 - 在单个进程中管理多个 agents"""

    def __init__(self):
        self.callback: Optional[MultiAgentCallback] = None
        self.client: Optional[SimCoordinationClient] = None
        self.running = False

    def load_agent_module(self, agent_name: str) -> Dict[str, Any]:
        """
        动态加载 agent 模块（自动扫描）

        Args:
            agent_name: agent 目录名称（如 'twins', 'ontology'）

        Returns:
            包含 agent 信息的字典：
            - name: agent 名称
            - agent_class: Agent 类
            - script_dir: agent 目录路径
            - agent_code: agent 代码（从 agent.properties 读取）
            - agent_display_name: agent 显示名称（从 agent.properties 读取）

        Raises:
            ValueError: 如果 agent 不存在或加载失败
        """
        # 1. 构建 agent 目录路径
        agents_dir = os.path.join(EXAMPLES_DIR, 'agents')
        agent_dir = os.path.join(agents_dir, agent_name)

        if not os.path.exists(agent_dir):
            raise ValueError(f"Agent directory not found: {agent_dir}")

        if not os.path.isdir(agent_dir):
            raise ValueError(f"Not a directory: {agent_dir}")

        # 2. 读取 agent.properties
        props_file = os.path.join(agent_dir, 'agent.properties')

        try:
            properties = parse_properties(props_file)
        except FileNotFoundError:
            raise ValueError(f"agent.properties not found in {agent_dir}")
        except Exception as e:
            raise ValueError(f"Failed to parse agent.properties: {e}")

        # 3. 提取必要的配置
        agent_code = properties.get('agent_code')
        agent_display_name = properties.get('agent_name', agent_name)

        if not agent_code:
            raise ValueError(f"agent_code not found in {props_file}")

        logger.debug(f"Loaded properties for {agent_name}:")
        logger.debug(f"  agent_code: {agent_code}")
        logger.debug(f"  agent_name: {agent_display_name}")

        # 4. 查找 BaseHydroAgent 子类
        agent_class = find_agent_class(agent_dir)

        if agent_class is None:
            raise ValueError(
                f"No BaseHydroAgent subclass found in {agent_dir}. "
                f"Please ensure there is a Python file with a class that inherits from BaseHydroAgent."
            )

        logger.debug(f"Found agent class: {agent_class.__name__}")

        # 5. 返回 agent 信息
        return {
            'name': agent_name,
            'agent_class': agent_class,
            'script_dir': agent_dir,
            'agent_code': agent_code,
            'agent_display_name': agent_display_name
        }

    def start_all(self, agent_names: List[str]):
        """启动所有指定的 agents"""
        logger.info("=" * 70)
        logger.info("Multi-Agent Launcher")
        logger.info("=" * 70)
        logger.info(f"Starting {len(agent_names)} agent types: {', '.join(agent_names)}")
        logger.info(f"Log file: {os.path.join(LOG_DIR, 'agent.log')}")
        logger.info("=" * 70)
        logger.info("")

        # 1. 创建统一的 MultiAgentCallback
        logger.info("Creating unified MultiAgentCallback...")
        self.callback = MultiAgentCallback(node_id=os.getenv("HYDROS_NODE_ID", "LOCAL"))

        # 2. 加载环境配置（所有 agent 共享）
        env_config = None
        for agent_name in agent_names:
            try:
                logger.info(f"Registering {agent_name.upper()} agent...")

                # 加载 agent 模块
                agent_info = self.load_agent_module(agent_name)

                # 加载环境配置（所有 agent 共享，只加载一次）
                if env_config is None:
                    # 使用共享的 env.properties（在 examples 目录下）
                    env_config = load_env_config()
                    logger.info(f"  Cluster ID: {env_config['hydros_cluster_id']}")
                    logger.info(f"  Node ID: {env_config['hydros_node_id']}")

                # Agent 配置文件
                config_file = os.path.join(agent_info['script_dir'], 'agent.properties')   

                # 创建 agent factory（使用泛型 HydroAgentFactory，传递 env_config）
                agent_factory = HydroAgentFactory(
                    agent_class=agent_info['agent_class'],
                    config_file=config_file,
                    env_config=env_config
                )

                # 注册到 callback
                self.callback.register_agent_factory(agent_info['agent_code'], agent_factory)

                logger.info(f"  ✓ {agent_name.upper()} agent registered")
                logger.info(f"    Display Name: {agent_info['agent_display_name']}")
                logger.info(f"    Agent Code: {agent_info['agent_code']}")
                logger.info(f"    Agent Class: {agent_info['agent_class'].__name__}")

            except Exception as e:
                logger.error(f"Failed to register {agent_name}: {e}", exc_info=True)
                return False

        if env_config is None:
            logger.error("No environment configuration loaded!")
            return False

        # 3. 创建统一的 SimCoordinationClient
        logger.info("")
        logger.info("Creating SimCoordinationClient...")

        broker_url = env_config['mqtt_broker_url']
        broker_port = int(env_config['mqtt_broker_port'])
        topic = env_config['mqtt_topic']

        self.client = SimCoordinationClient(
            broker_url=broker_url,
            broker_port=broker_port,
            topic=topic,
            sim_coordination_callback=self.callback
        )

        # 设置 client 引用
        self.callback.set_client(self.client)

        # 4. 启动 client
        logger.info("")
        logger.info("Starting coordination client...")
        self.client.start()

        logger.info("")
        logger.info("=" * 70)
        logger.info(f"Multi-Agent System Started!")
        logger.info("=" * 70)
        logger.info(f"  MQTT Broker: {broker_url}:{broker_port}")
        logger.info(f"  MQTT Topic: {topic}")
        logger.info("")
        logger.info("Registered agent types:")
        for agent_name in agent_names:
            logger.info(f"  • {agent_name.upper()}")
        logger.info("")
        logger.info("Press Ctrl+C to stop all agents...")
        logger.info("")

        self.running = True
        return True

    def stop_all(self):
        """停止所有 agents"""
        if not self.running:
            return

        logger.info("")
        logger.info("=" * 70)
        logger.info("Stopping multi-agent system...")
        logger.info("=" * 70)

        if self.client:
            try:
                logger.info("Stopping coordination client...")
                self.client.stop()
                logger.info("  ✓ Client stopped")
            except Exception as e:
                logger.error(f"  ✗ Error stopping client: {e}")

        self.running = False

        logger.info("=" * 70)
        logger.info("Multi-agent system stopped")
        logger.info("=" * 70)

    def run(self):
        """运行主循环"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("")
            logger.info("Received interrupt signal...")
        finally:
            self.stop_all()


def show_help():
    """显示帮助信息"""
    # 自动发现可用的 agents
    available_agents = discover_all_agents()

    agents_list = "\n".join([f"    {agent:15} - Auto-discovered from agents/{agent}/"
                             for agent in available_agents])

    if not agents_list:
        agents_list = "    (No agents found in examples/agents/)"

    print(f"""
Multi-Agent Launcher - 在单个进程中运行多个 agents

用法:
    python multi_agent_launcher.py [选项] [agent1] [agent2] ...
    python multi_agent_launcher.py --all
    python multi_agent_launcher.py --list

可用的 agents (自动发现):
{agents_list}

选项:
    --all              - 启动所有可用的 agents
    --list             - 列出所有可用的 agents
    --debug            - 启用远程调试模式 (debugpy)
    --debug-port PORT  - 指定调试端口 (默认: 5678)
    --debug-nowait     - 不等待调试器连接，直接启动
    --help             - 显示帮助信息

示例:
    # 列出所有可用的 agents
    python multi_agent_launcher.py --list

    # 启动单个 agent
    python multi_agent_launcher.py twins

    # 启动多个 agents（在同一个进程中）
    python multi_agent_launcher.py twins ontology

    # 启动所有 agents
    python multi_agent_launcher.py --all

    # 启用调试模式（等待调试器连接）
    python multi_agent_launcher.py --debug twins ontology

    # 启用调试模式（不等待，直接启动）
    python multi_agent_launcher.py --debug --debug-nowait twins

    # 使用自定义调试端口
    python multi_agent_launcher.py --debug --debug-port 5679 twins

调试模式:
    • 使用 debugpy 进行远程调试
    • 默认监听端口: 5678
    • 支持 VS Code、PyCharm 等 IDE
    • 可以设置断点、单步调试、查看变量等

特性:
    • 自动发现 examples/agents/ 下的所有 agent 实现
    • 从 agent.properties 读取配置（agent_code, agent_name）
    • 自动扫描并加载 BaseHydroAgent 子类
    • 无需硬编码 agent 列表，每个目录一个 agent 实现
    • 所有 agents 在同一个进程中运行
    • 前台运行，可以在控制台看到日志
    • 所有日志保存到 examples/logs/agent.log
    • 日志内容中包含 agent 标识，可以区分不同的 agent
    • 使用 Ctrl+C 优雅停止所有 agents

添加新 Agent:
    1. 在 examples/agents/ 下创建新目录（如 myagent/）
    2. 创建 agent.properties 文件，包含 agent_code 和 agent_name
    3. 创建 Python 文件，实现 BaseHydroAgent 的子类
    4. 运行 python multi_agent_launcher.py myagent
""")


def main():
    """主函数"""
    global DEBUG_MODE, DEBUG_PORT

    # 解析参数
    if len(sys.argv) < 2 or '--help' in sys.argv or '-h' in sys.argv:
        show_help()
        sys.exit(0)

    # 处理 --list 参数
    if '--list' in sys.argv:
        print("\n" + "=" * 70)
        print("Available Agents (auto-discovered)")
        print("=" * 70)
        available_agents = discover_all_agents()

        if not available_agents:
            print("No agents found in examples/agents/")
            print("\nTo add a new agent:")
            print("  1. Create a directory in examples/agents/")
            print("  2. Add agent.properties with agent_code and agent_name")
            print("  3. Implement a BaseHydroAgent subclass")
        else:
            for agent_name in available_agents:
                agent_dir = os.path.join(EXAMPLES_DIR, 'agents', agent_name)
                props_file = os.path.join(agent_dir, 'agent.properties')

                try:
                    properties = parse_properties(props_file)
                    agent_code = properties.get('agent_code', 'N/A')
                    agent_display_name = properties.get('agent_name', 'N/A')

                    print(f"\n  {agent_name}")
                    print(f"    Display Name: {agent_display_name}")
                    print(f"    Agent Code:   {agent_code}")
                    print(f"    Directory:    agents/{agent_name}/")
                except Exception as e:
                    print(f"\n  {agent_name}")
                    print(f"    Error: {e}")

        print("\n" + "=" * 70)
        print(f"Total: {len(available_agents)} agent(s)")
        print("=" * 70 + "\n")
        sys.exit(0)

    # 解析调试参数
    debug_enabled = '--debug' in sys.argv
    debug_wait = '--debug-nowait' not in sys.argv
    debug_port = DEBUG_PORT

    # 解析调试端口
    if '--debug-port' in sys.argv:
        try:
            port_idx = sys.argv.index('--debug-port')
            if port_idx + 1 < len(sys.argv):
                debug_port = int(sys.argv[port_idx + 1])
        except (ValueError, IndexError):
            logger.error("Invalid --debug-port value")
            sys.exit(1)

    # 确定要启动的 agents
    if '--all' in sys.argv:
        # 自动发现所有可用的 agents
        agent_names = discover_all_agents()
        if not agent_names:
            logger.error("No agents found in examples/agents/")
            logger.error("Please add agent implementations first.")
            sys.exit(1)
        logger.info(f"Auto-discovered {len(agent_names)} agent(s): {', '.join(agent_names)}")
    else:
        agent_names = [
            arg for arg in sys.argv[1:]
            if not arg.startswith('--') and arg not in [str(debug_port)]
        ]

    if not agent_names:
        logger.error("No agents specified!")
        show_help()
        sys.exit(1)

    # 启用调试模式
    if debug_enabled:
        DEBUG_MODE = True
        DEBUG_PORT = debug_port
        setup_debugpy(port=debug_port, wait_for_client=debug_wait)

    # 创建协调器
    coordinator = MultiAgentCoordinator()

    # 设置信号处理
    def signal_handler(_signum, _frame):
        logger.info("")
        logger.info("Received signal, stopping...")
        coordinator.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动所有 agents
    if coordinator.start_all(agent_names):
        # 运行主循环
        coordinator.run()
    else:
        logger.error("Failed to start agents")
        sys.exit(1)


if __name__ == "__main__":
    main()
