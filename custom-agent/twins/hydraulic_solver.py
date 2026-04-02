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
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

# Add current directory to path for local imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in __import__('sys').path:
    __import__('sys').path.insert(0, _SCRIPT_DIR)

# Add idz directory to path for corelib import
_idz_dir = os.path.join(os.path.dirname(__file__), '..', 'idz')
if _idz_dir not in __import__('sys').path:
    __import__('sys').path.insert(0, _idz_dir)

from corelib.core.hydro_simulator import HydroSimulator
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
        self.simulation_states: Dict[int, Any] = {}
        self.controls: Dict[int, Dict[str, DeviceControl]] = {}
        self.boundary_params: Dict[int, Dict[str, BoundaryState]] = {}
        self.initial_states: Dict[int, Any] = {}
        self.state: Dict[int, Dict[str, float]] = {}
        logger.info(f"Hydraulic solver initialized for job: {job_instance_id}")

    def initialize(self, topology, idz_config_url: str) -> None:
        logger.info("Initializing hydraulic solver with topology")

        idz_config_file = self._download_idz_config(idz_config_url)
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
            for device_name in getattr(state, 'device_states', {}).keys():
                controls[node_id][device_name] = DeviceControl(
                    device_name=device_name,
                    e_i_t=65.0,
                    n_i_t=1,
                )
        return controls

    def _build_default_boundary_params(self, simulation_states: Dict[int, Any]) -> Dict[int, Dict[str, BoundaryState]]:
        boundary_params: Dict[int, Dict[str, BoundaryState]] = {}
        for node_id, state in simulation_states.items():
            station_state = getattr(state, 'station_state', None)
            if station_state is None:
                continue

            base_boundary = BoundaryState(
                h_i_t=float(getattr(station_state, 'h_i_t', 0.0)),
                hat_h_i_t=float(getattr(station_state, 'hat_h_i_t', 0.0)),
                Inflow_i_t=float(getattr(station_state, 'inflow_i_t', 0.0)),
                qtot_i_t=float(getattr(station_state, 'qtot_i_t', 0.0)),
                boundary_id=str(node_id),
            )
            boundary_params[node_id] = {
                'upstream_boundary': copy.deepcopy(base_boundary),
                'downstream_boundary': copy.deepcopy(base_boundary),
            }
            boundary_params[node_id]['upstream_boundary'].boundary_type = 'upstream'
            boundary_params[node_id]['downstream_boundary'].boundary_type = 'downstream'
        return boundary_params

    def _apply_boundary_conditions(
        self,
        boundary_params: Dict[int, Dict[str, BoundaryState]],
        boundary_conditions: Dict[int, Dict[str, float]],
    ) -> None:
        if not boundary_conditions:
            return

        alias_map = {
            'upstream_water_level': 'h_i_t',
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
                boundary_params[object_id] = self._build_default_boundary_params({object_id: current_state})[object_id]

            for boundary_name in ('upstream_boundary', 'downstream_boundary'):
                boundary = boundary_params[object_id].get(boundary_name)
                if boundary is None:
                    continue
                for metric_code, value in metric_values.items():
                    target_attr = alias_map.get(metric_code, metric_code)
                    if hasattr(boundary, target_attr) and value is not None:
                        setattr(boundary, target_attr, float(value))

    def _apply_control_conditions(
        self,
        controls: Dict[int, Dict[str, DeviceControl]],
        control_conditions: Dict[int, Dict[str, float]],
    ) -> None:
        if not control_conditions:
            return

        for object_id, metric_values in control_conditions.items():
            if object_id not in controls:
                continue

            for device_control in controls[object_id].values():
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

    def _download_idz_config(self, idz_config_url: str) -> Optional[str]:
        try:
            if not idz_config_url:
                logger.warning('idz_config_url is empty')
                return None

            parsed = urlparse(idz_config_url)
            encoded_path = quote(parsed.path, safe='/:@!$&\'()*+,;=')
            encoded_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                encoded_path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            ))

            request = Request(encoded_url)
            request.add_header('User-Agent', 'Hydros-Agent-SDK/0.1.3')

            with urlopen(request, timeout=30) as response:
                content = response.read().decode('utf-8')

            try:
                import yaml

                data = yaml.safe_load(content)
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
