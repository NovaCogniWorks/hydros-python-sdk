"""
Hydro 智能体协调回调接口。

本模块提供类似 Java SimCoordinationCallback 的回调接口，让开发者专注业务逻辑，
由 SDK 处理：
- 消息解析和序列化
- MQTT 连接和订阅
- 消息过滤和路由
- 自动响应处理
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging

from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    SimTaskTerminateRequest,
    TimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateRequest,
    TimeSeriesCalculationRequest,
    AgentInstanceStatusReport,
    MpcResultReport,
    OutflowTimeSeriesRequest,
)
from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.protocol.models import HydroAgentInstance

logger = logging.getLogger(__name__)


class SimCoordinationCallback(ABC):
    """
    仿真协调回调的抽象基类。

    该接口定义收到协调指令时会被调用的回调方法。开发者必须实现三个核心方法：
    - get_component(): 返回 agent code
    - on_sim_task_init(): 处理任务初始化
    - on_tick(): 处理仿真步

    其他方法都有默认实现，可按需覆盖。

    类似 Java 侧 com.hydros.protocol.coordination.node.callback.SimCoordinationCallback。
    """

    @abstractmethod
    def get_component(self) -> str:
        """
        获取该回调处理器的 agent code。

        子类必须实现该方法。

        Returns:
            Agent code（例如 "TWINS_SIMULATION_AGENT"）
        """
        pass

    @abstractmethod
    def on_sim_task_init(self, request: SimTaskInitRequest):
        """
        收到仿真任务初始化请求时调用。

        这是启动仿真任务的主入口。子类必须实现该方法。

        Args:
            request: 任务初始化请求
        """
        pass

    @abstractmethod
    def on_tick(self, request: TickCmdRequest):
        """
        收到仿真 tick 指令时调用。

        每个仿真步都会调用该方法。子类必须实现该方法。

        Args:
            request: tick 指令请求
        """
        pass

    # 带默认实现的可选回调
    def is_remote_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """
        检查智能体实例是否为远端实例（运行在其他节点上）。

        默认实现返回 False（将全部智能体视为本地智能体）。
        可覆盖该方法来实现真正的远端智能体识别。

        Args:
            agent_instance: 要检查的智能体实例

        Returns:
            远端智能体返回 True，本地智能体返回 False
        """
        return False

    def _get_or_create_sibling_agent_cache(self) -> Dict[str, Dict[str, Dict[str, HydroAgentInstance]]]:
        """拿兄弟智能体缓存，按需懒初始化。"""
        cache = getattr(self, "_sibling_agent_instances_by_biz_scene_instance_id", None)
        if cache is None:
            cache = {}
            setattr(self, "_sibling_agent_instances_by_biz_scene_instance_id", cache)
        return cache

    def _get_biz_scene_instance_sibling_cache(
        self,
        biz_scene_instance_id: str,
    ) -> Dict[str, Dict[str, HydroAgentInstance]]:
        cache = self._get_or_create_sibling_agent_cache()
        biz_scene_instance_cache = cache.get(biz_scene_instance_id)
        if biz_scene_instance_cache is None:
            biz_scene_instance_cache = {
                "agent_code": {},
                "object_id": {},
            }
            cache[biz_scene_instance_id] = biz_scene_instance_cache
        else:
            biz_scene_instance_cache.setdefault("agent_code", {})
            biz_scene_instance_cache.setdefault("object_id", {})
        return biz_scene_instance_cache

    def _store_sibling_agent_instance(self, agent_instance: HydroAgentInstance) -> None:
        biz_scene_instance_id = agent_instance.context.biz_scene_instance_id
        biz_scene_instance_cache = self._get_biz_scene_instance_sibling_cache(biz_scene_instance_id)

        biz_scene_instance_cache["agent_code"][agent_instance.agent_code] = agent_instance

    @staticmethod
    def _extract_object_id(hydro_object: Any) -> Optional[int]:
        if hydro_object is None:
            return None

        value = None
        if isinstance(hydro_object, dict):
            value = hydro_object.get("object_id")
        else:
            value = getattr(hydro_object, "object_id", None)

        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_child_hydro_objects(hydro_object: Any) -> List[Any]:
        if hydro_object is None:
            return []

        children = None
        if isinstance(hydro_object, dict):
            children = hydro_object.get("children")
        else:
            children = getattr(hydro_object, "children", None)

        if children is None:
            return []
        if isinstance(children, dict):
            return list(children.values())
        if isinstance(children, list):
            return children
        return []

    def _index_hydro_object_owner(
        self,
        object_owner_cache: Dict[str, HydroAgentInstance],
        agent_instance: HydroAgentInstance,
        hydro_object: Any,
    ) -> int:
        indexed_count = 0
        object_id = self._extract_object_id(hydro_object)
        if object_id is not None:
            object_owner_cache[str(object_id)] = agent_instance
            indexed_count += 1

        for child in self._get_child_hydro_objects(hydro_object):
            indexed_count += self._index_hydro_object_owner(
                object_owner_cache,
                agent_instance,
                child,
            )
        return indexed_count

    def _store_agent_managed_top_objects(
        self,
        agent_instance: HydroAgentInstance,
        managed_top_objects: Optional[List[Any]],
    ) -> int:
        if not managed_top_objects:
            return 0

        biz_scene_instance_id = agent_instance.context.biz_scene_instance_id
        biz_scene_instance_cache = self._get_biz_scene_instance_sibling_cache(biz_scene_instance_id)
        object_owner_cache = biz_scene_instance_cache["object_id"]

        indexed_count = 0
        for top_object in managed_top_objects:
            indexed_count += self._index_hydro_object_owner(
                object_owner_cache,
                agent_instance,
                top_object,
            )

        model_context = ContextManager.get_context(biz_scene_instance_id)
        if model_context is None:
            return indexed_count

        context_indexed_count = model_context.on_agent_instance_sibling_created(
            agent_instance,
            managed_top_objects,
        )
        return max(indexed_count, context_indexed_count)

    def get_sibling_agent_instance(
        self,
        agent_code: str,
        biz_scene_instance_id: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        """按 agent_code 找兄弟智能体。"""
        if not agent_code:
            return None

        cache = self._get_or_create_sibling_agent_cache()
        if biz_scene_instance_id:
            biz_scene_instance_cache = cache.get(biz_scene_instance_id)
            if not biz_scene_instance_cache:
                return None
            return biz_scene_instance_cache["agent_code"].get(agent_code)

        for biz_scene_instance_cache in cache.values():
            agent = biz_scene_instance_cache["agent_code"].get(agent_code)
            if agent is not None:
                return agent
        return None

    def get_agent_by_object_id(
        self,
        object_id: int,
        biz_scene_instance_id: Optional[str] = None,
    ) -> Optional[HydroAgentInstance]:
        """按水工对象 ID 找拥有该对象的兄弟智能体。"""
        if object_id is None:
            return None

        object_id_key = str(object_id)
        cache = self._get_or_create_sibling_agent_cache()
        if biz_scene_instance_id:
            biz_scene_instance_cache = cache.get(biz_scene_instance_id)
            if biz_scene_instance_cache:
                agent = biz_scene_instance_cache.get("object_id", {}).get(object_id_key)
                if agent is not None:
                    return agent
            return ContextManager.get_agent_by_object_id(object_id, biz_scene_instance_id)

        for biz_scene_instance_cache in cache.values():
            agent = biz_scene_instance_cache.get("object_id", {}).get(object_id_key)
            if agent is not None:
                return agent
        return ContextManager.get_agent_by_object_id(object_id)

    def clear_sibling_agent_instances(self, biz_scene_instance_id: Optional[str] = None) -> None:
        """清掉兄弟智能体缓存，避免上下文结束后一直占着内存。"""
        cache = self._get_or_create_sibling_agent_cache()
        if biz_scene_instance_id is None:
            cache.clear()
            ContextManager.clear()
            return
        cache.pop(biz_scene_instance_id, None)
        ContextManager.remove(biz_scene_instance_id)

    def on_agent_instance_sibling_created(self, response: SimTaskInitResponse):
        """
        兄弟智能体实例创建时调用（远端智能体已初始化）。

        默认实现会记录该事件。可按需覆盖。

        Args:
            response: 远端智能体返回的任务初始化响应
        """
        for agent_instance in response.created_agent_instances:
            self._store_sibling_agent_instance(agent_instance)
            managed_top_objects = (
                (response.managed_top_objects or {}).get(agent_instance.agent_id)
                or (response.managed_top_objects or {}).get(agent_instance.agent_code)
                or []
            )
            indexed_count = self._store_agent_managed_top_objects(
                agent_instance,
                managed_top_objects,
            )
            if indexed_count:
                logger.info(
                    "Indexed managed hydro objects for sibling agent: agentId=%s, agentCode=%s, count=%s",
                    agent_instance.agent_id,
                    agent_instance.agent_code,
                    indexed_count,
                )
        logger.info(f"Sibling agent created: {response.source_agent_instance.agent_id}")

    def on_agent_instance_sibling_status_updated(self, report: AgentInstanceStatusReport):
        """
        兄弟智能体实例状态更新时调用。

        默认实现会记录该事件。可按需覆盖。

        Args:
            report: 远端智能体返回的状态报告
        """
        self._store_sibling_agent_instance(report.source_agent_instance)
        logger.info(f"Sibling agent status updated: {report.source_agent_instance.agent_id}")

    def on_mpc_result(self, report: MpcResultReport):
        """
        收到 MPC 结果报告时调用。

        默认实现仅记录事件。协调侧或数据侧消费者应覆盖该方法，
        用于持久化或转发 MPC 结果。
        """
        logger.info(
            "MPC result report received: source=%s, result_count=%s",
            report.source_agent_instance.agent_id,
            len(report.mpc_results),
        )

    def on_time_series_calculation(self, request: TimeSeriesCalculationRequest):
        """
        收到时序计算请求时调用。

        默认实现会记录警告。可按需覆盖。

        Args:
            request: 计算请求
        """
        logger.warning("Time series calculation received but not implemented")

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest):
        """
        时序数据更新时调用。

        默认实现会记录该事件。可按需覆盖。

        Args:
            request: 数据更新请求
        """
        logger.info("Time series data update received")

    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest):
        """
        外发流量时序数据更新时调用。

        默认实现会记录该事件。可按需覆盖。

        Args:
            request: 外发流量数据更新请求
        """
        logger.info("Outflow time series data update received")

    def on_task_terminate(self, request: SimTaskTerminateRequest):
        """
        收到任务终止请求时调用。

        默认实现会记录终止事件。可覆盖该方法以增加自定义清理逻辑。

        Args:
            request: 任务终止请求
        """
        self.clear_sibling_agent_instances(request.context.biz_scene_instance_id)
        logger.info(f"Task termination requested: {request.reason}")

    def on_monitor_rule_updated(self, request):
        """
        监控规则更新时调用。

        默认实现不执行任何操作。可按需覆盖。

        Args:
            request: 监控规则更新请求
        """
        logger.debug("Monitor rule updated (default handler)")

    def on_device_fault_inject(self, request):
        """
        收到设备故障注入请求时调用。

        默认实现不执行任何操作。可按需覆盖。

        Args:
            request: 故障注入请求
        """
        logger.debug("Device fault inject (default handler)")

    def on_noise_simulation(self, request):
        """
        收到噪声仿真请求时调用。

        默认实现不执行任何操作。可按需覆盖。

        Args:
            request: 噪声仿真请求
        """
        logger.debug("Noise simulation (default handler)")

    def on_identified_param_updated(self, request):
        """
        辨识参数更新时调用。

        默认实现不执行任何操作。可按需覆盖。

        Args:
            request: 参数同步请求
        """
        logger.debug("Identified parameter updated (default handler)")

    def on_outflow_time_series(self, request: OutflowTimeSeriesRequest):
        """
        请求外发流量时序数据时调用。

        默认实现会记录该事件。可按需覆盖。

        Args:
            request: 外发流量时序请求
        """
        logger.debug("Outflow time series request received")
