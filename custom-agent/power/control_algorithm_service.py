from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from edge_control import (  # noqa: E402
    ControlAlgorithmRuntime,
    PowerControlAlgorithm,
    PowerControlConfig,
    create_control_algorithm_http_server,
)

logger = logging.getLogger(__name__)


def build_runtime() -> ControlAlgorithmRuntime:
    runtime = ControlAlgorithmRuntime()
    runtime.register(PowerControlAlgorithm(PowerControlConfig()))
    return runtime


def main() -> None:
    host = os.environ.get("HYDROS_CONTROL_ALGORITHM_HOST", "127.0.0.1")
    port = int(os.environ.get("HYDROS_CONTROL_ALGORITHM_PORT", "8066"))
    logging.basicConfig(level=os.environ.get("HYDROS_CONTROL_ALGORITHM_LOG_LEVEL", "INFO"))
    runtime = build_runtime()
    server = create_control_algorithm_http_server(runtime, host=host, port=port)
    logger.info(
        "Starting power control algorithm service on %s:%s, endpoint=/control-algorithms/{algorithm_type}/solve",
        host,
        port,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
