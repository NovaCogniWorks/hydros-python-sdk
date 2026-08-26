"""仅用于 edge 与 custom-agent 联调的无计算控制算法探针服务。"""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Optional, Sequence

# 直接启动探针时需要显式暴露 SDK 项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hydros_agent_sdk import (
    ControlAlgorithmInput,
    ControlAlgorithmOutput,
    ControlAlgorithmRuntime,
    ControlAlgorithmStatus,
    create_control_algorithm_http_server,
    setup_logging,
)


class ControlAlgorithmContractProbe:
    """为 ``pump_station_flow_dmpc`` 返回 ``HOLD`` 的确定性联调替身。"""

    algorithm_type = "pump_station_flow_dmpc"
    algorithm_version = "1.0.0"

    def solve(self, input_data: ControlAlgorithmInput) -> ControlAlgorithmOutput:
        """确认标准输入可被接收，但不生成任何候选执行器目标。"""
        return ControlAlgorithmOutput(
            schema_version=input_data.schema_version,
            request_id=input_data.context.request_id,
            status=ControlAlgorithmStatus.HOLD,
            reason="CONTRACT_PROBE_ONLY",
            evidence={
                "mode": "dry_run",
                "implementation": "control_contract_probe",
                "algorithm_type": self.algorithm_type,
                "algorithm_version": self.algorithm_version,
            },
        )


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

    setup_logging()
    server = create_control_algorithm_contract_probe_server(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
