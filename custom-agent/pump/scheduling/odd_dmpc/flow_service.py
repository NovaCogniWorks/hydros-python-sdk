from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from flow_depart import generate_flow_depart
from pump_unit import PumpUnit

from .station_model import PumpStationModel
from .types import StationConfig, SystemConfig


@dataclass
class FlowDepartService:
    system_config: SystemConfig
    config_dict: Optional[Dict] = None
    config_path: Optional[str] = None
    _cache: Dict[Tuple[int, Tuple[int, ...]], pd.DataFrame] = field(default_factory=dict)
    _model_cache: Dict[Tuple[int, Tuple[int, ...]], PumpStationModel] = field(default_factory=dict)
    _unit_model_cache: Dict[int, Dict[int, PumpUnit]] = field(default_factory=dict)

    def _available_key(self, station_id: int, available_unit_ids: Iterable[int]) -> Tuple[int, Tuple[int, ...]]:
        return station_id, tuple(sorted(available_unit_ids))

    def _unit_names(self, station: StationConfig, available_unit_ids: Iterable[int]) -> List[str]:
        id_set = set(available_unit_ids)
        names = [
            unit.name
            for unit in station.units
            if unit.id in id_set
        ]
        if not names:
            raise ValueError(f"No available units provided for station {station.id}")
        return names

    def _resolve_data_file(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() and candidate.exists():
            return candidate
        config_root = Path(self.config_path or self.system_config.source_config_path).resolve().parent
        search_roots = [
            Path.cwd(),
            config_root,
            config_root.parent,
            Path(self.system_config.flow_depart_data_dir),
        ]
        for root in search_roots:
            resolved = (root / candidate).resolve()
            if resolved.exists():
                return resolved
        raise FileNotFoundError(f"Data file not found: {relative_path}")

    def _sheet_name_lookup(self, workbook: pd.ExcelFile, target_sheet: str) -> str:
        lookup = {str(name).strip().lower(): str(name) for name in workbook.sheet_names}
        sheet_name = lookup.get(str(target_sheet).strip().lower())
        if sheet_name is None:
            if len(workbook.sheet_names) == 1:
                return str(workbook.sheet_names[0])
            raise KeyError(f"Sheet '{target_sheet}' not found in {workbook.io}")
        return sheet_name

    def _load_unit_models(self, station_id: int) -> Dict[int, PumpUnit]:
        cached = self._unit_model_cache.get(station_id)
        if cached is not None:
            return cached

        station = self.system_config.station_by_id[station_id]
        unit_models: Dict[int, PumpUnit] = {}
        if all(unit.table_e is not None and unit.table_r is not None for unit in station.units):
            for unit in station.units:
                unit_models[unit.id] = PumpUnit(
                    unit.name,
                    pd.DataFrame(unit.table_e.rows, columns=unit.table_e.columns),
                    pd.DataFrame(unit.table_r.rows, columns=unit.table_r.columns),
                )
        else:
            table_e_path = self._resolve_data_file(station.units_file["tableE"])
            table_r_path = self._resolve_data_file(station.units_file["tableR"])
            with pd.ExcelFile(table_e_path) as workbook_e, pd.ExcelFile(table_r_path) as workbook_r:
                for unit in station.units:
                    sheet_e = self._sheet_name_lookup(workbook_e, unit.name)
                    sheet_r = self._sheet_name_lookup(workbook_r, unit.name)
                    unit_models[unit.id] = PumpUnit(
                        unit.name,
                        workbook_e.parse(sheet_name=sheet_e),
                        workbook_r.parse(sheet_name=sheet_r),
                    )
        for unit in station.units:
            model = unit_models[unit.id]
            if unit.q_min is not None:
                model.q_min = float(unit.q_min)
            if unit.q_max is not None:
                model.q_max = float(unit.q_max)
        self._unit_model_cache[station_id] = unit_models
        return unit_models

    def get_optimal_table(self, station_id: int, available_unit_ids: Iterable[int]) -> pd.DataFrame:
        key = self._available_key(station_id, available_unit_ids)
        if key in self._cache:
            return self._cache[key].copy()

        station = self.system_config.station_by_id[station_id]
        
        # Load the pump units we need
        units = [self.get_unit_model(station_id, uid) for uid in key[1]]
        
        # Get parameters from system config or use defaults
        step_q = getattr(self.system_config, 'flow_depart_step_q', 1.0)
        step_h = getattr(self.system_config, 'flow_depart_step_h', 0.1)
        rho = getattr(self.system_config, 'global_rho', 1000.0)
        g = getattr(self.system_config, 'global_g', 9.81)
        
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            table = generate_flow_depart(
                station_id=station_id,
                units=units,
                step_q=step_q,
                step_h=step_h,
                rho=rho,
                g=g
            )
        if table is None or table.empty:
            raise ValueError(f"Unable to generate flow depart table for station {station_id} and units {key[1]}")
        self._cache[key] = table.copy()
        return table.copy()

    def get_station_model(self, station_id: int, available_unit_ids: Iterable[int]) -> PumpStationModel:
        key = self._available_key(station_id, available_unit_ids)
        cached = self._model_cache.get(key)
        if cached is not None:
            return cached

        station = self.system_config.station_by_id[station_id]
        if key not in self._cache:
            self.get_optimal_table(station_id, key[1])
        model = PumpStationModel(station, self._cache[key])
        self._model_cache[key] = model
        return model

    def get_unit_model(self, station_id: int, unit_id: int) -> PumpUnit:
        station = self.system_config.station_by_id[station_id]
        if unit_id not in station.unit_name_by_id:
            raise KeyError(f"Unit {unit_id} not found in station {station_id}")
        return self._load_unit_models(station_id)[unit_id]

    def estimate_unit_efficiency(self, station_id: int, unit_id: int, flow: float, head: float) -> Optional[float]:
        unit_model = self.get_unit_model(station_id, unit_id)
        return float(unit_model.predict_efficiency(flow, head))
