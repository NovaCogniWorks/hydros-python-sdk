"""
Call the service-private ODD-DMPC LocalController from standalone algorithm context.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Dict, List

from hydros_agent_sdk.utils.yaml_loader import YamlLoader

from .odd_dmpc.config import load_runtime_context_from_payload
from .odd_dmpc.flow_service import FlowDepartService
from .odd_dmpc.local_controller import LocalController, StationControlContext
from .odd_dmpc.types import (
    ControlAction,
    LowerFeedback,
    StationMemory,
    TransferBundle,
    SystemConfig,
)

from .errors import PumpFlowDmpcError
from .types import PumpFlowDmpcArguments


class PumpFlowDmpcSolver:
    """Bridge to original ODD-DMPC LocalController."""

    def __init__(self) -> None:
        self._local_controller: LocalController | None = None
        self._system_config: SystemConfig | None = None
        self._flow_service: FlowDepartService | None = None
        self._runtime = None
        self._lower_feedback: LowerFeedback | None = None
        self._available_units_map: Dict[int, List[int]] = {}
        self._loaded_config_source = ""
        self._config_lock = RLock()

    def _ensure_loaded(self, arguments: PumpFlowDmpcArguments) -> None:
        config_source = self._config_source_key(arguments)
        with self._config_lock:
            if (
                self._system_config is not None
                and self._loaded_config_source == config_source
            ):
                return
            payload = self._load_config_payload_for_arguments(arguments)
            try:
                context = load_runtime_context_from_payload(payload)
            except Exception as exc:
                raise PumpFlowDmpcError(
                    "INVALID_RUNTIME_CONFIG",
                    "cannot build pump DMPC runtime from config source %s: %s"
                    % (config_source, exc),
                ) from exc
            effective_payload = context.get("config_payload", payload)
            self._system_config = context["system_config"]
            if not self._system_config.stations:
                raise PumpFlowDmpcError(
                    "INVALID_RUNTIME_CONFIG",
                    "pump DMPC config has no stations: %s" % config_source,
                )
            self._runtime = context["runtime"]
            flow_service_config_path = (
                config_source
                if config_source and not self._is_remote_config(config_source)
                and not arguments.algorithm_params
                else None
            )
            self._flow_service = FlowDepartService(
                self._system_config,
                config_dict=effective_payload,
                config_path=flow_service_config_path,
                cache_dir=str(self._resolve_flow_depart_cache_dir()),
                generation_enabled=False,
            )
            self._local_controller = LocalController(
                system_config=self._system_config,
                runtime=self._runtime,
                flow_service=self._flow_service,
            )
            self._available_units_map = {
                station.id: [unit.id for unit in station.units]
                for station in self._system_config.stations
            }
            self._loaded_config_source = config_source

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

    def solve(self, arguments: PumpFlowDmpcArguments) -> ControlAction:
        self._ensure_loaded(arguments)

        station_id = arguments.station_id
        configured_station_ids = sorted(self._system_config.station_by_id)
        if station_id not in self._system_config.station_by_id:
            raise PumpFlowDmpcError(
                "TARGET_STATION_NOT_CONFIGURED",
                "target station %s is absent from config %s; configured station ids=%s"
                % (station_id, self._loaded_config_source, configured_station_ids),
            )

        # Build StationMemory
        station_memory = StationMemory(
            active_unit_ids=list(arguments.active_unit_ids),
            unit_openings=dict(arguments.unit_openings),
            unit_status=dict(arguments.unit_status),
            time_since_adjust=dict(arguments.time_since_adjust),
            time_since_switch=dict(arguments.time_since_switch),
            last_selected_flow=float(arguments.last_selected_flow),
            mode=arguments.mode,
        )

        # Build TransferBundle
        ref_flow = list(arguments.reference_flow)
        ref_front = list(arguments.reference_front_level)
        ref_back = list(arguments.reference_back_level)
        ref_head = list(arguments.reference_head)

        transfer_bundle = TransferBundle(
            station_id=station_id,
            reference_flow=ref_flow,
            reference_back_level=ref_back,
            reference_front_level=ref_front,
            reference_head=ref_head,
            active_unit_ids=list(arguments.active_unit_ids),
            time_since_adjust=dict(arguments.time_since_adjust),
            time_since_switch=dict(arguments.time_since_switch),
            disturbance_estimate={},
        )

        # Online ODD control uses per-unit performance models directly. Station
        # flow-depart tables are offline planning artifacts, not a solve input.
        station_ctx = StationControlContext(
            station_id=station_id,
            station_model=None,
            available_unit_ids=list(arguments.available_unit_ids),
            basin_levels={},
            basin_profiles=None,
            pool_areas={},
            anchor_basin_levels={},
            boundary_nominal_flows={},
            current_back_level=float(arguments.current_back_level),
            current_front_level=float(arguments.current_front_level),
            current_head=float(arguments.current_head),
            upper_flow_refs={},
            flow_history={},
            boundary_level_plan=None,
            start_time_hours=0.0,
            step_hours=1.0,
            demand_plan=None,
            unit_blade_bounds=dict(arguments.unit_blade_bounds),
            max_blade_delta_per_step=float(arguments.max_blade_delta_per_step),
        )

        return self._local_controller.solve(
            mode=arguments.mode,
            station_ctx=station_ctx,
            upstream_prediction={},
            disturbance_forecast={},
            transfer_bundle=transfer_bundle,
            station_memory=station_memory,
        )
