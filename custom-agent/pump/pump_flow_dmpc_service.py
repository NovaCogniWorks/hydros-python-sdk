"""独立启动泵站流量 DMPC HTTP 服务。"""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
import logging
from pathlib import Path
import sys
import threading
from typing import Optional, Sequence

# 直接执行 custom-agent 脚本时需要显式暴露 SDK 项目根与本应用目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUMP_AGENT_ROOT = Path(__file__).resolve().parent
for import_root in (PROJECT_ROOT, PUMP_AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from hydros_agent_sdk import (  # noqa: E402
    ControlAlgorithmRuntime,
    create_control_algorithm_http_server,
    setup_logging,
)
from pump_flow_dmpc import (  # noqa: E402
    PumpFlowDmpcInputResolver,
    PumpFlowDmpcSolver,
    PumpStationFlowDmpcAlgorithm,
)


logger = logging.getLogger(__name__)


def create_pump_flow_dmpc_server(
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """创建仅注册泵站流量 DMPC 的标准 HTTP 服务。"""

    runtime = ControlAlgorithmRuntime()
    runtime.register(
        PumpStationFlowDmpcAlgorithm(
            solver=PumpFlowDmpcSolver(),
            resolver=PumpFlowDmpcInputResolver(),
        )
    )
    return create_control_algorithm_http_server(runtime, host=host, port=port)


class PumpFlowDmpcHttpHost:
    """由智能体 launcher 托管生命周期的泵站流量 DMPC HTTP Host。"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8015,
    ) -> None:
        self._host = host
        self._port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def server_address(self) -> Optional[tuple[str, int]]:
        """返回实际监听地址；服务未启动时返回 ``None``。"""

        if self._server is None:
            return None
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        """注册算法并启动标准 HTTP Server；私有模型在 solve 时解析。"""

        if self._server is not None:
            raise RuntimeError("pump flow DMPC HTTP host is already started")

        server = create_pump_flow_dmpc_server(host=self._host, port=self._port)
        thread = threading.Thread(
            target=server.serve_forever,
            name="pump-flow-dmpc-http-host",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()
        logger.info(
            "Pump flow DMPC HTTP host started: address=%s:%s, algorithmType=%s",
            server.server_address[0],
            server.server_address[1],
            PumpStationFlowDmpcAlgorithm.algorithm_type,
        )

    def stop(self) -> None:
        """停止 HTTP Server 并等待服务线程退出。"""

        server = self._server
        thread = self._thread
        if server is None:
            return

        try:
            server.shutdown()
        finally:
            server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            self._server = None
            self._thread = None
        logger.info("Pump flow DMPC HTTP host stopped")


def main(argv: Optional[Sequence[str]] = None) -> None:
    """启动独立服务；算法运行配置由每次请求的输入信号提供。"""

    parser = argparse.ArgumentParser(description="Hydros pump flow DMPC service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args(argv)

    setup_logging()
    server = create_pump_flow_dmpc_server(host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
