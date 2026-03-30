"""
Digital Twins forecast agent based on the runnable twins project.

This implementation keeps the existing realtime step-by-step simulation behavior and
adds rolling forecast capabilities that can be coordinated by the central coordinator.
"""

import copy
import logging
import os
import sys
import threading
import time
from typing import ClassVar, Dict, List, Optional, Tuple

# Add current directory to Python path for hydraulic_solver import
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from hydros_agent_sdk import (
    AgentErrorContext,
    ErrorCodes,
    HydroAgentFactory,
    MultiAgentCallback,
    SimCoordinationClient,
    load_env_config,
    setup_logging,
)
from hydros_agent_sdk.agents import TwinsSimulationAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import ObjectTimeSeries, SimulationContext
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics

from hydraulic_solver import HydraulicSolver

if __name__ == "__main__":
    examples_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(examples_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    try:
        env_config = load_env_config()
        hydros_cluster_id = env_config.get('hydros_cluster_id', 'default_cluster')
        hydros_node_id = env_config.get('hydros_node_id', 'LOCAL')
    except Exception:
        hydros_cluster_id = 'default_cluster'
        hydros_node_id = os.getenv("HYDROS_NODE_ID", "LOCAL")

    setup_logging(
        level=logging.INFO,
        hydros_cluster_id=hydros_cluster_id,
        hydros_node_id=hydros_node_id,
        console=True,
        log_file=os.path.join(log_dir, "hydros.log"),
        use_rolling=True,
    )

logger = logging.getLogger(__name__)


class MyTwinsSimulationAgent(TwinsSimulationAgent):
    """Digital twins simulation agent with rolling forecast support."""

    DEFAULT_BOUNDARY_METRICS: ClassVar[List[str]] = ['inflow', 'upstream_water_level']
    DEFAULT_SCENARIO_GROUPS: ClassVar[Dict[str, set[str]]] = {
        'weather_forecast': {'weather_forecast', 'weather_inflow', 'forecast_inflow'},
        'water_use_plan': {'water_use_plan', 'planned_demand', 'planned_outflow'},
        'emergency_maintenance': {'emergency_maintenance', 'maintenance_shutdown'},
    }
    DEFAULT_BOUNDARY_ALIASES: ClassVar[Dict[str, str]] = {
        'inflow': 'Inflow_i_t',
        'upstream_water_level': 'h_i_t',
        'weather_forecast': 'Inflow_i_t',
        'weather_inflow': 'Inflow_i_t',
        'forecast_inflow': 'Inflow_i_t',
        'water_use_plan': 'qtot_i_t',
        'planned_demand': 'qtot_i_t',
        'planned_outflow': 'qtot_i_t',
    }
    DEFAULT_CONTROL_ALIASES: ClassVar[Dict[str, str]] = {
        'gate_opening': 'e_i_t',
        'opening': 'e_i_t',
        'emergency_maintenance': 'maintenance_shutdown',
        'maintenance_shutdown': 'maintenance_shutdown',
    }

    def __init__(
        self,
        sim_coordination_client,
        agent_id: str,
        agent_code: str,
        agent_type: str,
        agent_name: str,
        context: SimulationContext,
        hydros_cluster_id: str,
        hydros_node_id: str,
        **kwargs,
    ):
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            **kwargs,
        )

        self._hydraulic_solver: Optional[HydraulicSolver] = None
        self._forecast_lock = threading.RLock()
        self._rolling_cycle = 10
        self._forecast_horizon = 0
        self._trigger_on_condition_update = True
        self._force_forecast_on_next_tick = False
        self._boundary_condition_metrics = set(self.DEFAULT_BOUNDARY_METRICS)
        self._scenario_metric_groups = {
            name: set(values) for name, values in self.DEFAULT_SCENARIO_GROUPS.items()
        }
        self._boundary_metric_aliases = dict(self.DEFAULT_BOUNDARY_ALIASES)
        self._control_metric_aliases = dict(self.DEFAULT_CONTROL_ALIASES)
        self._forecast_results_cache: Dict[int, Dict[int, Dict[str, float]]] = {}

        logger.info(f"MyTwinsSimulationAgent created: {agent_id}")

    def _initialize_twins_model(self):
        logger.info("Initializing digital twins model...")
        idz_config_url = self.properties.get_property('idz_config_url')

        with AgentErrorContext(
            ErrorCodes.MODEL_INITIALIZATION_FAILURE,
            agent_name=self.agent_code,
        ) as ctx:
            self._hydraulic_solver = HydraulicSolver.get_or_create(self.biz_scene_instance_id)

        if ctx.has_error:
            raise RuntimeError(f"Solver creation failed: {ctx.error_message}")

        if self._topology:
            with AgentErrorContext(
                ErrorCodes.MODEL_INITIALIZATION_FAILURE,
                agent_name=self.agent_code,
            ) as ctx:
                self._hydraulic_solver.initialize(self._topology, idz_config_url)

            if ctx.has_error:
                raise RuntimeError(f"Solver initialization failed: {ctx.error_message}")
        else:
            logger.warning("No topology available for hydraulic solver")

        self._load_forecast_config()
        logger.info(
            "Hydraulic solver parameters: time_step=%s, convergence_tolerance=%s, max_iterations=%s, rolling_cycle=%s, forecast_horizon=%s",
            self.properties.get_property('time_step', 60),
            self.properties.get_property('convergence_tolerance', 1e-6),
            self.properties.get_property('max_iterations', 100),
            self._rolling_cycle,
            self._forecast_horizon,
        )

    def on_tick_simulation(self, request):
        step = request.step
        logger.info(f"Executing digital twins simulation for step {step}")

        with self._forecast_lock:
            current_results = self._execute_realtime_step(step)
            if not current_results:
                return []

            if self._should_trigger_forecast(step):
                window_results = self._run_forecast_window(
                    start_step=step,
                    anchor_results=current_results,
                )
                metrics_list = self._convert_window_results_to_metrics(window_results)
                logger.info(
                    "Rolling forecast emitted for step %s covering %s future steps",
                    step,
                    self._forecast_horizon,
                )
            else:
                metrics_list = self._convert_results_to_metrics(current_results, step_index=step)

            logger.info(f"Generated {len(metrics_list)} metrics for step {step}")
            return metrics_list

    def _execute_realtime_step(self, step: int) -> Dict[int, Dict[str, float]]:
        if not self._hydraulic_solver:
            logger.error("Hydraulic solver not initialized")
            return {}

        with AgentErrorContext(
            ErrorCodes.SIMULATION_EXECUTION_FAILURE,
            agent_name=self.agent_code,
        ) as ctx:
            boundary_conditions, control_conditions = self._collect_step_inputs(step)
            results = self._hydraulic_solver.solve_step(
                step=step,
                boundary_conditions=boundary_conditions,
                control_conditions=control_conditions,
            )

        if ctx.has_error:
            logger.error(f"Hydraulic solver failed: {ctx.error_message}")
            return {}

        return results

    def _load_forecast_config(self) -> None:
        self._rolling_cycle = max(1, self._as_int(self.properties.get_property('rolling_cycle', 10), 10))
        self._forecast_horizon = max(0, self._as_int(self.properties.get_property('forecast_horizon', 0), 0))
        self._trigger_on_condition_update = self._as_bool(
            self.properties.get_property('trigger_forecast_on_condition_update', True),
            True,
        )

        boundary_metrics = self.properties.get_property(
            'boundary_condition_metrics',
            self.DEFAULT_BOUNDARY_METRICS,
        )
        self._boundary_condition_metrics = {str(item) for item in self._as_list(boundary_metrics)}

        configured_groups = self.properties.get_property('scenario_metric_groups', {})
        if isinstance(configured_groups, dict):
            merged_groups = {
                name: set(values) for name, values in self.DEFAULT_SCENARIO_GROUPS.items()
            }
            for group_name, metrics in configured_groups.items():
                merged_groups[str(group_name)] = {str(item) for item in self._as_list(metrics)}
            self._scenario_metric_groups = merged_groups

        configured_boundary_aliases = self.properties.get_property('boundary_metric_aliases', {})
        if isinstance(configured_boundary_aliases, dict):
            merged_boundary_aliases = dict(self.DEFAULT_BOUNDARY_ALIASES)
            merged_boundary_aliases.update({str(k): str(v) for k, v in configured_boundary_aliases.items()})
            self._boundary_metric_aliases = merged_boundary_aliases

        configured_control_aliases = self.properties.get_property('control_metric_aliases', {})
        if isinstance(configured_control_aliases, dict):
            merged_control_aliases = dict(self.DEFAULT_CONTROL_ALIASES)
            merged_control_aliases.update({str(k): str(v) for k, v in configured_control_aliases.items()})
            self._control_metric_aliases = merged_control_aliases

        logger.info(
            "Forecast config loaded: rolling_cycle=%s, forecast_horizon=%s, trigger_on_condition_update=%s",
            self._rolling_cycle,
            self._forecast_horizon,
            self._trigger_on_condition_update,
        )

    def _collect_step_inputs(
        self,
        step: int,
    ) -> Tuple[Dict[int, Dict[str, float]], Dict[int, Dict[str, float]]]:
        boundary_conditions: Dict[int, Dict[str, float]] = {}
        control_conditions: Dict[int, Dict[str, float]] = {}
        normalized_boundary_metrics = {item.lower() for item in self._boundary_condition_metrics}

        for time_series in self._time_series_cache.values():
            if time_series.object_id is None or not time_series.metrics_code:
                continue

            value = self._extract_time_series_value(time_series, step)
            if value is None:
                continue

            metrics_code = str(time_series.metrics_code)
            normalized_code = metrics_code.lower()
            object_id = int(time_series.object_id)

            boundary_target = self._boundary_metric_aliases.get(metrics_code)
            if boundary_target is None:
                boundary_target = self._boundary_metric_aliases.get(normalized_code)
            if boundary_target is None and normalized_code in normalized_boundary_metrics:
                boundary_target = metrics_code
            if boundary_target is not None:
                boundary_conditions.setdefault(object_id, {})[boundary_target] = float(value)

            control_target = self._control_metric_aliases.get(metrics_code)
            if control_target is None:
                control_target = self._control_metric_aliases.get(normalized_code)
            if control_target is not None:
                control_conditions.setdefault(object_id, {})[control_target] = float(value)

        return boundary_conditions, control_conditions

    def _run_forecast_window(
        self,
        start_step: int,
        anchor_results: Optional[Dict[int, Dict[str, float]]] = None,
    ) -> Dict[int, Dict[int, Dict[str, float]]]:
        if not self._hydraulic_solver:
            return {}

        if anchor_results is None:
            anchor_results = self._hydraulic_solver.get_current_results()

        window_results: Dict[int, Dict[int, Dict[str, float]]] = {
            start_step: copy.deepcopy(anchor_results)
        }

        if self._forecast_horizon <= 0:
            self._merge_forecast_results(window_results)
            return window_results

        snapshot = self._hydraulic_solver.snapshot()
        for target_step in range(start_step + 1, start_step + self._forecast_horizon + 1):
            boundary_conditions, control_conditions = self._collect_step_inputs(target_step)
            snapshot, step_results = self._hydraulic_solver.solve_step_from_snapshot(
                step=target_step,
                snapshot=snapshot,
                boundary_conditions=boundary_conditions,
                control_conditions=control_conditions,
            )
            window_results[target_step] = step_results

        self._merge_forecast_results(window_results)
        return window_results

    def _should_trigger_forecast(self, step: int) -> bool:
        if self._forecast_horizon <= 0:
            return False

        triggered_by_cycle = (step % self._rolling_cycle) == 0
        triggered_by_event = self._force_forecast_on_next_tick
        should_trigger = triggered_by_cycle or triggered_by_event

        if should_trigger:
            self._force_forecast_on_next_tick = False
        return should_trigger

    def _merge_forecast_results(self, window_results: Dict[int, Dict[int, Dict[str, float]]]) -> None:
        for step, results in window_results.items():
            self._forecast_results_cache[step] = copy.deepcopy(results)

    def _convert_window_results_to_metrics(
        self,
        window_results: Dict[int, Dict[int, Dict[str, float]]],
    ) -> List[MqttMetrics]:
        metrics_list: List[MqttMetrics] = []
        for step in sorted(window_results.keys()):
            metrics_list.extend(self._convert_results_to_metrics(window_results[step], step_index=step))
        return metrics_list

    def _convert_results_to_metrics(
        self,
        results: Dict[int, Dict[str, float]],
        step_index: int,
    ) -> List[MqttMetrics]:
        metrics_list: List[MqttMetrics] = []
        node_info, cross_section_info = self._build_topology_mappings()

        for node_id, values in results.items():
            if node_id not in node_info:
                continue

            node_type = node_info[node_id]['type']
            if node_type in ['DisturbanceNode']:
                self._send_disturbance_node_metrics(node_id, node_info[node_id], values, metrics_list, step_index)
            elif node_type in ['Pipe', 'GateStation']:
                self._send_pipe_gate_metrics(
                    node_id,
                    node_info[node_id],
                    cross_section_info,
                    values,
                    metrics_list,
                    step_index,
                )
            else:
                self._send_default_metrics(node_id, node_info[node_id], values, metrics_list, step_index)

        return metrics_list

    def _build_topology_mappings(self) -> Tuple[Dict[int, Dict[str, object]], Dict[int, Dict[str, object]]]:
        node_info: Dict[int, Dict[str, object]] = {}
        cross_section_info: Dict[int, Dict[str, object]] = {}

        if not self._topology:
            return node_info, cross_section_info

        for top_obj in self._topology.top_objects:
            node_info[top_obj.object_id] = {
                'type': top_obj.object_type,
                'name': top_obj.object_name,
                'cross_section_children': [],
            }

            cross_section_ids: List[int] = []
            for child in top_obj.children:
                node_info[child.object_id] = {
                    'type': child.object_type,
                    'name': child.object_name,
                    'cross_section_children': [],
                }
                if child.object_type in ['CrossSection', 'CrossSectionNode']:
                    cross_section_ids.append(child.object_id)
                    cross_section_info[child.object_id] = {
                        'name': child.object_name,
                        'parent_id': top_obj.object_id,
                        'parent_type': top_obj.object_type,
                    }

            if top_obj.object_type in ['Pipe', 'GateStation']:
                node_info[top_obj.object_id]['cross_section_children'] = cross_section_ids

        return node_info, cross_section_info

    def _send_disturbance_node_metrics(
        self,
        node_id: int,
        node_info: Dict[str, object],
        values: Dict[str, float],
        metrics_list: List[MqttMetrics],
        step_index: int,
    ) -> None:
        node_name = str(node_info['name'])

        if 'water_level' in values or 'h_i_t' in values:
            water_level = values.get('water_level', values.get('h_i_t', 0.0))
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=node_id,
                object_name=node_name,
                step_index=step_index,
                metrics_code='water_level',
                value=water_level,
            ))

        if 'water_flow' in values or 'qtot_i_t' in values or 'q_out' in values:
            water_flow = values.get('water_flow', values.get('qtot_i_t', values.get('q_out', 0.0)))
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=node_id,
                object_name=node_name,
                step_index=step_index,
                metrics_code='water_flow',
                value=water_flow,
            ))

    def _send_pipe_gate_metrics(
        self,
        node_id: int,
        node_info: Dict[str, object],
        cross_section_info: Dict[int, Dict[str, object]],
        values: Dict[str, float],
        metrics_list: List[MqttMetrics],
        step_index: int,
    ) -> None:
        cross_section_ids = list(node_info.get('cross_section_children', []))
        if not cross_section_ids:
            self._send_default_metrics(node_id, node_info, values, metrics_list, step_index)
            return

        node_water_level = values.get('water_level', values.get('h_i_t', 0.0))
        q_in = values.get('q_in', values.get('water_flow', 0.0))
        q_out = values.get('q_out', values.get('water_flow', 0.0))

        for index, cs_id in enumerate(cross_section_ids):
            cs_name = str(cross_section_info.get(cs_id, {}).get('name', f'CS_{cs_id}'))
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=cs_id,
                object_name=cs_name,
                step_index=step_index,
                metrics_code='water_level',
                value=node_water_level,
            ))
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=cs_id,
                object_name=cs_name,
                step_index=step_index,
                metrics_code='water_flow',
                value=q_in if index == 0 else q_out,
            ))

    def _send_default_metrics(
        self,
        node_id: int,
        node_info: Dict[str, object],
        values: Dict[str, float],
        metrics_list: List[MqttMetrics],
        step_index: int,
    ) -> None:
        node_name = str(node_info['name'])
        for metrics_code, value in values.items():
            metrics_list.append(create_mock_metrics(
                source_id=self.agent_code,
                job_instance_id=self.biz_scene_instance_id,
                object_id=node_id,
                object_name=node_name,
                step_index=step_index,
                metrics_code=metrics_code,
                value=value,
            ))

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]):
        logger.info(f"Updating digital twins with {len(time_series_list)} boundary conditions")
        relevant_update = False

        for time_series in time_series_list:
            try:
                logger.info(
                    "Boundary condition update: object=%s, metrics=%s, values=%s",
                    time_series.object_name,
                    time_series.metrics_code,
                    len(time_series.time_series),
                )
                if self._simulation_state and time_series.object_id:
                    state_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._simulation_state[state_key] = time_series

                if self._is_forecast_related_metric(time_series.metrics_code):
                    relevant_update = True
            except Exception as exc:
                logger.error(
                    f"Error updating boundary condition for {time_series.object_name}: {exc}",
                    exc_info=True,
                )

        if not relevant_update or not self._trigger_on_condition_update or self._forecast_horizon <= 0:
            return

        self._force_forecast_on_next_tick = True
        if not self._hydraulic_solver:
            return

        try:
            with self._forecast_lock:
                current_results = self._hydraulic_solver.get_current_results()
                window_results = self._run_forecast_window(
                    start_step=self._current_step,
                    anchor_results=current_results,
                )
                metrics_list = self._convert_window_results_to_metrics(window_results)
                if metrics_list:
                    self.send_metrics_batch(metrics_list)
                    logger.info(
                        "Triggered immediate rolling forecast after condition update, step=%s, metrics=%s",
                        self._current_step,
                        len(metrics_list),
                    )
                    self._force_forecast_on_next_tick = False
        except Exception as exc:
            logger.error(f"Immediate forecast after condition update failed: {exc}", exc_info=True)

    def _is_forecast_related_metric(self, metrics_code: Optional[str]) -> bool:
        if not metrics_code:
            return False
        normalized = str(metrics_code).lower()
        if normalized in {key.lower() for key in self._boundary_metric_aliases.keys()}:
            return True
        if normalized in {key.lower() for key in self._control_metric_aliases.keys()}:
            return True
        for group_metrics in self._scenario_metric_groups.values():
            if normalized in {item.lower() for item in group_metrics}:
                return True
        return False

    def _extract_time_series_value(self, time_series: ObjectTimeSeries, step: int) -> Optional[float]:
        if not time_series.time_series:
            return None
        for ts_value in time_series.time_series:
            if ts_value.step == step:
                return ts_value.value
        return None

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        logger.info('=' * 70)
        logger.info(f'TERMINATING DIGITAL TWINS SIMULATION AGENT: {self.biz_scene_instance_id}')
        logger.info('=' * 70)

        if self._hydraulic_solver is not None:
            try:
                HydraulicSolver.remove(self.biz_scene_instance_id)
            finally:
                self._hydraulic_solver = None

        self._forecast_results_cache.clear()
        return super().on_terminate(request)

    def get_metrics_topic(self) -> str:
        return f"{self.hydros_cluster_id}/hydros/simulation/jobs/{self.biz_scene_instance_id}/realtime/objects"
        # return f"/hydros/data/edges/{self.hydros_cluster_id}/{self.biz_scene_instance_id}"

    @staticmethod
    def _as_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {'1', 'true', 'yes', 'on'}:
                return True
            if lowered in {'0', 'false', 'no', 'off'}:
                return False
        if value is None:
            return default
        return bool(value)

    @staticmethod
    def _as_list(value) -> List[object]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    env_file = os.path.join(script_dir, 'env.properties')
    env_config = load_env_config(env_file)

    broker_url = env_config['mqtt_broker_url']
    broker_port = int(env_config['mqtt_broker_port'])
    topic = env_config['mqtt_topic']
    mqtt_username = env_config.get('mqtt_username')
    mqtt_password = env_config.get('mqtt_password')

    config_file = os.path.join(script_dir, 'agent.properties')

    agent_factory = HydroAgentFactory(
        agent_class=MyTwinsSimulationAgent,
        config_file=config_file,
        env_config=env_config,
    )

    callback = MultiAgentCallback(node_id=os.getenv('HYDROS_NODE_ID', 'LOCAL'))
    callback.register_agent_factory('TWINS_SIMULATION_AGENT', agent_factory)

    sim_coordination_client = SimCoordinationClient(
        broker_url=broker_url,
        broker_port=broker_port,
        topic=topic,
        sim_coordination_callback=callback,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
    )

    callback.set_client(sim_coordination_client)

    try:
        logger.info('=' * 70)
        logger.info('Starting Digital Twins Simulation Agent Service')
        logger.info('=' * 70)
        logger.info(f'Environment config: {env_file}')
        logger.info(f'Agent config: {config_file}')
        logger.info(f'MQTT Broker: {broker_url}:{broker_port}')
        logger.info(f'MQTT Topic: {topic}')
        logger.info('=' * 70)

        sim_coordination_client.start()

        logger.info('Service started successfully')
        logger.info('Ready to create twins agent instances for incoming tasks')

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info('Stopping service...')
        sim_coordination_client.stop()
        logger.info('Service stopped')
    except Exception as exc:
        logger.error(f'Error: {exc}', exc_info=True)
        sim_coordination_client.stop()


if __name__ == '__main__':
    main()

