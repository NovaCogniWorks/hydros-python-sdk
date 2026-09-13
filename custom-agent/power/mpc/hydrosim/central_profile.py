"""Project the Central Power DB profile into the imported V47 runtime inputs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from . import config as hydrosim_config
from .core import HydroSimulationCore


_INTER_STATION_PARAMETER_KEYS = frozenset(
    {
        "inter_station_efficiency_factor",
        "low_stage_inter_station_efficiency_factor",
        "low_stage_relief_deadband_m",
        "low_stage_factor_start_m",
        "low_stage_factor_full_m",
        "upstream_efficiency_recovery_gain",
        "inflow_deficit_balance_gain",
        "inflow_deficit_balance_deadband_m3s",
        "flow_rebalance_deadband_m3s",
        "flow_rebalance_max_delta_p",
        "slow_rebalance_max_delta_p",
        "slow_rebalance_max_delta_q_m3s",
        "low_stage_pubugou_priority_spread_tolerance_m3s",
        "stage_pid_enable",
        "stage_pid_deadband_m",
        "stage_pid_kp_mw_per_m",
        "stage_pid_ki_mw_per_m_step",
        "stage_pid_kd_mw_per_m",
        "stage_pid_max_delta_p",
        "stage_pid_output_limit_p",
        "stage_pid_forecast_min_scale",
        "stage_pid_forecast_full_deficit_m3s",
        "stage_pid_integral_limit_m_step",
        "stage_mpc_enable",
        "stage_mpc_horizon_steps",
        "stage_mpc_stage_weight",
        "stage_mpc_forecast_weight",
        "stage_mpc_flow_spread_weight",
        "stage_mpc_move_weight",
        "stage_mpc_min_improve",
        "stage_mpc_candidate_fracs",
    }
)

_STATION_CONSTRAINT_KEYS = _INTER_STATION_PARAMETER_KEYS | frozenset(
    {
        "design_head",
        "design_power",
        "min_power",
        "max_power",
        "stair_min_step_p",
        "unit_min_step_p",
        "station_target_ramp_rate",
    }
)

_RESERVOIR_PARAMETER_KEYS = frozenset(
    {
        "min_stage",
        "design_stage",
        "max_stage",
        "min_capacity",
        "design_capacity",
        "max_capacity",
        "Kp",
        "Ki",
        "Kd",
        "use_integral",
        "spill_ff_enable",
        "spill_ff_gain",
        "spill_ff_deadband",
        "spill_ff_gain_yellow_high",
        "spill_ff_gain_red_high",
        "spill_ff_high_deadband",
        "spill_ff_high_green_band",
        "spill_ff_high_yellow_band",
        "max_spill_q",
        "spill_ff_stage_guard_enable",
        "spill_ff_stage_guard_band",
        "spill_ramp_rate",
    }
)

_RESERVOIR_ALIASES = {
    "target_stage": "design_stage",
    "pid_kp": "Kp",
    "pid_ki": "Ki",
    "pid_kd": "Kd",
    "max_spill_flow": "max_spill_q",
}

_TOP_LEVEL_KEYS = frozenset({"planning", "allocation", "reservoir_release"})


def build_central_power_runtime_core(
    profile: Mapping[str, Any],
    *,
    reservoir_step_seconds: int,
) -> tuple[HydroSimulationCore, dict[str, Any]]:
    """Build a V47 runtime core from one resolved central Power profile.

    The profile also carries outer ``planning`` parameters, but those are consumed
    by Power scheduling and deliberately do not enter the V47/HydroReservoir core.
    Edge station/gate profiles remain outside this projection.
    """
    if not isinstance(profile, Mapping):
        raise ValueError("central Power profile must be an object")
    _reject_unsupported_keys(profile, _TOP_LEVEL_KEYS, "central Power profile")
    if not profile:
        raise ValueError("central Power profile must not be empty")
    if int(reservoir_step_seconds) <= 0:
        raise ValueError("reservoir_step_seconds must be positive")

    flow_configs = deepcopy(hydrosim_config.FLOW_CONFIGS)
    flow_station_cfgs = deepcopy(hydrosim_config.FLOW_STATION_CFGS)
    power_configs = deepcopy(hydrosim_config.POWER_CONFIGS)
    unit_configs = deepcopy(hydrosim_config.UNIT_CONFIGS)

    allocation = _mapping(profile.get("allocation"), "allocation")
    _reject_unsupported_keys(
        allocation,
        _INTER_STATION_PARAMETER_KEYS | frozenset({"station_constraints"}),
        "allocation",
    )
    inter_parameters = {
        key: value
        for key, value in allocation.items()
        if key != "station_constraints"
    }
    _apply_parameters_to_all_stations(power_configs, inter_parameters)
    _apply_station_constraints(power_configs, allocation.get("station_constraints"))

    reservoir_release = _mapping(profile.get("reservoir_release"), "reservoir_release")
    _reject_unsupported_keys(
        reservoir_release,
        frozenset({"stations"}),
        "reservoir_release",
    )
    ignored_legacy_time_steps = _apply_reservoir_release(
        flow_configs,
        reservoir_release.get("stations"),
    )
    for flow_config in flow_configs:
        flow_config["time_steps"] = int(reservoir_step_seconds)

    return (
        HydroSimulationCore(
            flow_configs=flow_configs,
            flow_station_cfgs=flow_station_cfgs,
            power_configs=power_configs,
            unit_configs=unit_configs,
            capa_loc=hydrosim_config.CAPA_LOC,
        ),
        {
            "source": "resolved_agent_params",
            "inter_station_parameter_keys": sorted(inter_parameters),
            "station_constraint_count": len(allocation.get("station_constraints") or []),
            "reservoir_release_count": len(reservoir_release.get("stations") or []),
            "reservoir_step_seconds": int(reservoir_step_seconds),
            "reservoir_step_source": "simulation_runtime_options.output_step_seconds",
            "ignored_legacy_time_steps_count": len(ignored_legacy_time_steps),
            "ignored_legacy_time_steps": ignored_legacy_time_steps,
        },
    )


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _apply_parameters_to_all_stations(
    power_configs: list[dict[str, Any]],
    parameters: Mapping[str, Any],
) -> None:
    _reject_unsupported_keys(parameters, _INTER_STATION_PARAMETER_KEYS, "allocation.inter_station.parameters")
    for config in power_configs:
        config.update(parameters)


def _apply_station_constraints(
    power_configs: list[dict[str, Any]],
    constraints: Any,
) -> None:
    if constraints is None:
        return
    if not isinstance(constraints, list):
        raise ValueError("allocation.inter_station.station_constraints must be a list")

    for item in constraints:
        if not isinstance(item, Mapping):
            raise ValueError("allocation.inter_station.station_constraints entries must be objects")
        station_object_id = item.get("station_object_id")
        try:
            station_index = hydrosim_config.STATION_NODE_IDS.index(int(station_object_id))
        except (TypeError, ValueError):
            raise ValueError(f"unknown station_object_id: {station_object_id!r}") from None

        parameters = _mapping(item.get("parameters"), "station constraint parameters")
        values = {key: value for key, value in item.items() if key not in {"station_object_id", "parameters"}}
        values.update(parameters)
        _reject_unsupported_keys(values, _STATION_CONSTRAINT_KEYS, "allocation.inter_station.station_constraints")
        power_configs[station_index].update(values)


def _apply_reservoir_release(
    flow_configs: list[dict[str, Any]],
    stations: Any,
) -> list[dict[str, Any]]:
    if stations is None:
        return []
    if not isinstance(stations, list):
        raise ValueError("reservoir_release.stations must be a list")

    ignored_legacy_time_steps: list[dict[str, Any]] = []
    for item in stations:
        if not isinstance(item, Mapping):
            raise ValueError("reservoir_release.stations entries must be objects")
        station_object_id = item.get("station_object_id")
        try:
            station_index = hydrosim_config.STATION_NODE_IDS.index(int(station_object_id))
        except (TypeError, ValueError):
            raise ValueError(f"unknown reservoir station_object_id: {station_object_id!r}") from None

        parameters = _mapping(item.get("parameters"), "reservoir release parameters")
        values = {key: value for key, value in item.items() if key not in {"station_object_id", "parameters"}}
        values.update(parameters)
        if "time_steps" in values:
            ignored_legacy_time_steps.append(
                {
                    "station_object_id": int(station_object_id),
                    "configured_time_steps": values["time_steps"],
                    "effective": False,
                }
            )
            values.pop("time_steps")
        normalized = {_RESERVOIR_ALIASES.get(key, key): value for key, value in values.items()}
        _reject_unsupported_keys(normalized, _RESERVOIR_PARAMETER_KEYS, "reservoir_release.stations")
        flow_configs[station_index].update(normalized)
    return ignored_legacy_time_steps


def _reject_unsupported_keys(values: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unsupported = sorted(set(values) - allowed)
    if unsupported:
        raise ValueError(f"unsupported {path} keys: {', '.join(unsupported)}")
