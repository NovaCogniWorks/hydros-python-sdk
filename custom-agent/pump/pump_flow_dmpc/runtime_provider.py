"""Build request-scoped runtime contexts for the pump-flow DMPC solver."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Optional

from hydros_agent_sdk.utils.yaml_loader import YamlLoader

from .errors import PumpFlowDmpcError
from .odd_dmpc.config import load_runtime_context_from_payload
from .odd_dmpc.flow_service import FlowDepartService
from .odd_dmpc.local_controller import LocalController
from .odd_dmpc.types import RuntimeParameters, SystemConfig
from .types import PumpFlowDmpcArguments


@dataclass(frozen=True)
class PumpFlowDmpcRuntimeContext:
    """A complete runtime bundle bound to one deterministic config source."""

    config_source: str
    system_config: SystemConfig
    runtime: RuntimeParameters
    flow_service: FlowDepartService
    local_controller: LocalController
    solve_lock: Any = field(default_factory=RLock, repr=False, compare=False)


class PumpFlowDmpcRuntimeProvider:
    """Resolve and cache the latest immutable pump-flow runtime bundle."""

    def __init__(self) -> None:
        self._cached_context: Optional[PumpFlowDmpcRuntimeContext] = None
        self._config_lock = RLock()

    def resolve(self, arguments: PumpFlowDmpcArguments) -> PumpFlowDmpcRuntimeContext:
        """Return a context that remains valid for the complete caller request."""

        config_source = self._config_source_key(arguments)
        with self._config_lock:
            cached = self._cached_context
            if cached is not None and cached.config_source == config_source:
                return cached

            context = self._create_context(arguments, config_source)
            self._cached_context = context
            return context

    def _create_context(
        self,
        arguments: PumpFlowDmpcArguments,
        config_source: str,
    ) -> PumpFlowDmpcRuntimeContext:
        payload = self._load_config_payload_for_arguments(arguments)
        try:
            loaded = load_runtime_context_from_payload(payload)
        except Exception as exc:
            raise PumpFlowDmpcError(
                "INVALID_RUNTIME_CONFIG",
                "cannot build pump DMPC runtime from config source %s: %s"
                % (config_source, exc),
            ) from exc

        effective_payload = loaded.get("config_payload", payload)
        system_config = loaded["system_config"]
        if not system_config.stations:
            raise PumpFlowDmpcError(
                "INVALID_RUNTIME_CONFIG",
                "pump DMPC config has no stations: %s" % config_source,
            )
        runtime = loaded["runtime"]
        flow_service_config_path = (
            config_source
            if config_source
            and not self._is_remote_config(config_source)
            and not arguments.algorithm_params
            else None
        )
        flow_service = FlowDepartService(
            system_config,
            config_dict=effective_payload,
            config_path=flow_service_config_path,
            cache_dir=str(self._resolve_flow_depart_cache_dir()),
            generation_enabled=False,
        )
        local_controller = LocalController(
            system_config=system_config,
            runtime=runtime,
            flow_service=flow_service,
        )
        return PumpFlowDmpcRuntimeContext(
            config_source=config_source,
            system_config=system_config,
            runtime=runtime,
            flow_service=flow_service,
            local_controller=local_controller,
        )

    @staticmethod
    def _is_remote_config(config_source: str) -> bool:
        return config_source.startswith("http://") or config_source.startswith("https://")

    @staticmethod
    def _resolve_flow_depart_cache_dir() -> Path:
        """Return the application-level offline artifact directory."""

        return Path(__file__).resolve().parents[1] / ".cache"

    def _load_config_payload(self, config_source: str) -> dict:
        if not config_source:
            raise PumpFlowDmpcError(
                "CONFIG_NOT_FOUND",
                "pump DMPC config source is required",
            )
        try:
            if self._is_remote_config(config_source):
                payload = YamlLoader.from_url(config_source)
            else:
                if not os.path.exists(config_source):
                    raise PumpFlowDmpcError(
                        "CONFIG_NOT_FOUND",
                        "config path not available: %s" % config_source,
                    )
                payload = YamlLoader.from_file(config_source)
        except PumpFlowDmpcError:
            raise
        except Exception as exc:
            raise PumpFlowDmpcError(
                "CONFIG_LOAD_FAILED",
                "cannot load pump DMPC config from %s: %s" % (config_source, exc),
            ) from exc
        if not isinstance(payload, dict):
            raise PumpFlowDmpcError(
                "INVALID_RUNTIME_CONFIG",
                "pump DMPC config is not a mapping: %s" % config_source,
            )
        return payload

    def _load_config_payload_for_arguments(self, arguments: PumpFlowDmpcArguments) -> dict:
        if arguments.algorithm_params:
            return self._payload_from_algorithm_params(arguments)
        return self._load_config_payload(str(arguments.config_path or "").strip())

    def _payload_from_algorithm_params(self, arguments: PumpFlowDmpcArguments) -> dict:
        lower_controller = self._lower_controller_params(arguments.algorithm_params)
        control_horizon = int(lower_controller.get("control_horizon_lower", 10))
        return {
            "flow_depart": {
                "step_q": 1.0,
                "step_h": 0.1,
            },
            "scheduling": {
                "horizon_hours": max(control_horizon, 1),
                "dt_hours": 1,
                "target_avg_flow_last_station": (
                    float(arguments.reference_flow[0])
                    if arguments.reference_flow
                    else 0.0
                ),
            },
            "runtime": dict(arguments.algorithm_params),
        }

    @staticmethod
    def _lower_controller_params(algorithm_params: dict) -> dict:
        raw_lower = algorithm_params.get("lower_controller", {})
        raw_odd = algorithm_params.get("odd", {})
        if not raw_lower and isinstance(raw_odd, dict):
            raw_lower = raw_odd.get("lower_controller", {})
        return dict(raw_lower) if isinstance(raw_lower, dict) else {}

    @staticmethod
    def _config_source_key(arguments: PumpFlowDmpcArguments) -> str:
        if arguments.algorithm_params:
            serialized = json.dumps(
                arguments.algorithm_params,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            return "parameters.algorithm_params:%s" % serialized
        return str(arguments.config_path or "").strip()
