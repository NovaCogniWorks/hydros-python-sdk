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
from typing import List, Optional

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

    def load_agent_module(self, agent_name: str):
        """动态加载 agent 模块"""
        agent_map = {
            'twins': {
                'module': 'agents.twins.twins_agent',
                'agent_class': 'MyTwinsSimulationAgent',
                'script_dir': os.path.join(EXAMPLES_DIR, 'agents', 'twins'),
                'agent_code': 'TWINS_SIMULATION_AGENT'
            },
            'ontology': {
                'module': 'agents.ontology.ontology_agent',
                'agent_class': 'MyOntologySimulationAgent',
                'script_dir': os.path.join(EXAMPLES_DIR, 'agents', 'ontology'),
                'agent_code': 'ONTOLOGY_SIMULATION_AGENT'
            },
        }

        if agent_name not in agent_map:
            raise ValueError(f"Unknown agent: {agent_name}")

        agent_info = agent_map[agent_name]

        # 动态导入模块
        module = __import__(agent_info['module'], fromlist=[agent_info['agent_class']])

        return {
            'name': agent_name,
            'agent_class': getattr(module, agent_info['agent_class']),
            'script_dir': agent_info['script_dir'],
            'agent_code': agent_info['agent_code']
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
    print("""
Multi-Agent Launcher - 在单个进程中运行多个 agents

用法:
    python multi_agent_launcher.py [选项] [agent1] [agent2] ...
    python multi_agent_launcher.py --all

可用的 agents:
    twins      - Twins Simulation Agent
    ontology   - Ontology Simulation Agent
    lite       - Lite Agent Example

选项:
    --all              - 启动所有 agents
    --debug            - 启用远程调试模式 (debugpy)
    --debug-port PORT  - 指定调试端口 (默认: 5678)
    --debug-nowait     - 不等待调试器连接，直接启动
    --help             - 显示帮助信息

示例:
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
    • 所有 agents 在同一个进程中运行
    • 前台运行，可以在控制台看到日志
    • 所有日志保存到 examples/logs/agent.log
    • 日志内容中包含 agent 标识，可以区分不同的 agent
    • 使用 Ctrl+C 优雅停止所有 agents
""")


def main():
    """主函数"""
    global DEBUG_MODE, DEBUG_PORT

    # 解析参数
    if len(sys.argv) < 2 or '--help' in sys.argv or '-h' in sys.argv:
        show_help()
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
        agent_names = ['twins', 'ontology']
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
    def signal_handler(signum, frame):
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
