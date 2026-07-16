"""控制算法标准 HTTP 运行时。"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional, Type
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from .models import ControlAlgorithmInput
from .runtime import ControlAlgorithmRuntime


logger = logging.getLogger(__name__)


_EDGE_CONTROL_ALGORITHM_PATH_PREFIX = (
    "engine",
    "v1",
    "api",
    "control-algorithms",
)
_EDGE_DEFAULT_PATH_PREFIX = ("engine", "v1", "api", "edge-control")
_LEGACY_PATH_PREFIX = ("control-algorithms",)
_SUPPORTED_PATH_PREFIXES = (
    _EDGE_CONTROL_ALGORITHM_PATH_PREFIX,
    _EDGE_DEFAULT_PATH_PREFIX,
    _LEGACY_PATH_PREFIX,
)


class ControlAlgorithmHttpService:
    """将已注册的 SDK 控制算法 runtime 暴露为标准 HTTP 服务。"""

    def __init__(self, runtime: ControlAlgorithmRuntime) -> None:
        self._runtime = runtime

    def create_server(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
    ) -> ThreadingHTTPServer:
        """创建 HTTP server；应用层负责启动、关闭和注册具体算法。"""
        return ThreadingHTTPServer((host, port), self._handler_type())

    def _handler_type(self) -> Type[BaseHTTPRequestHandler]:
        runtime = self._runtime

        class ControlAlgorithmRequestHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                algorithm_type = self._algorithm_type()
                if algorithm_type is None:
                    self._write_json(
                        HTTPStatus.NOT_FOUND,
                        {
                            "error_code": "UNSUPPORTED_PATH",
                            "error_message": (
                                "expected /engine/v1/api/control-algorithms/"
                                "{algorithm_type}/solve"
                            ),
                        },
                    )
                    return
                try:
                    payload = self._read_json()
                    logger.info(
                        "Control algorithm HTTP request received: path=%s, "
                        "pathAlgorithmType=%s, payload=%s",
                        self.path,
                        algorithm_type,
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    )
                    input_data = ControlAlgorithmInput.model_validate(payload)
                except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "error_code": "INVALID_ALGORITHM_INPUT",
                            "error_message": str(exc),
                        },
                    )
                    return
                if input_data.algorithm_type != algorithm_type:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "error_code": "ALGORITHM_TYPE_MISMATCH",
                            "error_message": "path algorithm_type does not match request body",
                        },
                    )
                    return

                output = runtime.solve(input_data)
                self._write_json(HTTPStatus.OK, output.model_dump(mode="json"))

            def do_GET(self) -> None:  # noqa: N802
                self._write_json(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    {"error_code": "METHOD_NOT_ALLOWED"},
                )

            def _algorithm_type(self) -> Optional[str]:
                path = urlparse(self.path).path
                parts = [part for part in path.split("/") if part]
                for path_prefix in _SUPPORTED_PATH_PREFIXES:
                    algorithm_index = len(path_prefix)
                    if (
                        len(parts) == algorithm_index + 2
                        and tuple(parts[:algorithm_index]) == path_prefix
                        and parts[-1] == "solve"
                    ):
                        return unquote(parts[algorithm_index])
                return None

            def _read_json(self) -> Any:
                content_length = self.headers.get("Content-Length")
                if content_length is None:
                    raise ValueError("Content-Length is required")
                try:
                    length = int(content_length)
                except ValueError as exc:
                    raise ValueError("Content-Length must be an integer") from exc
                if length < 0:
                    raise ValueError("Content-Length must not be negative")
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def _write_json(self, status: HTTPStatus, payload: Any) -> None:
                body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status.value)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return ControlAlgorithmRequestHandler


def create_control_algorithm_http_server(
    runtime: ControlAlgorithmRuntime,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """创建 SDK 标准控制算法 HTTP server 的便捷入口。"""
    return ControlAlgorithmHttpService(runtime).create_server(host, port)
