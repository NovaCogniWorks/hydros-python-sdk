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
    MultiAgentCallback,
    load_env_config,
)
from launcher_support import (
    AgentClassResolver,
    AgentDirectoryResolver,
    AgentDiscoveryService,
    AgentFactoryRegistrationService,
    AgentModuleInfo,
    AgentModuleLoader,
    CoordinationClientFactory,
    LauncherCli,
    LauncherRuntime,
    LauncherStartupReporter,
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

    def __init__(
        self,
        module_loader: Optional[AgentModuleLoader] = None,
        registration_service: Optional[AgentFactoryRegistrationService] = None,
        client_factory: Optional[CoordinationClientFactory] = None,
        startup_reporter: Optional[LauncherStartupReporter] = None,
    ):
        self.callback: Optional[MultiAgentCallback] = None
        self.client: Optional[SimCoordinationClient] = None
        if module_loader is None:
            _, module_loader = create_launcher_services()
        self.module_loader = module_loader
        self.registration_service = registration_service or AgentFactoryRegistrationService(
            module_loader=module_loader,
            env_file=ENV_FILE,
            logger=logger,
        )
        self.client_factory = client_factory or CoordinationClientFactory()
        self.startup_reporter = startup_reporter or LauncherStartupReporter(
            log_file=os.path.join(LOG_DIR, "hydros.log"),
            logger=logger,
        )
        self.running = False

    def load_agent_module(self, agent_name: str) -> AgentModuleInfo:
        """动态加载 agent 模块。"""
        return self.module_loader.load(agent_name)

    def start_all(self, agent_names: List[str]):
        """启动所有指定的 agents"""
        self.startup_reporter.log_starting(agent_names)

        logger.info("Creating unified MultiAgentCallback...")
        self.callback = MultiAgentCallback(node_id=os.getenv("HYDROS_NODE_ID", "LOCAL"))

        try:
            env_config, registered_agents = self.registration_service.register_agents(
                self.callback,
                agent_names,
            )
        except Exception as e:
            logger.error(f"Failed to register agents: {e}", exc_info=True)
            return False

        logger.info("")
        logger.info("Creating SimCoordinationClient...")
        self.client = self.client_factory.create(env_config, self.callback)
        self.callback.set_client(self.client)

        logger.info("")
        logger.info("Starting coordination client...")
        self.client.start()

        self.startup_reporter.log_started(env_config, registered_agents)
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
