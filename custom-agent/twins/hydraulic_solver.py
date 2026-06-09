"""
Hydraulic Solver implementation using corelib HydroSimulator.

This module wraps the low-level simulator and adds:
1. per-job solver lifecycle management
2. boundary/control injection helpers
3. snapshot-based forecast execution without mutating realtime state
"""

import copy
import logging
import os
import threading
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError

# Add current directory to path for local imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in __import__('sys').path:
    __import__('sys').path.insert(0, _SCRIPT_DIR)

# Add idz directory to path for corelib import
_idz_dir = os.path.join(os.path.dirname(__file__), '..', 'idz')
if _idz_dir not in __import__('sys').path:
    __import__('sys').path.insert(0, _idz_dir)

from corelib.core.hydro_simulator import HydroSimulator
from hydros_agent_sdk.utils.yaml_loader import fetch_url_text
from simulation_states import BoundaryState, DeviceControl

logger = logging.getLogger(__name__)


class HydraulicSolver:
    """Hydraulic solver using corelib HydroSimulator."""

    _solvers: Dict[str, 'HydraulicSolver'] = {}
    _lock = threading.RLock()

    @classmethod
    def get_or_create(cls, job_instance_id: str) -> 'HydraulicSolver':
        with cls._lock:
            if job_instance_id not in cls._solvers:
                solver = cls(job_instance_id)
                cls._solvers[job_instance_id] = solver
                logger.info(f"Created hydraulic solver for job: {job_instance_id}")
            return cls._solvers[job_instance_id]

    @classmethod
    def get(cls, job_instance_id: str) -> Optional['HydraulicSolver']:
        with cls._lock:
            return cls._solvers.get(job_instance_id)

    @classmethod
    def remove(cls, job_instance_id: str) -> None:
        with cls._lock:
            if job_instance_id not in cls._solvers:
                return

            solver = cls._solvers.pop(job_instance_id)
            if getattr(solver, 'sim', None) and hasattr(solver.sim, 'cleanup'):
                try:
                    solver.sim.cleanup()
                except Exception as exc:
                    logger.warning(f"Failed to cleanup simulator for {job_instance_id}: {exc}")

            cls._cleanup_idz_config(job_instance_id)
            logger.info(f"Removed hydraulic solver for job: {job_instance_id}")

    @classmethod
    def _cleanup_idz_config(cls, job_instance_id: str) -> None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.abspath(os.path.join(script_dir, '..', '..', 'data'))
        file_path = os.path.join(data_dir, f"idz_config_{job_instance_id}.yml")

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Removed IDZ config file: {file_path}")
        except Exception as exc:
            logger.warning(f"Failed to remove IDZ config file {file_path}: {exc}", exc_info=True)

    def __init__(self, job_instance_id: str):
        self.job_instance_id = job_instance_id
        self.sim = None
        self.topology = None
        self.simulation_states: Dict[int, Any] = {}
        self.controls: Dict[int, Dict[str, DeviceControl]] = {}
        self.boundary_params: Dict[int, Dict[str, BoundaryState]] = {}
        self.initial_states: Dict[int, Any] = {}
        self.initial_states_source_data: Dict[str, Any] = {}
        self.state: Dict[int, Dict[str, float]] = {}
        logger.info(f"Hydraulic solver initialized for job: {job_instance_id}")

    def initialize(self, topology, idz_config_url: str, initial_states_url: Optional[str] = None) -> None:
        logger.info("Initializing hydraulic solver with topology")
        self.topology = topology

        idz_config_file = self._download_idz_config(idz_config_url, initial_states_url)
        if not idz_config_file:
            raise RuntimeError("Failed to download IDZ configuration file")

        self.sim = HydroSimulator(idz_config_file)
        logger.info(f"HydroSimulator created, num_nodes={self.sim.num_nodes}")

        self.initial_states = self.sim.get_initial_states()
        self.simulation_states = copy.deepcopy(self.initial_states)
        self.controls = self._build_default_controls(self.simulation_states)
        self.boundary_params = self._build_default_boundary_params(self.simulation_states)
        self.state = self.export_results_from_states(self.simulation_states)

        logger.info(
            "Hydraulic solver ready: states=%s, controls=%s, boundaries=%s",
            len(self.simulation_states),
            len(self.controls),
            len(self.boundary_params),
        )

    def snapshot(self) -> Dict[str, Any]:
        """Return a deep-copied mutable snapshot for forecast execution."""
        return {
            'simulation_states': copy.deepcopy(self.simulation_states),
            'controls': copy.deepcopy(self.controls),
            'boundary_params': copy.deepcopy(self.boundary_params),
        }

    def get_current_results(self) -> Dict[int, Dict[str, float]]:
        return self.export_results_from_states(self.simulation_states)

    def solve_step(
        self,
        step: int,
        boundary_conditions: Optional[Dict[int, Dict[str, float]]] = None,
        control_conditions: Optional[Dict[int, Dict[str, float]]] = None,
    ) -> Dict[int, Dict[str, float]]:
        """Execute one realtime step and persist the resulting state."""
        snapshot = self.snapshot()
        snapshot, output_results = self.solve_step_from_snapshot(
            step=step,
            snapshot=snapshot,
            boundary_conditions=boundary_conditions,
            control_conditions=control_conditions,
        )
        self.simulation_states = snapshot['simulation_states']
        self.controls = snapshot['controls']
        self.boundary_params = snapshot['boundary_params']
        self.state = copy.deepcopy(output_results)
        return output_results

    def solve_step_from_snapshot(
        self,
        step: int,
        snapshot: Dict[str, Any],
        boundary_conditions: Optional[Dict[int, Dict[str, float]]] = None,
        control_conditions: Optional[Dict[int, Dict[str, float]]] = None,
    ) -> tuple[Dict[str, Any], Dict[int, Dict[str, float]]]:
        """Execute one forecast step based on an external snapshot."""
        if not self.sim:
            raise RuntimeError('Hydraulic solver is not initialized')

        simulation_states = snapshot['simulation_states']
        controls = snapshot['controls']
        boundary_params = snapshot['boundary_params']

        self._apply_boundary_conditions(boundary_params, boundary_conditions or {})
        self._apply_control_conditions(controls, control_conditions or {})

        try:
            new_states, _ = self.sim.step(
                controls=controls,
                boundary_params=boundary_params,
                simulation_states=simulation_states,
            )
        except Exception as exc:
            logger.error(f"Step {step} simulation failed: {exc}", exc_info=True)
            raise

        output_results = self.export_results_from_states(new_states)
        snapshot['simulation_states'] = new_states
        snapshot['controls'] = controls
        snapshot['boundary_params'] = boundary_params

        # logger.info(f"Simulation step {step} completed with {len(output_results)} objects")
        return snapshot, output_results

    def update_controls(self, controls_update: Dict[int, Dict[str, DeviceControl]]) -> None:
        for node_id, device_controls in controls_update.items():
            if node_id not in self.controls:
                self.controls[node_id] = {}
            self.controls[node_id].update(device_controls)
        logger.info(f"Updated controls for {len(controls_update)} nodes")

    def update_boundary_params(self, boundary_update: Dict[int, Dict[str, BoundaryState]]) -> None:
        for node_id, boundaries in boundary_update.items():
            if node_id not in self.boundary_params:
                self.boundary_params[node_id] = {}
            self.boundary_params[node_id].update(boundaries)
        logger.info(f"Updated boundary params for {len(boundary_update)} nodes")

    def export_results_from_states(self, simulation_states: Dict[int, Any]) -> Dict[int, Dict[str, float]]:
        output_results: Dict[int, Dict[str, float]] = {}
        for node_id, state in simulation_states.items():
            output_results[node_id] = {
                'water_level': float(getattr(state.station_state, 'h_i_t', 0.0)),
                'water_flow': float(getattr(state.station_state, 'qtot_i_t', 0.0)),
            }
        return output_results

    def _build_default_controls(self, simulation_states: Dict[int, Any]) -> Dict[int, Dict[str, DeviceControl]]:
        controls: Dict[int, Dict[str, DeviceControl]] = {}
        for node_id in sorted(simulation_states.keys()):
            state = simulation_states[node_id]
            controls[node_id] = {}
            existing_controls = getattr(state, 'device_controls', {}) or {}
            if existing_controls:
                for device_name, device_control in existing_controls.items():
                    controls[node_id][device_name] = copy.deepcopy(device_control)
                continue

            device_states = getattr(state, 'device_states', {}) or {}
            for device_name in device_states.keys():
                controls[node_id][device_name] = DeviceControl(
                    device_name=str(device_name),
                    e_i_t=0.0,
                    n_i_t=1,
                )
        return controls

    def _build_default_boundary_params(self, simulation_states: Dict[int, Any]) -> Dict[int, Dict[str, BoundaryState]]:
        boundary_params: Dict[int, Dict[str, BoundaryState]] = {}
        boundary_node_ids = sorted(int(node_id) for node_id in simulation_states.keys())
        if not boundary_node_ids:
            return boundary_params

        first_boundary_override, last_boundary_override = self._extract_boundary_overrides()

        first_node_id = boundary_node_ids[0]
        first_boundary = self._build_boundary_state_for_node(
            node_id=first_node_id,
            state=simulation_states.get(first_node_id),
            boundary_type='upstream',
            override=first_boundary_override,
        )
        if first_boundary is not None:
            boundary_params[first_node_id] = {'upstream_boundary': first_boundary}

        last_node_id = boundary_node_ids[-1]
        last_boundary = self._build_boundary_state_for_node(
            node_id=last_node_id,
            state=simulation_states.get(last_node_id),
            boundary_type='downstream',
            override=last_boundary_override,
        )
        if last_boundary is not None:
            boundary_params.setdefault(last_node_id, {})['downstream_boundary'] = last_boundary

        return boundary_params

    def _extract_boundary_overrides(self) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        boundaries = (
            self.initial_states_source_data.get('initial_states', {})
            .get('boundaries', {})
            .get('overrides', [])
        )
        if not isinstance(boundaries, list) or not boundaries:
            return None, None

        first_item = boundaries[0] if isinstance(boundaries[0], dict) else None
        last_item = boundaries[-1] if isinstance(boundaries[-1], dict) else None
        return first_item, last_item

    def _build_boundary_state_for_node(
        self,
        node_id: int,
        state: Any,
        boundary_type: str,
        override: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundaryState]:
        station_state = getattr(state, 'station_state', None)
        if station_state is None:
            return None

        station_h_i_t = float(getattr(station_state, 'h_i_t', 0.0))
        station_hat_h_i_t = float(getattr(station_state, 'hat_h_i_t', 0.0))
        boundary_h_i_t = station_h_i_t
        if boundary_type == 'downstream' and boundary_h_i_t == 0.0 and station_hat_h_i_t != 0.0:
            boundary_h_i_t = station_hat_h_i_t

        boundary = BoundaryState(
            h_i_t=boundary_h_i_t,
            hat_h_i_t=station_hat_h_i_t,
            Inflow_i_t=float(getattr(station_state, 'inflow_i_t', 0.0)),
            qtot_i_t=float(getattr(station_state, 'qtot_i_t', 0.0)),
            boundary_id=str((override or {}).get('id') or node_id),
            boundary_type=boundary_type,
        )

        if not isinstance(override, dict):
            return boundary

        metric_code = str(override.get('metrics_code') or '').strip().lower()
        value = override.get('value')
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return boundary

        if boundary_type == 'upstream' and metric_code in {'water_flow', 'inflow'}:
            boundary.Inflow_i_t = numeric_value
            boundary.qtot_i_t = numeric_value
        elif boundary_type == 'downstream' and metric_code in {'water_level', 'water_depth'}:
            boundary.h_i_t = numeric_value
            boundary.hat_h_i_t = numeric_value

        return boundary

    def _apply_boundary_conditions(
        self,
        boundary_params: Dict[int, Dict[str, BoundaryState]],
        boundary_conditions: Dict[int, Dict[str, float]],
    ) -> None:
        if not boundary_conditions:
            return

        alias_map = {
            'upstream_water_level': 'h_i_t',
            'downstream_water_level': 'h_i_t',
            'water_level': 'h_i_t',
            'inflow': 'Inflow_i_t',
            'inflow_i_t': 'Inflow_i_t',
            'water_flow': 'qtot_i_t',
            'flow': 'qtot_i_t',
        }

        for object_id, metric_values in boundary_conditions.items():
            if object_id not in boundary_params:
                current_state = self.simulation_states.get(object_id)
                if current_state is None:
                    continue
                node_boundary_params = self._build_default_boundary_params({object_id: current_state})
                if object_id not in node_boundary_params:
                    continue
                boundary_params[object_id] = node_boundary_params[object_id]

            for boundary_name in ('upstream_boundary', 'downstream_boundary'):
                boundary = boundary_params[object_id].get(boundary_name)
                if boundary is None:
                    continue
                for metric_code, value in metric_values.items():
                    target_attr = alias_map.get(metric_code, metric_code)
                    if not hasattr(boundary, target_attr) or value is None:
                        continue

                    numeric_value = float(value)
                    setattr(boundary, target_attr, numeric_value)

                    if (
                        boundary_name == 'downstream_boundary'
                        and target_attr == 'h_i_t'
                    ):
                        boundary.hat_h_i_t = numeric_value

    def _apply_control_conditions(
        self,
        controls: Dict[int, Dict[str, DeviceControl]],
        control_conditions: Dict[int, Dict[str, float]],
    ) -> None:
        if not control_conditions:
            return

        for object_id, metric_values in control_conditions.items():
            target_controls = self._resolve_target_device_controls(controls, object_id)
            if not target_controls:
                continue

            for device_control in target_controls:
                for metric_code, value in metric_values.items():
                    if value is None:
                        continue
                    if metric_code in {'gate_opening', 'opening', 'e_i_t'}:
                        device_control.e_i_t = float(value)
                    elif metric_code in {'unit_count', 'n_i_t'}:
                        device_control.n_i_t = int(value)
                    elif metric_code in {'target_flow'}:
                        device_control.target_flow = float(value)
                    elif metric_code in {'emergency_shutdown', 'maintenance_shutdown'} and float(value) > 0:
                        device_control.e_i_t = 0.0
                        device_control.target_flow = 0.0

    def _resolve_target_device_controls(
        self,
        controls: Dict[int, Dict[str, DeviceControl]],
        object_id: int,
    ) -> list[DeviceControl]:
        object_controls = controls.get(object_id)
        if object_controls:
            return list(object_controls.values())

        object_name = self._resolve_topology_object_name(object_id)
        if not object_name:
            return []

        matched_controls: list[DeviceControl] = []
        matched_node_ids: list[int] = []
        for node_id, device_controls in controls.items():
            device_control = device_controls.get(object_name)
            if device_control is not None:
                matched_controls.append(device_control)
                matched_node_ids.append(node_id)

        if matched_controls:
            if len(matched_controls) > 1:
                logger.warning(
                    "Multiple control targets resolved by device name: object_id=%s, object_name=%s, node_ids=%s",
                    object_id,
                    object_name,
                    matched_node_ids,
                )
            logger.info(
                "Resolved control target by device name: object_id=%s, object_name=%s, matches=%s, node_ids=%s",
                object_id,
                object_name,
                len(matched_controls),
                matched_node_ids,
            )
        return matched_controls

    def _resolve_topology_object_name(self, object_id: int) -> Optional[str]:
        if not self.topology:
            return None

        for top_obj in getattr(self.topology, 'top_objects', []) or []:
            matched_name = self._match_object_name(top_obj, object_id)
            if matched_name:
                return matched_name
            for child in getattr(top_obj, 'children', []) or []:
                matched_name = self._match_object_name(child, object_id)
                if matched_name:
                    return matched_name
        return None

    @staticmethod
    def _match_object_name(obj: Any, object_id: int) -> Optional[str]:
        candidates = [getattr(obj, 'object_id', None), getattr(obj, 'id', None)]
        for candidate in candidates:
            try:
                if int(candidate) == object_id:
                    return str(getattr(obj, 'object_name', getattr(obj, 'name', '')))
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _iter_initial_state_items(initial_states_data: Dict[str, Any]) -> list[Dict[str, Any]]:
        result: list[Dict[str, Any]] = []
        for category_config in (initial_states_data.get('initial_states') or {}).values():
            if not isinstance(category_config, dict):
                continue
            overrides = category_config.get('overrides')
            if isinstance(overrides, dict):
                for items in overrides.values():
                    if isinstance(items, list):
                        result.extend(item for item in items if isinstance(item, dict))
            elif isinstance(overrides, list):
                result.extend(item for item in overrides if isinstance(item, dict))
        return result

    @staticmethod
    def _update_state_value(initial_state: Dict[str, Any], key: str, value: Any) -> bool:
        if value is None:
            return False
        try:
            initial_state[key] = float(value)
        except (TypeError, ValueError):
            initial_state[key] = value
        return True

    def _apply_initial_states_overrides(
        self,
        idz_data: Dict[str, Any],
        initial_states_data: Dict[str, Any],
    ) -> int:
        objects = idz_data.get('objects')
        if not isinstance(objects, list):
            return 0

        object_map = {
            int(obj['id']): obj for obj in objects
            if isinstance(obj, dict) and obj.get('id') is not None
        }
        ordered_objects = [obj for obj in objects if isinstance(obj, dict) and obj.get('id') is not None]
        child_map: Dict[int, Dict[str, Any]] = {}
        cross_section_parent_map: Dict[int, tuple[Dict[str, Any], int]] = {}
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            for child in obj.get('device_children', []) or []:
                if isinstance(child, dict) and child.get('id') is not None:
                    child_map[int(child['id'])] = child
            for index, cross_section in enumerate(obj.get('cross_section_children', []) or []):
                if isinstance(cross_section, dict) and cross_section.get('id') is not None:
                    cross_section_parent_map[int(cross_section['id'])] = (obj, index)

        applied = 0
        for item in self._iter_initial_state_items(initial_states_data):
            object_id = item.get('id')
            metric_code = str(item.get('metrics_code') or '').strip()
            value = item.get('value')
            if object_id is None or not metric_code:
                continue

            try:
                object_id = int(object_id)
            except (TypeError, ValueError):
                continue

            target_object = object_map.get(object_id)
            target_child = child_map.get(object_id)
            cross_section_parent = cross_section_parent_map.get(object_id)

            if target_child is not None:
                initial_state = target_child.setdefault('initial_state', {})
                if metric_code == 'gate_opening':
                    applied += int(self._update_state_value(initial_state, 'opening', value))
                elif metric_code == 'water_flow':
                    applied += int(self._update_state_value(initial_state, 'outflow', value))
                elif metric_code == 'water_level':
                    applied += int(self._update_state_value(initial_state, 'water_level', value))
                continue

            if cross_section_parent is not None:
                parent_object, cross_section_index = cross_section_parent
                initial_state = parent_object.setdefault('initial_state', {})

                if metric_code in {'water_level', 'water_depth'}:
                    target_key = 'water_level' if cross_section_index == 0 else 'water_level_back'
                    applied += int(self._update_state_value(initial_state, target_key, value))
                elif metric_code == 'water_flow':
                    target_key = 'inflow' if cross_section_index == 0 else 'outflow'
                    applied += int(self._update_state_value(initial_state, target_key, value))
                continue

            if target_object is None:
                continue

            initial_state = target_object.setdefault('initial_state', {})
            target_type = str(target_object.get('type') or '')

            if metric_code == 'water_flow':
                target_key = 'outflow' if target_type in {'DisturbanceNode', 'GateStation'} else 'water_flow'
                applied += int(self._update_state_value(initial_state, target_key, value))
            elif metric_code in {'water_level', 'water_depth'}:
                applied += int(self._update_state_value(initial_state, 'water_level', value))
            elif metric_code == 'inflow':
                applied += int(self._update_state_value(initial_state, 'inflow', value))
            elif metric_code == 'water_level_back':
                applied += int(self._update_state_value(initial_state, 'water_level_back', value))

        applied += self._apply_boundary_fallbacks(initial_states_data, ordered_objects, cross_section_parent_map)
        return applied

    def _apply_boundary_fallbacks(
        self,
        initial_states_data: Dict[str, Any],
        ordered_objects: list[Dict[str, Any]],
        cross_section_parent_map: Dict[int, tuple[Dict[str, Any], int]],
    ) -> int:
        if not ordered_objects:
            return 0

        boundaries = (
            initial_states_data.get('initial_states', {})
            .get('boundaries', {})
            .get('overrides', [])
        )
        if not isinstance(boundaries, list) or not boundaries:
            return 0

        first_object = ordered_objects[0]
        last_object = ordered_objects[-1]
        applied = 0

        for index, item in enumerate(boundaries):
            if not isinstance(item, dict):
                continue

            object_id = item.get('id')
            try:
                if object_id is not None and int(object_id) in cross_section_parent_map:
                    continue
            except (TypeError, ValueError):
                pass

            metric_code = str(item.get('metrics_code') or '').strip()
            value = item.get('value')
            target_object = first_object if index == 0 else last_object
            initial_state = target_object.setdefault('initial_state', {})

            if metric_code == 'water_flow':
                target_key = 'inflow' if index == 0 else 'outflow'
                applied += int(self._update_state_value(initial_state, target_key, value))
            elif metric_code in {'water_level', 'water_depth'}:
                target_key = 'water_level' if index == 0 else 'water_level_back'
                applied += int(self._update_state_value(initial_state, target_key, value))

        return applied

    def _download_idz_config(self, idz_config_url: str, initial_states_url: Optional[str] = None) -> Optional[str]:
        try:
            if not idz_config_url:
                logger.warning('idz_config_url is empty')
                return None

            content = fetch_url_text(idz_config_url, timeout=30)

            try:
                import yaml

                data = yaml.safe_load(content)
                applied_overrides = 0
                if initial_states_url and isinstance(data, dict):
                    initial_states_content = fetch_url_text(initial_states_url, timeout=30)
                    initial_states_data = yaml.safe_load(initial_states_content)
                    if isinstance(initial_states_data, dict):
                        self.initial_states_source_data = copy.deepcopy(initial_states_data)
                        applied_overrides = self._apply_initial_states_overrides(data, initial_states_data)
                        logger.info(
                            "Applied %s initial_state override(s) from %s",
                            applied_overrides,
                            initial_states_url,
                        )
                    else:
                        self.initial_states_source_data = {}
                if isinstance(data, dict) and 'objects' in data:
                    data['components'] = data.pop('objects')
                content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
            except ImportError:
                logger.warning('PyYAML not installed, skip IDZ YAML normalization')
            except Exception as exc:
                logger.warning(f'Failed to normalize IDZ YAML content: {exc}')

            script_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.abspath(os.path.join(script_dir, '..', '..', 'data'))
            os.makedirs(data_dir, exist_ok=True)

            output_path = os.path.join(data_dir, f'idz_config_{self.job_instance_id}.yml')
            with open(output_path, 'w', encoding='utf-8') as file_handle:
                file_handle.write(content)

            logger.info(f'IDZ config saved to: {output_path}')
            return output_path

        except ImportError as exc:
            logger.error(f'Missing dependency while downloading IDZ config: {exc}')
            return None
        except (HTTPError, URLError) as exc:
            logger.error(f'Failed to download IDZ config: {exc}')
            return None
        except Exception as exc:
            logger.error(f'Unexpected error while processing IDZ config: {exc}', exc_info=True)
            return None
