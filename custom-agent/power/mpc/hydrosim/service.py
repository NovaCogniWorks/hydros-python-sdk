from __future__ import annotations

import contextlib
import io
import tempfile
from dataclasses import replace
from typing import Any, Dict

from .core import HydroSimulationCore
from .types import HydroConfiguredSimulationRequest, HydroOutputMode, HydroRandomSimulationRequest


class HydroSimulationService:
    """外部调用类：屏蔽内部装配细节，对外提供稳定调用入口。"""

    def __init__(self, core: HydroSimulationCore | None = None) -> None:
        self.core = core or HydroSimulationCore()

    def run_random(
        self,
        request: HydroRandomSimulationRequest | None = None,
        output_mode: HydroOutputMode = "mixed",
        **kwargs,
    ) -> Dict[str, Any]:
        effective_request = request or HydroRandomSimulationRequest(**kwargs)
        if output_mode == "json":
            return self._run_random_json_only(effective_request)
        return self.core.run_random(effective_request).to_dict(mode=output_mode)

    def run_configured(
        self,
        request: HydroConfiguredSimulationRequest | None = None,
        output_mode: HydroOutputMode = "mixed",
        **kwargs,
    ) -> Dict[str, Any]:
        effective_request = request or HydroConfiguredSimulationRequest(**kwargs)
        if output_mode == "json":
            return self._run_configured_json_only(effective_request)
        return self.core.run_configured(effective_request).to_dict(mode=output_mode)

    def _run_random_json_only(self, request: HydroRandomSimulationRequest) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="hydrosim_json_") as temp_dir:
            temp_request = replace(request, output_dir=temp_dir, make_plots=False)
            with contextlib.redirect_stdout(io.StringIO()):
                result = self.core.run_random(temp_request).to_dict(mode="json")
            return self._sanitize_json_result(result)

    def _run_configured_json_only(self, request: HydroConfiguredSimulationRequest) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="hydrosim_json_") as temp_dir:
            temp_request = replace(request, output_dir=temp_dir, make_plots=False)
            with contextlib.redirect_stdout(io.StringIO()):
                result = self.core.run_configured(temp_request).to_dict(mode="json")
            return self._sanitize_json_result(result)

    def _sanitize_json_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = dict(result)
        run_summary = sanitized.get("run_summary")
        if isinstance(run_summary, dict):
            run_summary = dict(run_summary)
            run_summary.pop("outputs", None)
            run_summary.pop("output_dir", None)
            sanitized["run_summary"] = run_summary
        return sanitized
