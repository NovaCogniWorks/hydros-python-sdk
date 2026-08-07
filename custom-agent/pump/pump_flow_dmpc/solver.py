"""
Call the service-private ODD-DMPC LocalController from standalone algorithm context.
"""

from __future__ import annotations

import os
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
        config_source = str(arguments.config_path or "").strip()
        with self._config_lock:
            if (
                self._system_config is not None
                and self._loaded_config_source == config_source
            ):
                return
            payload = self._load_config_payload(config_source)
            try:
                context = load_runtime_context_from_payload(payload)
            except Exception as exc:
                raise PumpFlowDmpcError(
                    "INVALID_RUNTIME_CONFIG",
                    "cannot build pump DMPC runtime from config source %s: %s"
                    % (config_source, exc),
                ) from exc
            self._system_config = context["system_config"]
            self._runtime = context["runtime"]
            flow_service_config_path = (
                config_source
                if config_source and not self._is_remote_config(config_source)
                else None
            )
            self._flow_service = FlowDepartService(
                self._system_config,
                config_dict=payload,
                config_path=flow_service_config_path,
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
        if not isinstance(payload, dict) or not payload.get("stations"):
            raise PumpFlowDmpcError(
                "INVALID_RUNTIME_CONFIG",
                "pump DMPC config has no stations: %s" % config_source,
            )
        return payload

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

        # Build StationControlContext
        station_model = self._flow_service.get_station_model(
            station_id, arguments.available_unit_ids
        )

        station_ctx = StationControlContext(
            station_id=station_id,
            station_model=station_model,
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
        )

        return self._local_controller.solve(
            mode=arguments.mode,
            station_ctx=station_ctx,
            upstream_prediction={},
            disturbance_forecast={},
            transfer_bundle=transfer_bundle,
            station_memory=station_memory,
        )
