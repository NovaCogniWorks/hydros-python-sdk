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
from typing import List, Optional

# 添加项目根目录到 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 添加当前 launcher 目录到 Python 路径
EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EXAMPLES_DIR)
ENV_FILE = os.path.join(EXAMPLES_DIR, "env.properties")

from hydros_agent_sdk import (
    setup_logging,
    SimCoordinationClient,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
)
from launcher_support import (
    AgentClassResolver,
    AgentDirectoryResolver,
    AgentDiscoveryService,
    AgentModuleInfo,
    AgentModuleLoader,
    LauncherCli,
    LauncherRuntime,
    PropertiesFileLoader,
)

DEBUG_PORT = 5678

LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")

logger = logging.getLogger(__name__)


def configure_launcher_logging(argv: List[str]) -> None:
    """根据启动参数和 env.properties 配置 launcher 日志。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        env_config = load_env_config(ENV_FILE)
        hydros_cluster_id = env_config.get('hydros_cluster_id', 'default_cluster')
        hydros_node_id = env_config.get('hydros_node_id', 'LOCAL')
    except Exception:
        hydros_cluster_id = 'default_cluster'
        hydros_node_id = os.getenv("HYDROS_NODE_ID", "LOCAL")

    setup_logging(
        level=logging.DEBUG if '--debug' in argv else logging.INFO,
        hydros_cluster_id=hydros_cluster_id,
        hydros_node_id=hydros_node_id,
        console=True,
        log_file=os.path.join(LOG_DIR, "hydros.log"),
        simple='--full-log' not in argv,
        use_rolling=True
    )


def create_launcher_services():
    properties_loader = PropertiesFileLoader()
    directory_resolver = AgentDirectoryResolver(EXAMPLES_DIR)
    discovery_service = AgentDiscoveryService(directory_resolver, properties_loader)
    module_loader = AgentModuleLoader(
        directory_resolver=directory_resolver,
        properties_loader=properties_loader,
        class_resolver=AgentClassResolver(),
    )
    return discovery_service, module_loader


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

    def __init__(self, module_loader: Optional[AgentModuleLoader] = None):
        self.callback: Optional[MultiAgentCallback] = None
        self.client: Optional[SimCoordinationClient] = None
        if module_loader is None:
            _, module_loader = create_launcher_services()
        self.module_loader = module_loader
        self.running = False

    def load_agent_module(self, agent_name: str) -> AgentModuleInfo:
        """动态加载 agent 模块。"""
        return self.module_loader.load(agent_name)

    def start_all(self, agent_names: List[str]):
        """启动所有指定的 agents"""
        logger.info("=" * 70)
        logger.info("Multi-Agent Launcher")
        logger.info("=" * 70)
        logger.info(f"Starting {len(agent_names)} agent types: {', '.join(agent_names)}")
        logger.info(f"Log file: {os.path.join(LOG_DIR, 'hydros.log')}")
        logger.info("=" * 70)
        logger.info("")

        # 1. 创建统一的 MultiAgentCallback
        logger.info("Creating unified MultiAgentCallback...")
        self.callback = MultiAgentCallback(node_id=os.getenv("HYDROS_NODE_ID", "LOCAL"))

        # 2. 加载环境配置（所有 agent 共享）
        env_config = None
        registered_agents = []  # 存储已注册的 agent 信息
        for agent_name in agent_names:
            try:
                logger.info(f"Registering {agent_name.upper()} agent...")

                # 加载 agent 模块
                agent_info = self.load_agent_module(agent_name)

                # 加载环境配置（所有 agent 共享，只加载一次）
                if env_config is None:
                    # 使用当前 launcher 目录下的 env.properties
                    env_config = load_env_config(ENV_FILE)
                    logger.info(f"  Cluster ID: {env_config['hydros_cluster_id']}")
                    logger.info(f"  Node ID: {env_config['hydros_node_id']}")

                # Agent 配置文件
                config_file = os.path.join(agent_info.script_dir, 'agent.properties')

                # 创建 agent factory（使用泛型 HydroAgentFactory，传递 env_config）
                agent_factory = HydroAgentFactory(
                    agent_class=agent_info.agent_class,
                    config_file=config_file,
                    env_config=env_config
                )

                # 注册到 callback
                self.callback.register_agent_factory(agent_info.agent_code, agent_factory)

                logger.info(f"  ✓ {agent_name.upper()} agent registered")
                logger.info(f"    Display Name: {agent_info.agent_display_name}")
                logger.info(f"    Agent Code: {agent_info.agent_code}")
                logger.info(f"    Agent Class: {agent_info.agent_class.__name__}")

                # 保存 agent 信息用于后续显示
                registered_agents.append({
                    'name': agent_info.name,
                    'agent_code': agent_info.agent_code,
                    'agent_type': agent_info.agent_type or agent_info.agent_code.replace('_demo001', ''),
                    'agent_display_name': agent_info.agent_display_name,
                    'agent_class': agent_info.agent_class.__name__,
                    'directory': os.path.basename(agent_info.script_dir)
                })

            except Exception as e:
                logger.error(f"Failed to register {agent_name}: {e}", exc_info=True)
                return False

        if env_config is None:
            logger.error("No environment configuration loaded!")
            return False

        self.callback.register_system_default_central_scheduling_agent(env_config)
        if not any(agent['agent_code'] == 'CENTRAL_SCHEDULING_AGENT' for agent in registered_agents):
            registered_agents.append({
                'name': 'system-central-scheduling',
                'agent_code': 'CENTRAL_SCHEDULING_AGENT',
                'agent_type': 'CENTRAL_SCHEDULING_AGENT',
                'agent_display_name': 'System Central Scheduling Agent',
                'agent_class': 'SystemCentralSchedulingAgent',
                'directory': '(sdk built-in)'
            })

        # 3. 创建统一的 SimCoordinationClient
        logger.info("")
        logger.info("Creating SimCoordinationClient...")

        broker_url = env_config['mqtt_broker_url']
        broker_port = int(env_config['mqtt_broker_port'])
        topic = env_config['mqtt_topic']
        mqtt_username = env_config.get('mqtt_username')
        mqtt_password = env_config.get('mqtt_password')

        self.client = SimCoordinationClient(
            broker_url=broker_url,
            broker_port=broker_port,
            topic=topic,
            sim_coordination_callback=self.callback,
            mqtt_username=mqtt_username,
            mqtt_password=mqtt_password
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
        for agent in registered_agents:
            logger.info(f"  • {agent['name'].upper()}")
            logger.info(f"      Agent Code:   {agent['agent_code']}")
            logger.info(f"      Agent Type:   {agent['agent_type']}")
            logger.info(f"      Display Name: {agent['agent_display_name']}")
            logger.info(f"      Class Name:   {agent['agent_class']}")
            logger.info(f"      Directory:    agents/{agent['directory']}/")
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


def main():
    """主函数"""
    global DEBUG_PORT

    configure_launcher_logging(sys.argv)
    discovery_service, module_loader = create_launcher_services()
    cli = LauncherCli(discovery_service, default_debug_port=DEBUG_PORT)
    try:
        options = cli.parse(sys.argv)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    if options.show_help:
        cli.print_help()
        sys.exit(0)

    if options.list_only:
        cli.print_agent_list()
        sys.exit(0)

    agent_names = options.agent_names
    if options.all_requested:
        logger.info(f"Auto-discovered {len(agent_names)} agent(s): {', '.join(agent_names)}")

    if not agent_names:
        logger.error("No agents specified!")
        cli.print_help()
        sys.exit(1)

    # 启用调试模式
    if options.debug_enabled:
        DEBUG_PORT = options.debug_port
        setup_debugpy(port=options.debug_port, wait_for_client=options.debug_wait)

    # 创建协调器
    coordinator = MultiAgentCoordinator(module_loader=module_loader)
    runtime = LauncherRuntime(coordinator, logger=logger)

    sys.exit(runtime.run(agent_names))


if __name__ == "__main__":
    main()
