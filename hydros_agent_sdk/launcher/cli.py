"""Command-line entry point for the reusable Hydros multi-agent launcher."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional

from hydros_agent_sdk.launcher.support import MultiAgentLauncherApp


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hydros_agent_sdk.launcher",
        description="Run a Hydros multi-agent launcher for a given application directory.",
    )
    parser.add_argument(
        "--launcher-dir",
        required=True,
        help="Directory containing env.properties and agent directories.",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root to add to debug path mappings.",
    )
    parser.add_argument(
        "--default-debug-port",
        type=int,
        default=5678,
        help="Default debugpy port passed to the launcher app.",
    )
    parser.add_argument(
        "launcher_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the multi-agent launcher; prefix with -- when needed.",
    )

    options = parser.parse_args(argv)
    launcher_dir = os.path.abspath(options.launcher_dir)
    log_dir = os.path.join(launcher_dir, "logs")

    forwarded_args = options.launcher_args
    if forwarded_args and forwarded_args[0] == "--":
        forwarded_args = forwarded_args[1:]

    app = MultiAgentLauncherApp(
        launcher_dir=launcher_dir,
        env_file=os.path.join(launcher_dir, "env.properties"),
        log_file=os.path.join(log_dir, "hydros.log"),
        log_dir=log_dir,
        project_root=os.path.abspath(options.project_root) if options.project_root else launcher_dir,
        default_debug_port=options.default_debug_port,
        logger=logging.getLogger(__name__),
    )
    return app.run(["multi_agent_launcher.py", *forwarded_args])


if __name__ == "__main__":
    sys.exit(main())
