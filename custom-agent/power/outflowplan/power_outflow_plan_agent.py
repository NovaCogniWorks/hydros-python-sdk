"""
外发流量计划智能体示例

该示例展示了如何基于 OutflowPlanAgent 基类实现一个具体的外发流量计划智能体。
该智能体通过响应水文事件来执行流量计划计算。
"""

import copy
import json
import logging
import sys
import tempfile
from typing import Optional, List
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

CURRENT_DIR = Path(__file__).resolve().parent
MPC_DIR = CURRENT_DIR.parent / "mpc"
if str(MPC_DIR) not in sys.path:
    sys.path.insert(0, str(MPC_DIR))

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


class PowerOutflowPlanAgent(OutflowPlanAgent):
    """
    外发流量计划智能体的具体实现。

    该智能体的主要功能包括：
    1. 加载水网拓扑
    2. 初始化流量计划模型
    3. 响应外发流量时间序列请求
    4. 根据水文事件生成下泄流量计划
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

        logger.info(f"MyOutflowPlanAgent created: {agent_id}")

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
        处理外发流量时间序列请求。

        该方法：
        1. 从请求中提取事件信息
        2. 执行外发流量计划计算逻辑
        3. 生成 ObjectTimeSeries 格式的结果
        4. 将响应发送回协调器
        """
        logger.info(f"Received OutflowTimeSeriesRequest, commandId={request.command_id}")
        logger.info(f"Event: {request.hydro_event}")

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
            if planning_source_series:
                outflow_plans = self._execute_outflow_planning(hydro_event, planning_source_series)
            else:
                outflow_plans = self._execute_outflow_planning(hydro_event, [])

            logger.info(f"Outflow planning completed, produced {len(outflow_plans)} time series")

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
        parsed = urlparse(event_content_url)
        encoded_url = urlunparse(parsed._replace(path=quote(parsed.path)))
        request = Request(encoded_url, headers={"User-Agent": "HydrosPythonSdk/1.0"})

        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load outflow event content from %s: %s", event_content_url, exc)
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
            包含流量计划的时间序列列表 (ObjectTimeSeries)
        """
        logger.info("Executing power planning with HydroSim API...")

        if planning_source_series:
            self._ensure_hydrosim_initialized()
            with tempfile.TemporaryDirectory(prefix="hydrosim_power_plan_") as temp_dir:
                planning_file = self._write_power_planning_file(temp_dir, planning_source_series)
                planning_result = self._hydrosim_api.get_station_power_planning_series(planning_file)
            station_power_plans = self._build_station_object_time_series(
                planning_result.get("station_power_series", [])
            )
            logger.info("HydroSim power planning completed, produced %s station series", len(station_power_plans))
            return station_power_plans

        logger.warning("No Station/power planning series found in incoming event, fallback to sample logic.")
        return self._build_fallback_plans(hydro_event)

    def _initialize_hydrosim_session(self) -> None:
        time_series_file = self._get_hydrosim_property(
            "hydrosim_time_series_file",
            str(MPC_DIR / "time_series_power_planning.json"),
        )
        mpc_config_file = self._get_hydrosim_property(
            "hydrosim_mpc_config_file",
            str(MPC_DIR / "mpc_config.yaml"),
        )
        initial_states_file = self._get_hydrosim_property(
            "hydrosim_initial_states_file",
            str(MPC_DIR / "initial_states.yaml"),
        )
        constraints_file = self._get_hydrosim_property(
            "hydrosim_constraints_file",
            str(MPC_DIR / "constrains_targets.yaml"),
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

    def _get_hydrosim_property(self, key: str, default: str) -> str:
        value = self.properties.get_property(key, default)
        return str(Path(value).resolve())

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
        outflow_plans = []
        planning_horizon = self.properties.get_property('planning_horizon', 24)
        if self._topology:
            for top_obj in self._topology.top_objects[:3]:
                time_series_values = []
                for step in range(planning_horizon):
                    planned_outflow = self._calculate_planned_outflow(top_obj, step, hydro_event)
                    time_series_values.append(TimeSeriesValue(step=step, value=planned_outflow))
                outflow_plan = ObjectTimeSeries(
                    time_series_name=f"{top_obj.object_name}_outflow_plan",
                    object_id=top_obj.object_id,
                    object_type=top_obj.object_type,
                    object_name=top_obj.object_name,
                    metrics_code="planned_outflow",
                    time_series=time_series_values
                )
                outflow_plans.append(outflow_plan)
        logger.info("Generated %s fallback plans", len(outflow_plans))
        return outflow_plans

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
