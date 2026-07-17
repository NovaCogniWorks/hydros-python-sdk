from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from .models import ControlAlgorithmInput
from .runtime import ControlAlgorithmRuntime


def create_control_algorithm_http_server(
    runtime: ControlAlgorithmRuntime,
    *,
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    class ControlAlgorithmHttpHandler(BaseHTTPRequestHandler):
        server_version = "HydrosPowerControl/1.0"

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path_parts = [part for part in parsed.path.split("/") if part]
            if len(path_parts) != 3 or path_parts[0] != "control-algorithms" or path_parts[2] != "solve":
                self._write_json(
                    HTTPStatus.NOT_FOUND,
                    {"error_code": "NOT_FOUND", "error_message": f"Unsupported path: {parsed.path}"},
                )
                return
            algorithm_type = path_parts[1]
            try:
                payload = self._read_json_body()
                input_data = ControlAlgorithmInput.model_validate(payload)
            except ValueError as exc:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error_code": "INVALID_ALGORITHM_INPUT", "error_message": str(exc)},
                )
                return
            except ValidationError as exc:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error_code": "INVALID_ALGORITHM_INPUT", "error_message": exc.json()},
                )
                return

            if input_data.algorithm_type != algorithm_type:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "error_code": "ALGORITHM_TYPE_MISMATCH",
                        "error_message": (
                            f"Path algorithm_type={algorithm_type} does not match "
                            f"body algorithm_type={input_data.algorithm_type}"
                        ),
                    },
                )
                return

            output = runtime.solve(input_data)
            self._write_json(HTTPStatus.OK, output.model_dump(mode="json", exclude_none=True))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _read_json_body(self) -> dict[str, Any]:
            content_length_header = self.headers.get("Content-Length")
            if content_length_header is None:
                raise ValueError("Missing Content-Length header.")
            content_length = int(content_length_header)
            body = self.rfile.read(content_length)
            if not body:
                raise ValueError("Request body is empty.")
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON body: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            return payload

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), ControlAlgorithmHttpHandler)
