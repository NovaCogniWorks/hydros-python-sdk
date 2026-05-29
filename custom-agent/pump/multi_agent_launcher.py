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
    SimCoordinationClient,
    MultiAgentCallback,
)
from launcher_support import (
    AgentFactoryRegistrationService,
    AgentModuleInfo,
    AgentModuleLoader,
    CoordinationClientFactory,
    LauncherDebugSupport,
    LauncherCli,
    LauncherLoggingConfigurator,
    LauncherRuntime,
    LauncherServiceFactory,
    LauncherStartupReporter,
)

DEBUG_PORT = 5678

LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "hydros.log")

logger = logging.getLogger(__name__)


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
            module_loader = LauncherServiceFactory(EXAMPLES_DIR).create().module_loader
        self.module_loader = module_loader
        self.registration_service = registration_service or AgentFactoryRegistrationService(
            module_loader=module_loader,
            env_file=ENV_FILE,
            logger=logger,
        )
        self.client_factory = client_factory or CoordinationClientFactory()
        self.startup_reporter = startup_reporter or LauncherStartupReporter(
            log_file=LOG_FILE,
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

    LauncherLoggingConfigurator(
        env_file=ENV_FILE,
        log_file=LOG_FILE,
        log_dir=LOG_DIR,
    ).configure(sys.argv)
    services = LauncherServiceFactory(EXAMPLES_DIR).create()
    cli = LauncherCli(services.discovery_service, default_debug_port=DEBUG_PORT)
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
        LauncherDebugSupport(PROJECT_ROOT, logger=logger).setup(
            port=options.debug_port,
            wait_for_client=options.debug_wait,
        )

    # 创建协调器
    coordinator = MultiAgentCoordinator(module_loader=services.module_loader)
    runtime = LauncherRuntime(coordinator, logger=logger)

    sys.exit(runtime.run(agent_names))


if __name__ == "__main__":
    main()
