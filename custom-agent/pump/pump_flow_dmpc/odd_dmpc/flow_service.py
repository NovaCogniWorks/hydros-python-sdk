from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
import pickle
import logging
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from .flow_depart import generate_flow_depart
from .pump_unit import PumpUnit

from .station_model import PumpStationModel
from .types import StationConfig, SystemConfig

logger = logging.getLogger(__name__)


@dataclass
class FlowDepartService:
    system_config: SystemConfig
    config_dict: Optional[Dict] = None
    config_path: Optional[str] = None
    _cache: Dict[Tuple[int, Tuple[int, ...]], pd.DataFrame] = field(default_factory=dict)
    _model_cache: Dict[Tuple[int, Tuple[int, ...]], PumpStationModel] = field(default_factory=dict)
    _unit_model_cache: Dict[int, Dict[int, PumpUnit]] = field(default_factory=dict)
    cache_dir: Optional[str] = None
    generation_enabled: bool = True

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

    def _resolve_cache_path(self) -> Path:
        if self.cache_dir:
            cache_dir = Path(self.cache_dir)
        else:
            config_root = Path(self.config_path or self.system_config.source_config_path).resolve().parent
            cache_dir = config_root / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "flow_depart_cache.pkl"

    def _cache_meta(self) -> Dict[str, float]:
        """Return the generation parameter fingerprint used to validate cached tables."""
        return {
            "step_q": float(getattr(self.system_config, "flow_depart_step_q", 1.0)),
            "step_h": float(getattr(self.system_config, "flow_depart_step_h", 0.1)),
            "rho": float(getattr(self.system_config, "global_rho", 1000.0)),
            "g": float(getattr(self.system_config, "global_g", 9.81)),
        }

    def _cache_meta_matches(self, cached_meta: object) -> bool:
        if not isinstance(cached_meta, dict):
            return False
        current = self._cache_meta()
        for key, expected in current.items():
            cached_value = cached_meta.get(key)
            if cached_value is None:
                return False
            try:
                if abs(float(cached_value) - expected) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    def load_flow_depart_cache(self) -> int:
        cache_path = self._resolve_cache_path()
        if not cache_path.exists():
            logger.info("flow depart cache not found at %s", cache_path)
            return 0
        try:
            with open(cache_path, "rb") as f:
                loaded = pickle.load(f)
            if not isinstance(loaded, dict):
                logger.warning("flow depart cache payload is not a dict at %s", cache_path)
                return 0

            tables = loaded
            if "_meta" in loaded and "_tables" in loaded:
                cached_meta = loaded["_meta"]
                if not self._cache_meta_matches(cached_meta):
                    logger.warning(
                        "flow depart cache is stale at %s (cached meta=%s, current=%s); discarding",
                        cache_path,
                        cached_meta,
                        self._cache_meta(),
                    )
                    return 0
                tables = loaded["_tables"]
            else:
                logger.warning(
                    "flow depart cache uses legacy format without metadata at %s; discarding",
                    cache_path,
                )
                return 0

            if not isinstance(tables, dict):
                logger.warning("flow depart cache tables payload is not a dict at %s", cache_path)
                return 0

            loaded_count = 0
            for key, df in tables.items():
                if isinstance(key, tuple) and len(key) == 2 and isinstance(df, pd.DataFrame):
                    self._cache[key] = df
                    loaded_count += 1
            logger.info("flow depart cache loaded: %d tables from %s", loaded_count, cache_path)
            return loaded_count
        except Exception as e:
            logger.warning("failed to load flow depart cache from %s: %s", cache_path, e)
            return 0

    def save_flow_depart_cache(self) -> None:
        cache_path = self._resolve_cache_path()
        try:
            payload = {
                "_meta": self._cache_meta(),
                "_tables": self._cache,
            }
            with open(cache_path, "wb") as f:
                pickle.dump(payload, f)
            logger.info("flow depart cache saved: %d tables to %s", len(self._cache), cache_path)
        except Exception as e:
            logger.warning("failed to save flow depart cache: %s", e)
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

        if not self.generation_enabled:
            # The edge controller consumes an offline artifact. Reload once so a
            # cache produced after service startup can still become visible, but
            # never fall through to the expensive offline calculation.
            self.load_flow_depart_cache()
            if key in self._cache:
                return self._cache[key].copy()
            raise FileNotFoundError(
                "Precomputed flow depart table is missing for station %s and "
                "available units %s in %s; cached station combinations=%s"
                % (
                    station_id,
                    key[1],
                    self._resolve_cache_path(),
                    sorted(
                        cache_key[1]
                        for cache_key in self._cache
                        if cache_key[0] == station_id
                    ),
                )
            )

        station = self.system_config.station_by_id[station_id]
        
        # 加载所需泵组
        units = [self.get_unit_model(station_id, uid) for uid in key[1]]
        
        # 从系统配置获取参数，或使用默认值
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
        self.save_flow_depart_cache()
        return table.copy()

    def get_station_model(self, station_id: int, available_unit_ids: Iterable[int]) -> PumpStationModel:
        key = self._available_key(station_id, available_unit_ids)
        cached = self._model_cache.get(key)
        if cached is not None:
            return cached

        station = self.system_config.station_by_id[station_id]
        table = self.get_optimal_table(station_id, key[1])
        model = PumpStationModel(station, table)
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
