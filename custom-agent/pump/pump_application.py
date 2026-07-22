"""泵站 MQTT Agents 与边缘控制算法 HTTP Host 的统一应用入口。"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUMP_AGENT_ROOT = Path(__file__).resolve().parent
for import_root in (PROJECT_ROOT, PUMP_AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from hydros_agent_sdk.launcher.support import MultiAgentLauncherApp  # noqa: E402
from pump_flow_dmpc_service import PumpFlowDmpcHttpHost  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    """解析 pump 部署参数并启动统一的 MQTT + HTTP 运行时。"""

    parser = argparse.ArgumentParser(
        description="Run Hydros pump agents and the control algorithm HTTP host",
    )
    parser.add_argument("--launcher-dir", required=True)
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--default-debug-port", type=int, default=5678)
    parser.add_argument(
        "--control-algorithm-host",
        default=os.getenv("HYDROS_CONTROL_ALGORITHM_HTTP_HOST", "0.0.0.0"),
    )
    parser.add_argument(
        "--control-algorithm-port",
        type=int,
        default=int(os.getenv("HYDROS_CONTROL_ALGORITHM_HTTP_PORT", "8015")),
    )
    parser.add_argument(
        "--pump-flow-model-config",
        default=os.getenv("HYDROS_PUMP_FLOW_DMPC_MODEL_CONFIG", ""),
    )
    parser.add_argument("launcher_args", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)

    forwarded_args = options.launcher_args
    if forwarded_args and forwarded_args[0] == "--":
        forwarded_args = forwarded_args[1:]

    launcher_dir = os.path.abspath(options.launcher_dir)
    log_dir = os.path.join(launcher_dir, "logs")
    algorithm_host = PumpFlowDmpcHttpHost(
        model_config=options.pump_flow_model_config,
        host=options.control_algorithm_host,
        port=options.control_algorithm_port,
    )
    app = MultiAgentLauncherApp(
        launcher_dir=launcher_dir,
        env_file=os.path.join(launcher_dir, "env.properties"),
        log_file=os.path.join(log_dir, "hydros.log"),
        log_dir=log_dir,
        project_root=(
            os.path.abspath(options.project_root)
            if options.project_root
            else launcher_dir
        ),
        default_debug_port=options.default_debug_port,
        managed_services=(algorithm_host,),
        logger=logging.getLogger(__name__),
    )
    return app.run(["pump_application.py", *forwarded_args])


if __name__ == "__main__":
    sys.exit(main())
