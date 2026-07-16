"""启动不执行真实算法的控制算法契约探针服务。"""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Optional, Sequence

# 与 custom-agent 的其他直接启动入口一致：源码联调时先解析 SDK 项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hydros_agent_sdk import (
    ControlAlgorithmRuntime,
    create_control_algorithm_http_server,
)

from control_algorithm_contract_probe import ControlAlgorithmContractProbe


def create_control_algorithm_contract_probe_server(
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """注册 ``pump_station_flow_dmpc`` 联调替身，不注册真实控制算法。"""
    runtime = ControlAlgorithmRuntime()
    runtime.register(ControlAlgorithmContractProbe())
    return create_control_algorithm_http_server(runtime, host=host, port=port)


def main(argv: Optional[Sequence[str]] = None) -> None:
    """以独立进程运行探针，供人工或部署环境的安全联调使用。"""
    parser = argparse.ArgumentParser(description="Hydros control-algorithm contract probe")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args(argv)

    server = create_control_algorithm_contract_probe_server(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
