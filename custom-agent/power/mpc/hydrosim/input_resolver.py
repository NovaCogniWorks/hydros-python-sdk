from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .types import (
    HydroConstraintsData,
    HydroInitialStatesData,
    HydroMpcConfigData,
    HydroSimulationEventData,
    HydroSimulationInputBundle,
    HydroSimulationInputPatch,
)


class HydroSimulationInputResolver:
    """归一化 file/object 输入，并提供 patch 合并能力。"""

    def resolve_bundle(
        self,
        input_bundle: HydroSimulationInputBundle | dict[str, Any] | None = None,
        *,
        time_series_file: str | None = None,
        mpc_config_file: str | None = None,
        initial_states_file: str | None = None,
        constraints_file: str | None = None,
    ) -> HydroSimulationInputBundle:
        if input_bundle is not None:
            return self._normalize_bundle(input_bundle)
        return HydroSimulationInputBundle(
            event=self.load_event_data_from_file(time_series_file, "基础时间序列文件"),
            initial_states=self.load_initial_states_from_file(initial_states_file, "初始状态文件"),
            constraints=self.load_constraints_from_file(constraints_file, "约束文件"),
            mpc_config=self.load_mpc_config_from_file(mpc_config_file, "MPC 配置文件"),
        )

    def resolve_patch(
        self,
        patch: HydroSimulationInputPatch | dict[str, Any] | None = None,
        *,
        time_series_file: str | None = None,
        mpc_config_file: str | None = None,
        initial_states_file: str | None = None,
        constraints_file: str | None = None,
    ) -> HydroSimulationInputPatch:
        if patch is not None:
            return self._normalize_patch(patch)
        return HydroSimulationInputPatch(
            event=self.load_event_data_from_file(time_series_file, "基础时间序列文件") if time_series_file else None,
            initial_states=self.load_initial_states_from_file(initial_states_file, "初始状态文件") if initial_states_file else None,
            constraints=self.load_constraints_from_file(constraints_file, "约束文件") if constraints_file else None,
            mpc_config=self.load_mpc_config_from_file(mpc_config_file, "MPC 配置文件") if mpc_config_file else None,
        )

    def merge_patch(
        self,
        bundle: HydroSimulationInputBundle | dict[str, Any],
        patch: HydroSimulationInputPatch | dict[str, Any],
    ) -> HydroSimulationInputBundle:
        base_bundle = self._normalize_bundle(bundle)
        normalized_patch = self._normalize_patch(patch)
        return HydroSimulationInputBundle(
            event=normalized_patch.event or base_bundle.event,
            initial_states=normalized_patch.initial_states or base_bundle.initial_states,
            constraints=normalized_patch.constraints or base_bundle.constraints,
            mpc_config=normalized_patch.mpc_config or base_bundle.mpc_config,
        )

    def load_event_data_from_file(self, path: str | None, label: str = "时间序列文件") -> HydroSimulationEventData:
        payload = self._read_json_file(path, label)
        return HydroSimulationEventData.model_validate(payload)

    def load_initial_states_from_file(self, path: str | None, label: str = "初始状态文件") -> HydroInitialStatesData:
        payload = self._read_yaml_file(path, label)
        return HydroInitialStatesData.model_validate(payload)

    def load_constraints_from_file(self, path: str | None, label: str = "约束文件") -> HydroConstraintsData:
        payload = self._read_yaml_file(path, label)
        return HydroConstraintsData.model_validate(payload)

    def load_mpc_config_from_file(self, path: str | None, label: str = "MPC 配置文件") -> HydroMpcConfigData:
        payload = self._read_yaml_file(path, label)
        return HydroMpcConfigData(raw=dict(payload))

    def _normalize_bundle(self, input_bundle: HydroSimulationInputBundle | dict[str, Any]) -> HydroSimulationInputBundle:
        if isinstance(input_bundle, HydroSimulationInputBundle):
            return input_bundle
        return HydroSimulationInputBundle.model_validate(input_bundle)

    def _normalize_patch(self, patch: HydroSimulationInputPatch | dict[str, Any]) -> HydroSimulationInputPatch:
        if isinstance(patch, HydroSimulationInputPatch):
            return patch
        return HydroSimulationInputPatch.model_validate(patch)

    def _read_json_file(self, path: str | None, label: str) -> dict[str, Any]:
        if not path:
            raise ValueError(f"{label}不能为空。")
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            raise FileNotFoundError(f"{label}不存在: {path_obj}")
        with open(path_obj, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _read_yaml_file(self, path: str | None, label: str) -> dict[str, Any]:
        if not path:
            return {}
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            raise FileNotFoundError(f"{label}不存在: {path_obj}")
        with open(path_obj, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
