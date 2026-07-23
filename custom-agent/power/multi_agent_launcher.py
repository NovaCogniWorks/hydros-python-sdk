#!/usr/bin/env python3
"""电力 custom-agent 的轻量 launcher 入口。"""

import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAUNCHER_DIR)

from hydros_agent_sdk.launcher import MultiAgentLauncherApp

DEBUG_PORT = 5678
ENV_FILE = os.path.join(LAUNCHER_DIR, "env.properties")
LOG_DIR = os.path.join(LAUNCHER_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "hydros.log")

logger = logging.getLogger(__name__)


def main() -> None:
    app = MultiAgentLauncherApp(
        launcher_dir=LAUNCHER_DIR,
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
