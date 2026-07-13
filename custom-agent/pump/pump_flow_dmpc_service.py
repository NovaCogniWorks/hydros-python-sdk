"""独立启动泵站流量 DMPC HTTP 服务。"""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Optional, Sequence, Union

# 直接执行 custom-agent 脚本时需要显式暴露 SDK 项目根与本应用目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUMP_AGENT_ROOT = Path(__file__).resolve().parent
for import_root in (PROJECT_ROOT, PUMP_AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from hydros_agent_sdk import (  # noqa: E402
    ControlAlgorithmRuntime,
    create_control_algorithm_http_server,
)
from pump_flow_dmpc import (  # noqa: E402
    PumpFlowDmpcInputResolver,
    PumpFlowDmpcSolver,
    PumpStationFlowDmpcAlgorithm,
    TabulatedPumpPerformanceRepository,
)


def create_pump_flow_dmpc_server(
    model_config: Union[str, Path],
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """创建仅注册泵站流量 DMPC 的标准 HTTP 服务。"""

    performance = TabulatedPumpPerformanceRepository.from_yaml(model_config)
    runtime = ControlAlgorithmRuntime()
    runtime.register(
        PumpStationFlowDmpcAlgorithm(
            solver=PumpFlowDmpcSolver(performance),
            resolver=PumpFlowDmpcInputResolver(),
        )
    )
    return create_control_algorithm_http_server(runtime, host=host, port=port)


def main(argv: Optional[Sequence[str]] = None) -> None:
    """启动独立服务；模型路径由部署侧明确提供。"""

    parser = argparse.ArgumentParser(description="Hydros pump flow DMPC service")
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args(argv)

    server = create_pump_flow_dmpc_server(
        args.model_config,
        host=args.host,
        port=args.port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
