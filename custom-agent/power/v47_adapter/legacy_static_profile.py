from __future__ import annotations

from typing import Any, Dict, Mapping

from mpc.hydrosim.config import STATION_NODE_IDS, UNIT_CONFIGS, UNIT_OBJECT_IDS, validate_hydrosim_config


class LegacyHydrosimV47ProfileProvider:
    """Temporary bridge from the existing 200060 static model to V47 inputs.

    Runtime observations are intentionally excluded. A DB/runtime profile or
    explicit algorithm parameter always takes precedence over these defaults.
    """

    source_name = "legacy_hydrosim_config"

    _STATIC_FIELDS = (
        "design_head",
        "min_head",
        "max_head",
        "min_power",
        "max_power",
        "design_power",
        "design_efficiency",
        "eta_head_coeff",
        "eta_power_coeff",
        "power_ramp_rate",
    )

    _PARAMETER_ALIASES = {
        "min_power": ("min_power", "min_power_mw"),
        "max_power": ("max_power", "max_power_mw"),
        "power_ramp_rate": ("power_ramp_rate", "power_ramp_rate_mw"),
    }

    def __init__(self) -> None:
        validate_hydrosim_config()
        self._turbine_defaults = self._build_turbine_defaults()

    def merge_turbine_attributes(
        self,
        station_id: int,
        turbine_id: int,
        attributes: Mapping[str, Any],
        algorithm_parameters: Mapping[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(attributes)
        source_hints = dict(merged.get("v47_parameter_sources") or {})
        defaults = self._turbine_defaults.get(int(station_id), {}).get(int(turbine_id), {})
        for field_name, value in defaults.items():
            aliases = self._PARAMETER_ALIASES.get(field_name, (field_name,))
            if any(merged.get(alias) is not None for alias in aliases):
                continue
            if any(algorithm_parameters.get(alias) is not None for alias in aliases):
                continue
            merged[field_name] = value
            source_hints[field_name] = self.source_name
        if source_hints:
            merged["v47_parameter_sources"] = source_hints
        return merged

    @classmethod
    def _build_turbine_defaults(cls) -> Dict[int, Dict[int, Dict[str, Any]]]:
        result: Dict[int, Dict[int, Dict[str, Any]]] = {}
        for station_id, object_ids, unit_configs in zip(STATION_NODE_IDS, UNIT_OBJECT_IDS, UNIT_CONFIGS):
            station_defaults: Dict[int, Dict[str, Any]] = {}
            for object_id, unit_config in zip(object_ids, unit_configs):
                station_defaults[int(object_id)] = {
                    field_name: unit_config[field_name]
                    for field_name in cls._STATIC_FIELDS
                    if unit_config.get(field_name) is not None
                }
            result[int(station_id)] = station_defaults
        return result
