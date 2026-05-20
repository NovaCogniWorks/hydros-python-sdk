from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple
from urllib import request
from urllib.error import HTTPError, URLError


class ThreadClientError(RuntimeError):
    pass


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _encode_multipart_formdata(
    fields: Iterable[Tuple[str, str]],
    files: Iterable[Tuple[str, str, bytes, Optional[str]]],
) -> Tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    parts = []
    for name, value in fields:
        parts.extend(
            [
                f"--{boundary}".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
                b"",
                str(value).encode("utf-8"),
            ]
        )
    for field_name, filename, content, content_type in files:
        resolved_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.extend(
            [
                f"--{boundary}".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{filename}"'
                ).encode("utf-8"),
                f"Content-Type: {resolved_type}".encode("utf-8"),
                b"",
                content,
            ]
        )
    parts.append(f"--{boundary}--".encode("utf-8"))
    parts.append(b"")
    body = b"\r\n".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


class RemoteThreadClient:
    def __init__(self, base_url: str, timeout_seconds: float = 300.0) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.timeout_seconds = float(timeout_seconds)

    def _url(self, suffix: str) -> str:
        return f"{self.base_url}{suffix}"

    def _decode_response(self, response) -> Mapping[str, object]:
        raw = response.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ThreadClientError(f"Invalid JSON response from {response.geturl()}: {exc}") from exc

    def _post_json(self, url: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return self._decode_response(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ThreadClientError(f"HTTP {exc.code} calling {url}: {detail}") from exc
        except URLError as exc:
            raise ThreadClientError(f"Unable to reach {url}: {exc}") from exc

    def create_thread(
        self,
        hydro_model_path: str,
        is_steady_state: bool,
        uuid_value: Optional[str] = None,
    ) -> Mapping[str, object]:
        path = Path(hydro_model_path)
        if not path.exists():
            raise ThreadClientError(f"Hydro model file does not exist: {path}")
        file_bytes = path.read_bytes()
        fields = [("is_steady_state", "true" if is_steady_state else "false")]
        if uuid_value:
            fields.append(("uuid", uuid_value))
        body, content_type = _encode_multipart_formdata(
            fields=fields,
            files=[("file", path.name, file_bytes, "application/json")],
        )
        req = request.Request(
            self._url("/api/thread/create"),
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return self._decode_response(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ThreadClientError(f"HTTP {exc.code} calling create_thread: {detail}") from exc
        except URLError as exc:
            raise ThreadClientError(f"Unable to reach create_thread endpoint: {exc}") from exc

    def update_thread(self, uuid_value: str, updates: Iterable[Mapping[str, object]]) -> Mapping[str, object]:
        payload = {"uuid": uuid_value, "updates": list(updates)}
        return self._post_json(self._url("/api/thread/update"), payload)

    def start_sync(self, uuid_value: str, dt_seconds: int, steps: int) -> Mapping[str, object]:
        payload = {"uuid": uuid_value, "dt": int(dt_seconds), "steps": int(steps)}
        return self._post_json(self._url("/api/thread/start_sync"), payload)
