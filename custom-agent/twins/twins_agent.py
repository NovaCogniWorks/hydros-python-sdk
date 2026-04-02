"""
Digital Twins forecast agent based on the runnable twins project.

This implementation keeps the existing realtime step-by-step simulation behavior and
adds rolling forecast capabilities that can be coordinated by the central coordinator.
"""

import copy
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Any, ClassVar, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

# 将当前目录加入 Python 路径，便于导入本地 hydraulic_solver
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
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
    TimeSeriesCalculationRequest,
    TimeSeriesCalculationResponse,
)
from hydros_agent_sdk.protocol.models import (
    CommandStatus,
    ObjectTimeSeries,
    SimulationContext,
    TimeSeriesValue,
)
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
    """支持滚动预测的数字孪生仿真智能体。"""

    DEFAULT_BOUNDARY_METRICS: ClassVar[List[str]] = [
        'inflow',
        'upstream_water_level',
        'water_flow',
        'water_level',
    ]
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
        self._boundary_condition_metrics = set(self.DEFAULT_BOUNDARY_METRICS)
        self._scenario_metric_groups = {
            name: set(values) for name, values in self.DEFAULT_SCENARIO_GROUPS.items()
        }
        self._boundary_metric_aliases = dict(self.DEFAULT_BOUNDARY_ALIASES)
        self._control_metric_aliases = dict(self.DEFAULT_CONTROL_ALIASES)
        self._biz_scene_configuration: Dict[str, Any] = {}
        self._forecast_results_cache: Dict[int, Dict[int, Dict[str, float]]] = {}
        self._forecast_anchor_step = 0
        self._last_forecast_start_step: Optional[int] = None
        self._last_forecast_end_step: int = 0
        self._last_event_forecast_step: Optional[int] = None
        self._weather_forecast_inflow_cache: Dict[str, float] = {}
        self._weather_forecast_target_nodes: set[int] = set()
        self._weather_forecast_source_series_keys: set[str] = set()
        self._weather_forecast_steps_by_node: Dict[int, List[int]] = {}
        self._weather_forecast_logged_hits: set[str] = set()
        self._weather_forecast_logged_injections: set[str] = set()

        logger.info(f"MyTwinsSimulationAgent created: {agent_id}")

    def load_agent_configuration(self, request) -> None:
        super().load_agent_configuration(request)
        self._load_biz_scene_configuration(request)

    def _load_biz_scene_configuration(self, request=None) -> None:
        biz_scene_configuration_url = self.properties.get_property('biz_scene_configuration_url')
        if not biz_scene_configuration_url and request is not None:
            biz_scene_configuration_url = getattr(request, 'biz_scene_configuration_url', None)
            if biz_scene_configuration_url:
                self.properties['biz_scene_configuration_url'] = biz_scene_configuration_url
        if not biz_scene_configuration_url:
            logger.info("No biz_scene_configuration_url configured, skipping scene configuration load")
            return

        from hydros_agent_sdk.utils.yaml_loader import YamlLoader

        scene_config = YamlLoader.from_url(str(biz_scene_configuration_url))
        if not isinstance(scene_config, dict):
            raise ValueError(
                f"biz scene configuration must be a dictionary, got {type(scene_config).__name__}"
            )

        self._biz_scene_configuration = copy.deepcopy(scene_config)

        # 保留原始场景 YAML，且同时把顶层配置展开到现有 properties 查询链路中。
        self.properties['biz_scene_configuration'] = copy.deepcopy(scene_config)
        self.properties.update(scene_config)

        sim_agent_properties = scene_config.get('sim_agent_properties')
        if isinstance(sim_agent_properties, dict):
            for key, value in sim_agent_properties.items():
                self.properties.setdefault(str(key), value)
            self._apply_sim_agent_property_aliases(sim_agent_properties)

        logger.info(
            "Loaded biz scene configuration from %s with %s top-level keys",
            biz_scene_configuration_url,
            len(scene_config),
        )

    def _apply_sim_agent_property_aliases(self, sim_agent_properties: Dict[str, Any]) -> None:
        property_aliases = {
            'sim_step_size': 'time_step',
            'roll_steps': 'rolling_cycle',
            'output_future_steps': 'forecast_horizon',
        }

        for source_key, target_key in property_aliases.items():
            if source_key not in sim_agent_properties:
                continue
            existing_value = self.properties.get_property(target_key)
            if existing_value not in (None, '', 0, '0', False):
                continue
            self.properties[target_key] = sim_agent_properties[source_key]

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

            forecast_plan = self._build_periodic_forecast_plan(step)
            if not forecast_plan:
                logger.info("当前步仅执行实时仿真，不发送结果：step=%s", step)
                return []

            metrics_list: List[MqttMetrics] = []
            if bool(forecast_plan.get('include_realtime_metrics', False)):
                metrics_list.extend(self._convert_results_to_metrics(current_results, step_index=step))

            window_results = self._run_forecast_window(
                start_step=forecast_plan['start_step'],
                end_step=int(forecast_plan['window_end_step']),
                result_window_from_step=int(forecast_plan['result_window_from_step']),
                anchor_results=current_results,
            )
            forecast_metrics: List[MqttMetrics] = []
            if bool(forecast_plan.get('emit_metrics', True)):
                actual_send_from_step = int(forecast_plan['send_from_step'])
                actual_send_to_step = int(forecast_plan['send_to_step'])
                forecast_metrics = self._convert_window_results_to_metrics(
                    window_results,
                    send_from_step=actual_send_from_step,
                    send_to_step=actual_send_to_step,
                )
                metrics_list.extend(forecast_metrics)
            else:
                actual_send_from_step = int(forecast_plan['send_from_step'])
                actual_send_to_step = int(forecast_plan['send_to_step'])
            self._record_forecast_plan_execution(forecast_plan)
            logger.info(
                "周期滚动发送：当前步=%s，预测起始步=%s，实际发送步范围=[%s,%s]，预测步长=%s，是否附带实时结果=%s，是否发送预测结果=%s，预测记录数=%s",
                step,
                forecast_plan['start_step'],
                actual_send_from_step,
                actual_send_to_step,
                self._forecast_horizon,
                bool(forecast_plan.get('include_realtime_metrics', False)),
                bool(forecast_plan.get('emit_metrics', True)),
                len(forecast_metrics),
            )

            logger.info("周期滚动发送完成：当前步=%s，发送记录总数=%s", step, len(metrics_list))
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

            raw_cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
            if raw_cache_key in self._weather_forecast_source_series_keys:
                # 天气预报工况会先做“断面/渠道对象 -> 算法节点”的映射，
                # 原始 object_id 不能直接送入求解器，因此在常规注入链路中跳过。
                continue

            value = self._extract_time_series_value(time_series, step)
            if value is None:
                continue

            metrics_code = str(time_series.metrics_code)
            normalized_code = metrics_code.lower()
            object_id = int(time_series.object_id)

            boundary_target = self._resolve_boundary_metric_target(
                time_series=time_series,
                metrics_code=metrics_code,
                normalized_code=normalized_code,
                normalized_boundary_metrics=normalized_boundary_metrics,
            )
            if boundary_target is not None:
                boundary_conditions.setdefault(object_id, {})[boundary_target] = float(value)

            control_target = self._control_metric_aliases.get(metrics_code)
            if control_target is None:
                control_target = self._control_metric_aliases.get(normalized_code)
            if control_target is not None:
                control_conditions.setdefault(object_id, {})[control_target] = float(value)

        self._merge_weather_forecast_inputs(step, boundary_conditions)
        return boundary_conditions, control_conditions

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        """
        处理时间序列更新请求，并在天气预报事件到达时提前构建步级入流缓存。
        """
        event = getattr(request, 'time_series_data_changed_event', None)
        time_series_list = self._resolve_weather_forecast_time_series_list(event)
        source_type = getattr(event, 'hydro_event_source_type', None)

        self._sync_weather_forecast_series_marks(time_series_list, source_type)
        if self._is_weather_forecast_source(source_type):
            self._reset_weather_forecast_cache()
            self._cache_weather_forecast_time_series(time_series_list)

        return super().on_time_series_data_update(request)

    def _run_forecast_window(
        self,
        start_step: int,
        end_step: Optional[int] = None,
        result_window_from_step: Optional[int] = None,
        anchor_results: Optional[Dict[int, Dict[str, float]]] = None,
    ) -> Dict[int, Dict[int, Dict[str, float]]]:
        if not self._hydraulic_solver:
            return {}

        if anchor_results is None:
            anchor_results = self._hydraulic_solver.get_current_results()

        window_results: Dict[int, Dict[int, Dict[str, float]]] = {}

        if end_step is None:
            end_step = self._calculate_forecast_end_step(start_step)
        if result_window_from_step is None:
            result_window_from_step = start_step

        if start_step >= result_window_from_step:
            window_results[start_step] = copy.deepcopy(anchor_results)

        if end_step <= start_step:
            self._merge_forecast_results(window_results)
            return window_results

        snapshot = self._hydraulic_solver.snapshot()
        for target_step in range(start_step + 1, end_step + 1):
            boundary_conditions, control_conditions = self._collect_step_inputs(target_step)
            snapshot, step_results = self._hydraulic_solver.solve_step_from_snapshot(
                step=target_step,
                snapshot=snapshot,
                boundary_conditions=boundary_conditions,
                control_conditions=control_conditions,
            )
            if target_step >= result_window_from_step:
                window_results[target_step] = step_results

        self._merge_forecast_results(window_results)
        return window_results

    def _should_trigger_forecast(self, step: int) -> bool:
        if self._forecast_horizon <= 0:
            return False
        if step == 1:
            return True
        anchor_step = max(0, self._forecast_anchor_step)
        if step < anchor_step:
            return False
        return ((step - anchor_step) % self._rolling_cycle) == 0

    def _build_periodic_forecast_plan(self, step: int) -> Optional[Dict[str, int | str]]:
        if not self._should_trigger_forecast(step):
            return None

        start_step = step

        if step == 1:
            result_window_from_step = start_step
            send_from_step = start_step
            send_to_step = self._calculate_forecast_end_step(start_step)
            include_realtime_metrics = False
            emit_metrics = True
        else:
            send_from_step = max(step + 1, self._last_forecast_end_step + 1)
            send_to_step = self._last_forecast_end_step + self._rolling_cycle
            result_window_from_step = send_from_step
            include_realtime_metrics = False
            emit_metrics = True

        if send_from_step > send_to_step:
            logger.info(
                "跳过周期滚动预测发送：step=%s，anchor=%s，last_sent_end=%s，send_range为空",
                step,
                self._forecast_anchor_step,
                self._last_forecast_end_step,
            )
            return None

        return {
            'trigger_type': 'periodic',
            'start_step': start_step,
            'window_end_step': send_to_step,
            'result_window_from_step': result_window_from_step,
            'send_from_step': send_from_step,
            'send_to_step': send_to_step,
            'include_realtime_metrics': include_realtime_metrics,
            'emit_metrics': emit_metrics,
        }

    def _build_event_forecast_plan(self, step: int) -> Optional[Dict[str, int | str]]:
        if self._forecast_horizon <= 0:
            return None

        start_step = max(0, step)
        return {
            'trigger_type': 'event',
            'start_step': start_step,
            'window_end_step': self._calculate_forecast_end_step(start_step),
            'result_window_from_step': start_step,
            'send_from_step': start_step,
            'send_to_step': self._calculate_forecast_end_step(start_step),
        }

    def _calculate_forecast_end_step(self, start_step: int) -> int:
        return start_step + max(self._forecast_horizon - 1, 0)

    def _calculate_periodic_forecast_end_step(self, start_step: int) -> int:
        if start_step == 1:
            return self._calculate_forecast_end_step(start_step)
        return start_step + max(self._forecast_horizon, 0)

    def _record_forecast_plan_execution(self, forecast_plan: Dict[str, int | str]) -> None:
        start_step = int(forecast_plan['start_step'])
        send_to_step = int(forecast_plan['send_to_step'])
        trigger_type = str(forecast_plan['trigger_type'])

        self._last_forecast_start_step = start_step
        self._last_forecast_end_step = max(self._last_forecast_end_step, send_to_step)
        if trigger_type == 'event':
            self._forecast_anchor_step = start_step
            self._last_event_forecast_step = start_step

    def _merge_forecast_results(self, window_results: Dict[int, Dict[int, Dict[str, float]]]) -> None:
        for step, results in window_results.items():
            self._forecast_results_cache[step] = copy.deepcopy(results)

    def _convert_window_results_to_metrics(
        self,
        window_results: Dict[int, Dict[int, Dict[str, float]]],
        send_from_step: Optional[int] = None,
        send_to_step: Optional[int] = None,
    ) -> List[MqttMetrics]:
        metrics_list: List[MqttMetrics] = []
        for step in sorted(window_results.keys()):
            if send_from_step is not None and step < send_from_step:
                continue
            if send_to_step is not None and step > send_to_step:
                continue
            metrics_list.extend(self._convert_results_to_metrics(window_results[step], step_index=step))
        metrics_list.sort(
            key=lambda metric: (
                getattr(metric, 'step_index', -1),
                getattr(metric, 'object_id', -1),
                str(getattr(metric, 'metrics_code', '')),
            )
        )
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

    def _create_metrics(
        self,
        object_id: int,
        object_name: str,
        object_type: str,
        step_index: int,
        metrics_code: str,
        value: float,
    ) -> MqttMetrics:
        timestamp_ms = self._calculate_source_timestamp_ms(step_index)
        tenant_id = None
        if self.context and getattr(self.context, 'tenant', None):
            tenant_id = getattr(self.context.tenant, 'tenant_id', None)

        return create_mock_metrics(
            source_id=self.agent_code,
            source_agent_type=self.agent_type or 'TWINS_SIMULATION_AGENT',
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            job_instance_id=self.biz_scene_instance_id,
            biz_scenario_instance_id=self.biz_scene_instance_id,
            object_id=object_id,
            object_name=object_name,
            object_type=object_type,
            step_index=step_index,
            data_index=step_index,
            source_type='MQTT',
            source_time=self._format_source_time(timestamp_ms),
            metrics_code=metrics_code,
            value=value,
            timestamp_ms=timestamp_ms,
        )

    def _calculate_source_timestamp_ms(self, data_index: int) -> int:
        biz_start_time = self.properties.get_property('biz_start_time')
        sim_step_size = self._as_int(self.properties.get_property('sim_step_size', 60), 60)

        if not biz_start_time:
            return int(time.time() * 1000)

        try:
            start_time = datetime.strptime(str(biz_start_time), '%Y/%m/%d %H:%M:%S')
            source_time = start_time + timedelta(seconds=max(0, data_index) * max(1, sim_step_size))
            return int(source_time.timestamp() * 1000)
        except Exception as exc:
            logger.warning(
                "Failed to calculate source timestamp from biz_start_time=%s, sim_step_size=%s: %s",
                biz_start_time,
                sim_step_size,
                exc,
            )
            return int(time.time() * 1000)

    def _format_source_time(self, timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000).isoformat(timespec='seconds')

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
                        'type': child.object_type,
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
        node_type = str(node_info['type'])

        if 'water_level' in values or 'h_i_t' in values:
            water_level = values.get('water_level', values.get('h_i_t', 0.0))
            metrics_list.append(self._create_metrics(
                object_id=node_id,
                object_name=node_name,
                object_type=node_type,
                step_index=step_index,
                metrics_code='water_level',
                value=water_level,
            ))

        if 'water_flow' in values or 'qtot_i_t' in values or 'q_out' in values:
            water_flow = values.get('water_flow', values.get('qtot_i_t', values.get('q_out', 0.0)))
            metrics_list.append(self._create_metrics(
                object_id=node_id,
                object_name=node_name,
                object_type=node_type,
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
            cs_type = str(cross_section_info.get(cs_id, {}).get('type', 'CrossSection'))
            metrics_list.append(self._create_metrics(
                object_id=cs_id,
                object_name=cs_name,
                object_type=cs_type,
                step_index=step_index,
                metrics_code='water_level',
                value=node_water_level,
            ))
            metrics_list.append(self._create_metrics(
                object_id=cs_id,
                object_name=cs_name,
                object_type=cs_type,
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
        node_type = str(node_info['type'])
        for metrics_code, value in values.items():
            metrics_list.append(self._create_metrics(
                object_id=node_id,
                object_name=node_name,
                object_type=node_type,
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
                if time_series.object_id and time_series.metrics_code:
                    cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._time_series_cache[cache_key] = time_series
                if self._simulation_state and time_series.object_id:
                    state_key = f"{time_series.object_id}_{time_series.metrics_code}"
                    self._simulation_state[state_key] = time_series

                if self._is_forecast_related_time_series(time_series):
                    relevant_update = True
            except Exception as exc:
                logger.error(
                    f"Error updating boundary condition for {time_series.object_name}: {exc}",
                    exc_info=True,
                )

        if not relevant_update or not self._trigger_on_condition_update or self._forecast_horizon <= 0:
            return

        if not self._hydraulic_solver:
            return

        try:
            with self._forecast_lock:
                forecast_plan = self._build_event_forecast_plan(self._current_step)
                if not forecast_plan:
                    return

                current_results = self._hydraulic_solver.get_current_results()
                window_results = self._run_forecast_window(
                    start_step=int(forecast_plan['start_step']),
                    end_step=int(forecast_plan['window_end_step']),
                    result_window_from_step=int(forecast_plan['result_window_from_step']),
                    anchor_results=current_results,
                )
                metrics_list = self._convert_window_results_to_metrics(
                    window_results,
                    send_from_step=int(forecast_plan['send_from_step']),
                    send_to_step=int(forecast_plan['send_to_step']),
                )
                if metrics_list:
                    self.send_metrics_batch(metrics_list)
                    self._record_forecast_plan_execution(forecast_plan)
                    logger.info(
                        "工况触发立即发送：触发步=%s，发送步范围=[%s,%s]，发送记录总数=%s",
                        forecast_plan['start_step'],
                        forecast_plan['send_from_step'],
                        forecast_plan['send_to_step'],
                        len(metrics_list),
                    )
        except Exception as exc:
            logger.error(f"Immediate forecast after condition update failed: {exc}", exc_info=True)

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        处理中心下发的 calculation_request。

        当前实现采用保守策略：
        1. 如事件中携带 object_time_series，则先并入本地时间序列缓存
        2. 以“当前步或事件指定步”为起点执行一轮滚动预测
        3. 将预测结果转换为 ObjectTimeSeries 后回传 coordinator
        """
        logger.info(
            "Received TimeSeriesCalculationRequest: command_id=%s, event_type=%s, target_agent=%s, time_series_url=%s",
            request.command_id,
            getattr(request.hydro_event, 'hydro_event_type', None),
            getattr(request.target_agent_instance, 'agent_code', None),
            getattr(request.hydro_event, 'time_series_url', None),
        )

        if not self._hydraulic_solver:
            logger.warning("Ignore calculation request because hydraulic solver is not initialized")
            response = TimeSeriesCalculationResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                object_time_series_list=[],
                broadcast=False,
            )
            self.send_response(response)
            return

        try:
            with self._forecast_lock:
                # 允许中心在 calculation_request 中直接携带时间序列输入，
                # 这样无需额外等待 time_series_data_update_request 也能立即计算。
                self._ingest_event_time_series(request.hydro_event)
                if self._is_weather_forecast_source(getattr(request.hydro_event, 'hydro_event_source_type', None)):
                    self._reset_weather_forecast_cache()
                    self._cache_weather_forecast_time_series(
                        self._resolve_weather_forecast_time_series_list(request.hydro_event)
                    )

                start_step = self._resolve_calculation_start_step(request)
                current_results = self._hydraulic_solver.get_current_results()
                window_results = self._run_forecast_window(
                    start_step=start_step,
                    end_step=self._calculate_forecast_end_step(start_step),
                    result_window_from_step=start_step,
                    anchor_results=current_results,
                )
                object_time_series_list = self._convert_window_results_to_time_series(window_results)

            response = TimeSeriesCalculationResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                object_time_series_list=object_time_series_list,
                broadcast=False,
            )
            self.send_response(response)

            logger.info(
                "计算请求响应已发送：command_id=%s，起始步=%s，返回序列数=%s",
                request.command_id,
                start_step,
                len(object_time_series_list),
            )
        except Exception as exc:
            logger.error(f"Error handling calculation request: {exc}", exc_info=True)
            response = TimeSeriesCalculationResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.FAILED,
                source_agent_instance=self,
                hydro_event=request.hydro_event,
                object_time_series_list=[],
                broadcast=False,
            )
            self.send_response(response)

    def _resolve_boundary_metric_target(
        self,
        time_series: ObjectTimeSeries,
        metrics_code: str,
        normalized_code: str,
        normalized_boundary_metrics: set[str],
    ) -> Optional[str]:
        boundary_target = self._boundary_metric_aliases.get(metrics_code)
        if boundary_target is None:
            boundary_target = self._boundary_metric_aliases.get(normalized_code)
        if boundary_target is not None:
            return boundary_target

        if normalized_code == 'water_level':
            return 'h_i_t'

        if normalized_code != 'water_flow':
            return None

        descriptor = ' '.join(
            str(value).lower()
            for value in (
                time_series.time_series_name,
                time_series.object_name,
                time_series.object_type,
            )
            if value
        )

        if any(keyword in descriptor for keyword in ('入流', 'inflow', '旁侧', '侧向', 'lateral')):
            return 'Inflow_i_t'

        if any(keyword in descriptor for keyword in ('出流', 'outflow', '需水', 'demand', '取水')):
            return 'qtot_i_t'

        if normalized_code in normalized_boundary_metrics:
            if normalized_code == 'water_flow':
                return 'Inflow_i_t'
            return metrics_code

        return 'Inflow_i_t'

    def _is_forecast_related_time_series(self, time_series: ObjectTimeSeries) -> bool:
        metrics_code = time_series.metrics_code
        if not metrics_code:
            return False
        normalized = str(metrics_code).lower()
        if normalized in {key.lower() for key in self._boundary_metric_aliases.keys()}:
            return True
        if normalized in {key.lower() for key in self._control_metric_aliases.keys()}:
            return True
        if normalized in {'water_flow', 'water_level'}:
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

    def _ingest_event_time_series(self, hydro_event: Any) -> None:
        """将 calculation_request 携带的时间序列直接并入本地缓存。"""
        object_time_series = self._resolve_weather_forecast_time_series_list(hydro_event)
        if not object_time_series:
            return

        for time_series in object_time_series:
            if not time_series.object_id or not time_series.metrics_code:
                continue

            cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
            self._time_series_cache[cache_key] = time_series

            if self._simulation_state is not None:
                self._simulation_state[cache_key] = time_series

        logger.info("Merged %s event time series into local cache", len(object_time_series))

    def _resolve_weather_forecast_time_series_list(self, hydro_event: Any) -> List[ObjectTimeSeries]:
        """
        解析天气预报事件中的时间序列列表。

        优先级：
        1. 如果事件带有 time_series_url，则下载 JSON 并读取其中的 object_time_series
        2. 否则退回事件内联的 object_time_series
        """
        if hydro_event is None:
            return []

        time_series_url = getattr(hydro_event, 'time_series_url', None)
        if time_series_url:
            downloaded_series = self._download_time_series_from_url(str(time_series_url))
            if downloaded_series:
                logger.info(
                    "天气预报时间序列下载成功：time_series_url=%s，序列条数=%s",
                    time_series_url,
                    len(downloaded_series),
                )
                return downloaded_series
            logger.warning(
                "天气预报时间序列下载后未解析到有效数据，回退使用事件内联 object_time_series：time_series_url=%s",
                time_series_url,
            )

        return list(getattr(hydro_event, 'object_time_series', None) or [])

    def _download_time_series_from_url(self, time_series_url: str) -> List[ObjectTimeSeries]:
        """下载天气预报时间序列 JSON，并提取其中的 object_time_series。"""
        try:
            parsed = urlparse(time_series_url)
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
                payload = response.read().decode('utf-8')

            data = json.loads(payload)
            raw_series_list = data.get('object_time_series', [])
            object_time_series_list = [ObjectTimeSeries.model_validate(item) for item in raw_series_list]
            logger.info(
                "天气预报时间序列下载并解析完成：time_series_url=%s，object_time_series条数=%s",
                time_series_url,
                len(object_time_series_list),
            )
            return object_time_series_list
        except (HTTPError, URLError) as exc:
            logger.error(f"下载天气预报时间序列失败：url={time_series_url}, error={exc}")
            return []
        except Exception as exc:
            logger.error(f"解析天气预报时间序列失败：url={time_series_url}, error={exc}", exc_info=True)
            return []

    def _sync_weather_forecast_series_marks(
        self,
        time_series_list: List[ObjectTimeSeries],
        source_type: Optional[str],
    ) -> None:
        """
        同步“哪些原始时间序列属于天气预报”的标记集合。

        如果当前不是天气预报事件，则把本批次同 key 的旧天气标记移除，
        避免后续常规工况被误跳过。
        """
        is_weather_source = self._is_weather_forecast_source(source_type)
        if is_weather_source:
            self._weather_forecast_source_series_keys.clear()
        for time_series in time_series_list:
            if not time_series.object_id or not time_series.metrics_code:
                continue
            raw_cache_key = f"{time_series.object_id}_{time_series.metrics_code}"
            if is_weather_source:
                self._weather_forecast_source_series_keys.add(raw_cache_key)
            else:
                self._weather_forecast_source_series_keys.discard(raw_cache_key)

    def _reset_weather_forecast_cache(self) -> None:
        """收到新的天气预报事件后，重建天气缓存，避免历史节点残留。"""
        self._weather_forecast_inflow_cache.clear()
        self._weather_forecast_target_nodes.clear()
        self._weather_forecast_steps_by_node.clear()
        self._weather_forecast_logged_hits.clear()
        self._weather_forecast_logged_injections.clear()
        logger.info("天气预报缓存已清空，准备按最新事件重建")

    def _cache_weather_forecast_time_series(self, time_series_list: List[ObjectTimeSeries]) -> None:
        """
        将天气预报工况转换为“算法节点 + step -> value”的缓存。

        规则：
        1. 事件里的 object_id 先视为上游对象 ID
        2. 从 topology.downstream_map 中取第一个下游节点 ID 作为算法注入目标
        3. 以 node_id#step 作为缓存键，value 为该步入流
        """
        cached_count = 0

        for time_series in time_series_list:
            if time_series.object_id is None or not time_series.metrics_code:
                continue
            if str(time_series.metrics_code).strip().lower() != 'water_flow':
                logger.info(
                    "跳过非流量天气序列：object_id=%s，time_series_name=%s，metrics_code=%s",
                    time_series.object_id,
                    time_series.time_series_name,
                    time_series.metrics_code,
                )
                continue

            target_node_id = self._resolve_weather_target_node_id(int(time_series.object_id))
            if target_node_id is None:
                logger.warning(
                    "Skip weather forecast series because downstream target is missing: source_object_id=%s",
                    time_series.object_id,
                )
                continue

            self._weather_forecast_target_nodes.add(target_node_id)
            logger.info(
                "天气预报映射建立成功：源对象ID=%s，目标节点ID=%s，序列名=%s，点数=%s",
                time_series.object_id,
                target_node_id,
                time_series.time_series_name,
                len(time_series.time_series),
            )

            for ts_value in time_series.time_series:
                if ts_value.step is None or ts_value.value is None:
                    continue
                step = int(ts_value.step)
                cache_key = self._build_weather_forecast_cache_key(target_node_id, step)
                self._weather_forecast_inflow_cache[cache_key] = float(ts_value.value)
                step_list = self._weather_forecast_steps_by_node.setdefault(target_node_id, [])
                if step not in step_list:
                    step_list.append(step)
                logger.info(
                    "天气预报缓存写入：cache_key=%s，源对象ID=%s，目标节点ID=%s，step=%s，value=%s",
                    cache_key,
                    time_series.object_id,
                    target_node_id,
                    step,
                    float(ts_value.value),
                )
                cached_count += 1

            self._weather_forecast_steps_by_node[target_node_id].sort()
            logger.info(
                "天气预报生效步已准备：目标节点ID=%s，steps=%s",
                target_node_id,
                self._weather_forecast_steps_by_node[target_node_id],
            )

        logger.info("Cached %s weather forecast inflow points", cached_count)

    def _resolve_weather_target_node_id(self, source_object_id: int) -> Optional[int]:
        """
        根据 topology 的 downstream_map，把天气预报对象 ID 映射为算法节点 ID。

        映射规则与需求一致：取 connections 中 from.id 对应的第一个 to.id。
        """
        if not self._topology:
            return None

        downstream_ids = self._topology.downstream_map.get(source_object_id, [])
        if not downstream_ids:
            return None
        return int(downstream_ids[0])

    def _merge_weather_forecast_inputs(
        self,
        step: int,
        boundary_conditions: Dict[int, Dict[str, float]],
    ) -> None:
        """把当前步命中的天气预报入流合并到边界条件中。"""
        if not self._weather_forecast_target_nodes:
            return

        for node_id in self._weather_forecast_target_nodes:
            effective_step, cached_value = self._get_weather_forecast_value(node_id, step)
            if cached_value is None:
                continue
            boundary_conditions.setdefault(node_id, {})['Inflow_i_t'] = float(cached_value)
            injection_log_key = f"{node_id}#{step}#{effective_step}"
            if injection_log_key not in self._weather_forecast_logged_injections:
                self._weather_forecast_logged_injections.add(injection_log_key)
                logger.info(
                    "天气预报入流已注入：当前步=%s，目标节点ID=%s，生效步=%s，入流=%s",
                    step,
                    node_id,
                    effective_step,
                    float(cached_value),
                )

    def _build_weather_forecast_cache_key(self, object_id: int, step: int) -> str:
        """生成天气预报步级缓存键。"""
        return f"{object_id}#{step}"

    def _get_weather_forecast_value(self, object_id: int, step: int) -> Tuple[Optional[int], Optional[float]]:
        """
        获取当前步应生效的天气预报值。

        规则：
        1. 找到该节点所有预报步中小于等于当前 step 的最大步
        2. 返回该步对应的值
        3. 如果当前步早于第一个预报步，则返回 None
        """
        step_list = self._weather_forecast_steps_by_node.get(object_id, [])
        if not step_list:
            logger.info(
                "天气预报查找跳过：目标节点ID=%s，当前步=%s，原因=没有缓存步",
                object_id,
                step,
            )
            return None, None

        effective_step: Optional[int] = None
        for candidate_step in step_list:
            if candidate_step > step:
                break
            effective_step = candidate_step

        if effective_step is None:
            logger.info(
                "天气预报查找跳过：目标节点ID=%s，当前步=%s，首个生效步=%s",
                object_id,
                step,
                step_list[0],
            )
            return None, None

        cache_key = self._build_weather_forecast_cache_key(object_id, effective_step)
        cached_value = self._weather_forecast_inflow_cache.get(cache_key)
        hit_log_key = f"{object_id}#{step}#{effective_step}"
        if hit_log_key not in self._weather_forecast_logged_hits:
            self._weather_forecast_logged_hits.add(hit_log_key)
            logger.info(
                "天气预报查找命中：目标节点ID=%s，当前步=%s，生效步=%s，cache_key=%s，value=%s",
                object_id,
                step,
                effective_step,
                cache_key,
                cached_value,
            )
        return effective_step, cached_value

    def _is_weather_forecast_source(self, source_type: Optional[str]) -> bool:
        """判断事件来源是否为天气预报。"""
        if not source_type:
            return False
        normalized = str(source_type).strip().upper()
        return normalized in {'WEATHER_FOR_CAST', 'WEATHER_FORECAST'}

    def _resolve_calculation_start_step(self, request: TimeSeriesCalculationRequest) -> int:
        """
        计算 calculation_request 的起算步。

        优先使用事件中显式声明的 auto_schedule_at_step；
        如果没有，则退化为当前仿真步；
        再不行则从第 1 步开始。
        """
        event_step = self._as_int(getattr(request.hydro_event, 'auto_schedule_at_step', -1), -1)
        if event_step > 0:
            return max(event_step, self._current_step or 0)
        if self._current_step > 0:
            return self._current_step
        return 1

    def _convert_window_results_to_time_series(
        self,
        window_results: Dict[int, Dict[int, Dict[str, float]]],
    ) -> List[ObjectTimeSeries]:
        """将按步结果窗口转换为 coordinator 可消费的 ObjectTimeSeries 列表。"""
        node_info, _ = self._build_topology_mappings()
        series_map: Dict[tuple[int, str], ObjectTimeSeries] = {}

        for step in sorted(window_results.keys()):
            for object_id, metrics_values in window_results[step].items():
                node_meta = node_info.get(object_id, {})
                object_name = str(node_meta.get('name', object_id))
                object_type = str(node_meta.get('type', 'HydroObject'))

                for metrics_code, value in metrics_values.items():
                    series_key = (object_id, metrics_code)
                    if series_key not in series_map:
                        # 使用中文注释说明：按“对象 + 指标”聚合整段预测窗口，
                        # coordinator 收到后可以直接按 step 展开。
                        series_map[series_key] = ObjectTimeSeries(
                            time_series_name=f"{object_name}_{metrics_code}",
                            object_id=object_id,
                            object_type=object_type,
                            object_name=object_name,
                            metrics_code=metrics_code,
                            time_series=[],
                        )

                    series_map[series_key].time_series.append(
                        TimeSeriesValue(
                            step=step,
                            time=self._format_source_time(self._calculate_source_timestamp_ms(step)),
                            value=float(value),
                        )
                    )

        return list(series_map.values())

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
        # return f"{self.hydros_cluster_id}/hydros/simulation/jobs/{self.biz_scene_instance_id}/realtime/objects"
        return f"/hydros/data/edges/{self.hydros_cluster_id}/{self.biz_scene_instance_id}"

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
