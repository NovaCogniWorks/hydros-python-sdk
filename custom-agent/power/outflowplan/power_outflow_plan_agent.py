"""
水电站出力时间序列智能体示例。

该实现基于 OutflowPlanAgent 事件入口，在收到外发时间序列请求后，
生成站点出力 `Station/power` 时间序列并回传给协调器。
"""

import copy
import json
import logging
import sys
import tempfile
from typing import Any, Dict, Optional, List
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen
import yaml

CURRENT_DIR = Path(__file__).resolve().parent
HYDROSIM_DIR = CURRENT_DIR.parent / "mpc"
DATA_DIR = CURRENT_DIR.parent / "data"
RUNTIME_DIR = CURRENT_DIR.parent / ".runtime" / "outflowplan"
if str(HYDROSIM_DIR) not in sys.path:
    sys.path.insert(0, str(HYDROSIM_DIR))

from hydrosim_api import HydroSimulationApi
from hydros_agent_sdk import (
    ErrorCodes,
    handle_agent_errors,
)
from hydros_agent_sdk.agents import OutflowPlanAgent
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    OutflowTimeSeriesRequest,
    OutflowTimeSeriesResponse,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    CommandStatus,
    ObjectTimeSeries,
    TimeSeriesValue,
)
from hydros_agent_sdk.protocol.events import (
    OutflowTimeSeriesDataChangedEvent,
    TimeSeriesDataChangedEvent,
)

logger = logging.getLogger(__name__)


class HydroSimInputFileResolver:
    """解析 HydroSim 输入文件来源，并按需下载远程配置到本地运行目录。"""

    def __init__(self, properties, runtime_dir: Path):
        self._properties = properties
        self._runtime_dir = runtime_dir

    def resolve(
        self,
        url_property_names: List[str],
        path_property_names: List[str],
        default_path: str,
        local_filename: str,
    ) -> str:
        source = self._get_first_configured_value(url_property_names + path_property_names)
        if not source:
            return str(Path(default_path).resolve())
        if self._is_remote_url(source):
            return self._download_to_runtime_dir(source, local_filename)
        return str(Path(source).resolve())

    def _get_first_configured_value(self, property_names: List[str]) -> Optional[str]:
        for property_name in property_names:
            value = self._properties.get_property(property_name, None)
            if value:
                return str(value).strip()
        return None

    @staticmethod
    def _is_remote_url(value: str) -> bool:
        return value.startswith("http://") or value.startswith("https://")

    def _download_to_runtime_dir(self, source_url: str, local_filename: str) -> str:
        parsed = urlparse(source_url)
        encoded_url = urlunparse(parsed._replace(path=quote(parsed.path, safe="/:@!$&'()*+,;=")))
        request = Request(encoded_url, headers={"User-Agent": "HydrosPythonSdk/1.0"})
        target_path = self._runtime_dir / local_filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(request, timeout=30) as response:
            target_path.write_bytes(response.read())
        logger.info("Downloaded HydroSim input file from %s to %s", source_url, target_path)
        return str(target_path.resolve())


class PowerOutflowPlanAgent(OutflowPlanAgent):
    """
    水电站出力时间序列智能体的具体实现。

    该智能体的主要功能包括：
    1. 加载水网拓扑
    2. 初始化 HydroSim 出力规划会话
    3. 响应外发时间序列请求
    4. 根据水文事件生成站点出力时间序列
    """

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
        **kwargs
    ):
        """初始化外发流量计划智能体实例。"""
        super().__init__(
            sim_coordination_client=sim_coordination_client,
            agent_id=agent_id,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_name=agent_name,
            context=context,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            **kwargs
        )

        # 拓扑对象
        self._topology = None
        self._hydrosim_api = HydroSimulationApi()
        self._hydrosim_initialized = False
        self._hydrosim_runtime_dir = RUNTIME_DIR
        self._hydrosim_runtime_dir.mkdir(parents=True, exist_ok=True)
        self._hydrosim_input_resolver = HydroSimInputFileResolver(
            properties=self.properties,
            runtime_dir=self._hydrosim_runtime_dir,
        )

        logger.info("PowerOutflowPlanAgent created: %s", agent_id)
        logger.warning("PowerOutflowPlanAgent runtime file marker: %s", __file__)

    @handle_agent_errors(ErrorCodes.AGENT_INIT_FAILURE)
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        response = super().on_init(request)
        try:
            self._initialize_hydrosim_session()
        except FileNotFoundError as exc:
            logger.warning("HydroSim init skipped because configuration files are missing: %s", exc)
        except Exception:
            logger.exception("HydroSim init failed during agent initialization.")
        return response

    @handle_agent_errors(ErrorCodes.SIMULATION_EXECUTION_FAILURE)
    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        处理外发时间序列请求并输出站点出力时间序列。

        该方法：
        1. 从请求中提取事件信息
        2. 执行水电站出力规划逻辑
        3. 生成 ObjectTimeSeries 格式的结果
        4. 将响应发送回协调器
        """
        logger.info(f"Received OutflowTimeSeriesRequest, commandId={request.command_id}")
        logger.info(f"Event: {request.hydro_event}")
        logger.warning(
            "Power planning request marker: file=%s, event_url=%s, direct_load=%s, embedded_series=%s",
            __file__,
            getattr(request.hydro_event, "event_content_url", None),
            getattr(request.hydro_event, "direct_load_time_series", None),
            len(getattr(request.hydro_event, "object_time_series", []) or []),
        )

        try:
            hydro_event = request.hydro_event.model_copy(
                update={"source_agent_code": self.agent_code}
            )
            hydro_event = hydro_event.model_copy(
                update={
                    "object_time_series": self._normalize_object_time_series(
                        hydro_event.object_time_series
                    )
                }
            )

            # 执行出力计划计算
            planning_source_series = self._normalize_object_time_series(
                self._resolve_incoming_outflow_plans(hydro_event)
            )
            outflow_plans = self._execute_outflow_planning(hydro_event, planning_source_series)

            logger.info("Power planning completed, produced %s station time series", len(outflow_plans))

            # 构造响应
            response = OutflowTimeSeriesResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self,
                hydro_event=hydro_event,
                outflow_time_series_map={"Station": outflow_plans},
                broadcast=False
            )

            # 发送响应
            self.send_response(response)

            logger.info(
                f"发布协调指令成功,commandId={response.command_id},"
                f"commandType=OutflowTimeSeriesResponse 到MQTT Topic={self.sim_coordination_client.topic}"
            )

        except Exception as e:
            logger.error(f"Error in outflow planning: {e}", exc_info=True)
            raise

    def _resolve_incoming_outflow_plans(self, hydro_event) -> List[ObjectTimeSeries]:
        object_time_series = list(getattr(hydro_event, "object_time_series", []) or [])
        if object_time_series:
            logger.info(
                "Using object_time_series embedded in OUTFLOW_TIME_SERIES event, count=%s",
                len(object_time_series),
            )
            return object_time_series

        event_content_url = getattr(hydro_event, "event_content_url", None)
        if not event_content_url:
            logger.info("OUTFLOW_TIME_SERIES event has no object_time_series or event content URL")
            return []

        object_time_series = self._load_object_time_series_from_url(event_content_url)
        if object_time_series:
            logger.info(
                "Loaded object_time_series from event URL, count=%s, url=%s",
                len(object_time_series),
                event_content_url,
            )
        return object_time_series

    def _load_object_time_series_from_url(self, event_content_url: str) -> List[ObjectTimeSeries]:
        payload = self._load_event_payload_from_url(event_content_url)
        if payload is None:
            return []

        for event_model in (OutflowTimeSeriesDataChangedEvent, TimeSeriesDataChangedEvent):
            try:
                parsed_event = event_model.model_validate(payload)
            except Exception:
                continue
            if parsed_event.object_time_series:
                return parsed_event.object_time_series

        raw_series = payload.get("object_time_series") or payload.get("objectTimeSeries") or []
        result: List[ObjectTimeSeries] = []
        for item in raw_series:
            try:
                result.append(ObjectTimeSeries.model_validate(item))
            except Exception:
                logger.debug("Skipping invalid object_time_series item: %s", item, exc_info=True)
        return result

    def _load_event_payload_from_url(self, event_content_url: str) -> Optional[Dict[str, Any]]:
        parsed = urlparse(event_content_url)
        encoded_url = urlunparse(parsed._replace(path=quote(parsed.path)))
        request = Request(encoded_url, headers={"User-Agent": "HydrosPythonSdk/1.0"})

        try:
            with urlopen(request, timeout=10) as response:
                raw_content = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            logger.warning("Failed to fetch outflow event content from %s: %s", event_content_url, exc)
            return None

        try:
            payload = json.loads(raw_content)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        try:
            payload = yaml.safe_load(raw_content)
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse outflow event content from %s as JSON/YAML: %s", event_content_url, exc)
            return None

        if not isinstance(payload, dict):
            logger.warning(
                "Outflow event content from %s is not an object payload, actual_type=%s",
                event_content_url,
                type(payload).__name__,
            )
            return None
        return payload

    def _normalize_object_time_series(
        self,
        object_time_series_list: List[ObjectTimeSeries],
    ) -> List[ObjectTimeSeries]:
        normalized: List[ObjectTimeSeries] = []

        for object_time_series in object_time_series_list or []:
            object_ids = [object_id for object_id in (object_time_series.object_ids or []) if object_id is not None]
            if not object_ids:
                normalized.append(object_time_series)
                continue

            split_count = len(object_ids)
            for object_id in object_ids:
                split_time_series = []
                for time_series_value in object_time_series.time_series or []:
                    split_value = copy.deepcopy(time_series_value)
                    if split_value.value is not None:
                        split_value.value = round(split_value.value / split_count, 6)
                    split_time_series.append(split_value)

                normalized.append(
                    object_time_series.model_copy(
                        update={
                            "object_id": object_id,
                            "object_ids": [],
                            "time_series": split_time_series,
                        }
                    )
                )

        if normalized:
            logger.info(
                "Normalized object_time_series for outflow event: input=%s, output=%s",
                len(object_time_series_list or []),
                len(normalized),
            )
        return normalized

    def _execute_outflow_planning(self, hydro_event, planning_source_series: List[ObjectTimeSeries]) -> List[ObjectTimeSeries]:
        """
        执行具体的水电站出力规划逻辑。

        优先使用 MPC/HydroSim 算法包生成各站点出力时间序列。
        当输入事件中缺少可用的站点出力需求时间序列时，退化为示例逻辑。

        参数:
            hydro_event: 触发计划计算的水文事件

        返回:
            包含站点出力计划的时间序列列表 (ObjectTimeSeries)
        """
        logger.info("Executing power planning with HydroSim API...")

        planning_payload = self._build_power_planning_payload_from_properties()
        if planning_payload is None:
            self._log_missing_station_power_series([], source="properties.objects_time_series_url")

        if planning_payload is None:
            planning_payload = self._build_power_planning_payload(planning_source_series)
        if planning_payload is None:
            self._log_missing_station_power_series(planning_source_series, source="normalized_event_series")
            planning_payload = self._build_power_planning_payload_from_event_url(hydro_event)

        if planning_payload is not None:
            self._ensure_hydrosim_initialized()
            with tempfile.TemporaryDirectory(prefix="hydrosim_power_plan_") as temp_dir:
                planning_file = self._write_power_planning_file(temp_dir, planning_payload)
                planning_result = self._hydrosim_api.get_station_power_planning_series(planning_file)
            station_power_plans = self._build_station_object_time_series(
                planning_result.get("station_power_series", [])
            )
            logger.info("HydroSim power planning completed, produced %s station series", len(station_power_plans))
            return station_power_plans

        inflow_payload = self._build_inflow_planning_payload(planning_source_series)
        if inflow_payload is None:
            inflow_payload = self._build_inflow_planning_payload_from_event_url(hydro_event)

        if inflow_payload is not None:
            self._ensure_hydrosim_initialized()
            with tempfile.TemporaryDirectory(prefix="hydrosim_inflow_plan_") as temp_dir:
                inflow_file = self._write_inflow_planning_file(temp_dir, inflow_payload)
                planning_result = self._hydrosim_api.get_station_power_planning_series_from_inflow(inflow_file)
            station_power_plans = self._build_station_object_time_series(
                planning_result.get("station_power_series", [])
            )
            logger.info("HydroSim inflow-driven power planning completed, produced %s station series", len(station_power_plans))
            return station_power_plans

        logger.warning("No Station/power or Station/water_flow planning series found in incoming event, fallback to sample logic.")
        return self._build_fallback_plans(hydro_event)

    def _build_power_planning_payload(
        self,
        object_time_series_list: List[ObjectTimeSeries],
    ) -> Optional[List[ObjectTimeSeries]]:
        planning_series = [
            item
            for item in object_time_series_list or []
            if item.object_type == "Station" and item.metrics_code == "power"
        ]
        return planning_series or None

    def _build_inflow_planning_payload(
        self,
        object_time_series_list: List[ObjectTimeSeries],
    ) -> Optional[List[ObjectTimeSeries]]:
        inflow_series = [
            item
            for item in object_time_series_list or []
            if item.object_type == "Station" and item.metrics_code == "water_flow"
        ]
        return inflow_series or None

    def _build_inflow_planning_payload_from_event_url(self, hydro_event) -> Optional[List[ObjectTimeSeries]]:
        event_content_url = getattr(hydro_event, "event_content_url", None)
        if not event_content_url:
            return None
        payload = self._load_event_payload_from_url(event_content_url)
        if payload is None:
            return None
        raw_series = payload.get("object_time_series") or payload.get("objectTimeSeries") or []
        inflow_series: List[ObjectTimeSeries] = []
        for item in raw_series:
            try:
                parsed_item = ObjectTimeSeries.model_validate(item)
            except Exception:
                logger.debug("Skipping invalid inflow item from %s: %s", event_content_url, item, exc_info=True)
                continue
            if parsed_item.object_type == "Station" and parsed_item.metrics_code == "water_flow":
                inflow_series.append(parsed_item)
        return inflow_series or None

    def _build_power_planning_payload_from_properties(self) -> Optional[List[ObjectTimeSeries]]:
        planning_url = self.properties.get_property("objects_time_series_url", None)
        if not planning_url:
            logger.info("Property objects_time_series_url is not configured.")
            return None

        payload = self._load_event_payload_from_url(str(planning_url))
        if payload is None:
            logger.warning("Failed to load planning payload from properties.objects_time_series_url=%s", planning_url)
            return None

        planning_series = self._extract_station_power_series_from_payload(payload, str(planning_url))
        if planning_series:
            logger.info(
                "Loaded Station/power planning series from properties.objects_time_series_url, count=%s, url=%s",
                len(planning_series),
                planning_url,
            )
        return planning_series

    def _build_power_planning_payload_from_event_url(self, hydro_event) -> Optional[List[ObjectTimeSeries]]:
        event_content_url = getattr(hydro_event, "event_content_url", None)
        if not event_content_url:
            logger.info("No event_content_url available for loading Station/power planning payload.")
            return None

        payload = self._load_event_payload_from_url(event_content_url)
        if payload is None:
            return None

        raw_series = payload.get("object_time_series") or payload.get("objectTimeSeries") or []
        if not raw_series:
            logger.warning(
                "Event payload from %s does not contain object_time_series/objectTimeSeries.",
                event_content_url,
            )
            return None

        planning_series = self._extract_station_power_series_from_payload(payload, event_content_url)

        if planning_series:
            logger.info(
                "Loaded Station/power planning series from event URL, count=%s, url=%s",
                len(planning_series),
                event_content_url,
            )
        else:
            self._log_missing_station_power_series(raw_series, source=f"event_url:{event_content_url}")
        return planning_series or None

    def _extract_station_power_series_from_payload(
        self,
        payload: Dict[str, Any],
        payload_source: str,
    ) -> List[ObjectTimeSeries]:
        raw_series = payload.get("object_time_series") or payload.get("objectTimeSeries") or []
        planning_series: List[ObjectTimeSeries] = []
        for item in raw_series:
            try:
                parsed_item = ObjectTimeSeries.model_validate(item)
            except Exception:
                logger.debug("Skipping invalid planning item from %s: %s", payload_source, item, exc_info=True)
                continue
            if parsed_item.object_type == "Station" and parsed_item.metrics_code == "power":
                planning_series.append(parsed_item)
        return planning_series

    def _log_missing_station_power_series(self, object_time_series_list, source: str) -> None:
        summary = []
        for item in object_time_series_list or []:
            if isinstance(item, ObjectTimeSeries):
                summary.append(
                    f"{item.object_type}/{item.metrics_code}/id={item.object_id or item.object_ids}"
                )
                continue

            if isinstance(item, dict):
                summary.append(
                    f"{item.get('object_type') or item.get('objectType')}/"
                    f"{item.get('metrics_code') or item.get('metricsCode')}/"
                    f"id={item.get('object_id') or item.get('objectId') or item.get('object_ids') or item.get('objectIds')}"
                )
                continue

            summary.append(type(item).__name__)

        logger.warning(
            "No Station/power series matched for source=%s, candidates=%s",
            source,
            summary,
        )

    def _initialize_hydrosim_session(self) -> None:
        time_series_file = self._resolve_hydrosim_input_file(
            url_property_names=["hydrosim_time_series_url", "objects_time_series_url"],
            path_property_names=["hydrosim_time_series_file", "hydrosim_power_planning_file"],
            default_path=str(DATA_DIR / "time_series_power_planning.json"),
            local_filename="time_series_power_planning.json",
        )
        mpc_config_file = self._resolve_hydrosim_input_file(
            url_property_names=["mpc_config_url", "hydrosim_mpc_config_url"],
            path_property_names=["hydrosim_mpc_config_file"],
            default_path=str(DATA_DIR / "mpc_config.yaml"),
            local_filename="mpc_config.yaml",
        )
        initial_states_file = self._resolve_hydrosim_input_file(
            url_property_names=["init_state_config_url", "hydrosim_initial_states_url"],
            path_property_names=["hydrosim_initial_states_file"],
            default_path=str(DATA_DIR / "initial_states.yaml"),
            local_filename="initial_states.yaml",
        )
        constraints_file = self._resolve_hydrosim_input_file(
            url_property_names=["target_and_constrain_config_url", "hydrosim_constraints_url"],
            path_property_names=["hydrosim_constraints_file"],
            default_path=str(DATA_DIR / "constrains_targets.yaml"),
            local_filename="constrains_targets.yaml",
        )

        init_result = self._hydrosim_api.initialize(
            time_series_file=time_series_file,
            mpc_config_file=mpc_config_file,
            initial_states_file=initial_states_file,
            constraints_file=constraints_file,
        )
        self._hydrosim_initialized = True
        logger.info("HydroSim initialized for power planning, session=%s", init_result["session"]["session_id"])

    def _ensure_hydrosim_initialized(self) -> None:
        if not self._hydrosim_initialized:
            self._initialize_hydrosim_session()

    def _resolve_hydrosim_input_file(
        self,
        url_property_names: List[str],
        path_property_names: List[str],
        default_path: str,
        local_filename: str,
    ) -> str:
        return self._hydrosim_input_resolver.resolve(
            url_property_names=url_property_names,
            path_property_names=path_property_names,
            default_path=default_path,
            local_filename=local_filename,
        )

    def _write_power_planning_file(self, temp_dir: str, object_time_series_list: List[ObjectTimeSeries]) -> str:
        payload = {
            "object_time_series": [
                item.model_dump(mode="json", exclude_none=True)
                for item in object_time_series_list
                if item.object_type == "Station" and item.metrics_code == "power"
            ]
        }
        if not payload["object_time_series"]:
            raise ValueError("输入事件中未找到可用于出力规划的 Station/power 时间序列。")
        planning_file = Path(temp_dir) / "time_series_power_planning.json"
        with open(planning_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return str(planning_file)

    def _write_inflow_planning_file(self, temp_dir: str, object_time_series_list: List[ObjectTimeSeries]) -> str:
        payload = {
            "object_time_series": [
                item.model_dump(mode="json", exclude_none=True)
                for item in object_time_series_list
                if item.object_type == "Station" and item.metrics_code == "water_flow"
            ]
        }
        if not payload["object_time_series"]:
            raise ValueError("No Station/water_flow time series found for inflow-driven power planning.")
        planning_file = Path(temp_dir) / "time_series_inflow_planning.json"
        with open(planning_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return str(planning_file)

    def _build_station_object_time_series(self, station_power_series: List[dict]) -> List[ObjectTimeSeries]:
        result: List[ObjectTimeSeries] = []
        for station in station_power_series:
            result.append(
                ObjectTimeSeries(
                    time_series_name=f"{station['station']}_power_plan",
                    object_id=int(station["node_id"]),
                    object_type="Station",
                    object_name=station["station"],
                    metrics_code="power",
                    time_series=[
                        TimeSeriesValue(step=int(row["step"]), value=float(row["value"]))
                        for row in station.get("time_series", [])
                    ],
                )
            )
        return result

    def _build_fallback_plans(self, hydro_event) -> List[ObjectTimeSeries]:
        power_plans = []
        planning_horizon = self.properties.get_property('planning_horizon', 24)
        if self._topology:
            for top_obj in self._topology.top_objects[:3]:
                time_series_values = []
                for step in range(planning_horizon):
                    planned_power = self._calculate_planned_outflow(top_obj, step, hydro_event)
                    time_series_values.append(TimeSeriesValue(step=step, value=planned_power))
                power_plan = ObjectTimeSeries(
                    time_series_name=f"{top_obj.object_name}_power_plan",
                    object_id=top_obj.object_id,
                    object_type="Station",
                    object_name=top_obj.object_name,
                    metrics_code="power",
                    time_series=time_series_values
                )
                power_plans.append(power_plan)
        logger.info("Generated %s fallback power plans", len(power_plans))
        return power_plans

    def _calculate_planned_outflow(self, hydro_object, step: int, hydro_event) -> float:
        """
        计算特定对象在特定时间步长的计划流量。

        这是一个占位方法 - 请在此处实现实际的计划算法。
        """
        # 示例：简单的线性变化计划
        base_outflow = 100.0
        variation = step * 5.0

        return base_outflow + variation

    @handle_agent_errors(ErrorCodes.AGENT_TERMINATE_FAILURE)
    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        """
        终止外发流量计划智能体运行。

        该方法：
        1. 清理计划资源
        2. 在状态管理器中注销
        3. 返回终止响应
        """
        logger.info(f"Terminating outflow plan agent: {self.agent_id}")

        # 清理资源
        self._topology = None
        self._plan_config = {}
        if self._hydrosim_initialized:
            try:
                self._hydrosim_api.cancel()
            except Exception:
                logger.warning("Failed to cancel HydroSim session during terminate.", exc_info=True)
        self._hydrosim_initialized = False
        # 在状态管理器中注销
        self.state_manager.terminate_task(self.context)
        self.state_manager.remove_local_agent(self)

        logger.info(f"Outflow plan agent terminated: {self.agent_id}")

        return SimTaskTerminateResponse(
            context=self.context,
            command_id=request.command_id,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self,
            broadcast=False
        )
