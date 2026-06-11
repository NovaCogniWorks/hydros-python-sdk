#!/usr/bin/env python3
"""
多智能体启动器：在单个进程中运行多个智能体

用法:
    python multi_agent_launcher.py agent1 agent2
    python multi_agent_launcher.py --all
    python multi_agent_launcher.py --debug agent1 agent2  # 启用远程调试
"""

import sys
import os
import logging

# 添加项目根目录到 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 添加当前 launcher 目录到 Python 路径
EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EXAMPLES_DIR)
ENV_FILE = os.path.join(EXAMPLES_DIR, "env.properties")

from hydros_agent_sdk.launcher import MultiAgentLauncherApp

DEBUG_PORT = 5678

LOG_DIR = os.path.join(EXAMPLES_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "hydros.log")

logger = logging.getLogger(__name__)


def main():
    """主函数"""
    app = MultiAgentLauncherApp(
        launcher_dir=EXAMPLES_DIR,
        env_file=ENV_FILE,
        log_file=LOG_FILE,
        log_dir=LOG_DIR,
        project_root=PROJECT_ROOT,
        default_debug_port=DEBUG_PORT,
        logger=logger,
    )
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
