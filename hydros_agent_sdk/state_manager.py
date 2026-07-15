"""
多任务智能体服务的统一状态管理。

本模块为 Hydro 智能体服务提供集中式状态管理，负责仿真上下文、
智能体实例和任务生命周期跟踪。
"""

from typing import Optional, Set, Dict, List
from datetime import datetime
from enum import Enum
import logging
from threading import RLock

from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    HydroAgentInstance,
    AgentStatus
)

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务生命周期状态。"""
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"


class TaskState:
    """
    表示仿真任务状态。

    跟踪任务生命周期、关联智能体和时间信息。
    """

    def __init__(self, context_id: str, agent_ids: Optional[List[str]] = None):
        self.context_id = context_id
        self.status = TaskStatus.INITIALIZING
        self.agent_ids: List[str] = agent_ids or []
        self.created_at = datetime.now()
        self.terminated_at: Optional[datetime] = None

    def __repr__(self):
        return (f"TaskState(context_id={self.context_id}, status={self.status}, "
                f"agents={len(self.agent_ids)}, created_at={self.created_at})")


class AgentStateManager:
    """
    多任务智能体服务的统一状态管理器。

    管理内容：
    - 活跃仿真上下文（用于多任务隔离）
    - 智能体实例及其生命周期
    - 任务状态和状态流转
    - 本地/远端智能体跟踪

    该类整合原 AgentContextManager 的能力，并增强任务生命周期跟踪
    和智能体实例管理。
    """

    def __init__(self):
        # 核心状态
        self._active_contexts: Set[str] = set()  # biz_scene_instance_id 集合
        self._task_states: Dict[str, TaskState] = {}  # context_id → 任务状态
        self._agent_instances: Dict[str, HydroAgentInstance] = {}  # agent_id → 实例
        self._local_agent_instances: Set[str] = set()  # 本地 agent_id 集合
        self._hydros_cluster_id: Optional[str] = None  # 当前集群 ID
        self._hydros_node_id: Optional[str] = None  # 当前节点 ID
        self._lock = RLock()

    # ========================================================================
    # 集群和节点管理
    # ========================================================================

    def set_cluster_id(self, cluster_id: str):
        """设置当前集群 ID。"""
        with self._lock:
            self._hydros_cluster_id = cluster_id
        logger.info(f"Cluster ID set to: {cluster_id}")

    def get_cluster_id(self) -> Optional[str]:
        """获取当前集群 ID。"""
        with self._lock:
            return self._hydros_cluster_id

    def set_node_id(self, node_id: str):
        """设置当前节点 ID。"""
        with self._lock:
            self._hydros_node_id = node_id
        logger.info(f"Node ID set to: {node_id}")

    def get_node_id(self) -> Optional[str]:
        """获取当前节点 ID。"""
        with self._lock:
            return self._hydros_node_id

    # ========================================================================
    # 上下文管理（来自 AgentContextManager）
    # ========================================================================

    def add_active_context(self, context: SimulationContext):
        """
        将仿真上下文加入活跃集合。

        任务初始化时调用。
        """
        if context and context.biz_scene_instance_id:
            with self._lock:
                self._active_contexts.add(context.biz_scene_instance_id)
            logger.info(f"Added active context: {context.biz_scene_instance_id}")

    def remove_active_context(self, context: SimulationContext):
        """
        从活跃集合移除仿真上下文。

        任务终止时调用。
        """
        if context and context.biz_scene_instance_id:
            with self._lock:
                self._active_contexts.discard(context.biz_scene_instance_id)
            logger.info(f"Removed active context: {context.biz_scene_instance_id}")

    def has_active_context(self, context: SimulationContext) -> bool:
        """
        检查仿真上下文当前是否活跃。

        Args:
            context: 要检查的仿真上下文

        Returns:
            上下文活跃时返回 True，否则返回 False
        """
        if not context or not context.biz_scene_instance_id:
            return False

        with self._lock:
            is_active = context.biz_scene_instance_id in self._active_contexts
        logger.debug(f"Context {context.biz_scene_instance_id} active: {is_active}")
        return is_active

    def begin_task_initialization(self, context: SimulationContext):
        """登记任务初始化窗口，但不提前接收普通业务指令。"""
        if not context or not context.biz_scene_instance_id:
            logger.warning("Cannot begin task initialization: invalid context")
            return

        context_id = context.biz_scene_instance_id
        with self._lock:
            task_state = self._task_states.get(context_id)
            if task_state is None or task_state.status == TaskStatus.TERMINATED:
                self._task_states[context_id] = TaskState(context_id)
                logger.info("Task initialization started: %s", context_id)

    def has_initializing_context(self, context: SimulationContext) -> bool:
        """判断任务是否正处于可接收初始化响应、但尚不可处理业务指令的阶段。"""
        if not context or not context.biz_scene_instance_id:
            return False

        with self._lock:
            task_state = self._task_states.get(context.biz_scene_instance_id)
            return task_state is not None and task_state.status == TaskStatus.INITIALIZING

    def cancel_task_initialization(self, context: SimulationContext):
        """清理未成功激活的初始化任务，避免接受迟到的初始化响应。"""
        if not context or not context.biz_scene_instance_id:
            return

        context_id = context.biz_scene_instance_id
        with self._lock:
            task_state = self._task_states.get(context_id)
            if task_state is not None and task_state.status == TaskStatus.INITIALIZING:
                self._task_states.pop(context_id, None)
                logger.info("Task initialization cancelled: %s", context_id)

    def get_active_contexts(self) -> Set[str]:
        """
        获取全部活跃上下文 ID。

        Returns:
            活跃 biz_scene_instance_id 的集合
        """
        with self._lock:
            return self._active_contexts.copy()

    # ========================================================================
    # 智能体实例管理
    # ========================================================================

    def register_agent_instance(self, agent: HydroAgentInstance):
        """
        注册智能体实例。

        Args:
            agent: 要注册的智能体实例
        """
        if agent and agent.agent_id:
            with self._lock:
                self._agent_instances[agent.agent_id] = agent
            logger.info(f"Registered agent instance: {agent.agent_id}")

    def unregister_agent_instance(self, agent_id: str):
        """
        注销智能体实例。

        Args:
            agent_id: 要注销的智能体 ID
        """
        with self._lock:
            if agent_id in self._agent_instances:
                del self._agent_instances[agent_id]
                self._local_agent_instances.discard(agent_id)
                logger.info(f"Unregistered agent instance: {agent_id}")

    def get_agent_instance(self, agent_id: str) -> Optional[HydroAgentInstance]:
        """
        按 ID 获取智能体实例。

        Args:
            agent_id: 要查找的智能体 ID

        Returns:
            找到时返回智能体实例，否则返回 None
        """
        with self._lock:
            return self._agent_instances.get(agent_id)

    def update_agent_status(self, agent_id: str, status: AgentStatus):
        """
        更新智能体实例状态。

        Args:
            agent_id: 智能体 ID
            status: 新状态
        """
        with self._lock:
            agent = self._agent_instances.get(agent_id)
            if agent:
                agent.agent_status = AgentStatus(status)
        if agent:
            logger.info(f"Updated agent {agent_id} status to: {status}")
        else:
            logger.warning(f"Cannot update status: agent {agent_id} not found")

    def get_agent_status(self, agent_id: str) -> Optional[AgentStatus]:
        """
        获取智能体实例状态。

        Args:
            agent_id: 智能体 ID

        Returns:
            找到时返回智能体状态，否则返回 None
        """
        with self._lock:
            agent = self._agent_instances.get(agent_id)
            return agent.agent_status if agent else None

    # ========================================================================
    # 本地/远端智能体跟踪（来自 AgentContextManager）
    # ========================================================================

    def add_local_agent(self, agent_instance: HydroAgentInstance):
        """
        注册本地智能体实例。

        Args:
            agent_instance: 要注册的智能体实例
        """
        if agent_instance and agent_instance.agent_id:
            with self._lock:
                self._local_agent_instances.add(agent_instance.agent_id)
            logger.info(f"Registered local agent: {agent_instance.agent_id}")

    def remove_local_agent(self, agent_instance: HydroAgentInstance):
        """
        注销本地智能体实例。

        Args:
            agent_instance: 要注销的智能体实例
        """
        if agent_instance and agent_instance.agent_id:
            with self._lock:
                self._local_agent_instances.discard(agent_instance.agent_id)
            logger.info(f"Unregistered local agent: {agent_instance.agent_id}")

    def is_local_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """
        检查智能体实例是否为本地实例（运行在当前节点上）。

        Args:
            agent_instance: 要检查的智能体实例

        Returns:
            本地智能体返回 True，否则返回 False
        """
        if not agent_instance:
            return False

        with self._lock:
            # 先按 agent_id 检查（显式注册）
            if agent_instance.agent_id in self._local_agent_instances:
                return True

            # 如果有 node_id，则按 node_id 检查（隐式检查）
            # 只有 node_id 匹配且智能体没有显式注册为远端时，才视为本地
            if self._hydros_node_id and agent_instance.hydros_node_id == self._hydros_node_id:
                # 如果 agent_id 已知但不在本地集合中，则不是本地
                if agent_instance.agent_id:
                    return False
                # 如果 agent_id 未知，则使用 node_id 兜底
                return True

        return False

    def is_remote_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """
        检查智能体实例是否为远端实例（运行在其他节点上）。

        Args:
            agent_instance: 要检查的智能体实例

        Returns:
            远端智能体返回 True，否则返回 False
        """
        if not agent_instance:
            return False

        return not self.is_local_agent(agent_instance)

    # ========================================================================
    # 任务生命周期管理
    # ========================================================================

    def init_task(self, context: SimulationContext, agents: Optional[List[HydroAgentInstance]] = None):
        """
        初始化新任务。

        Args:
            context: 任务对应的仿真上下文
            agents: 与该任务关联的可选智能体列表
        """
        if not context or not context.biz_scene_instance_id:
            logger.warning("Cannot init task: invalid context")
            return

        context_id = context.biz_scene_instance_id
        agent_ids = [agent.agent_id for agent in agents if agent and agent.agent_id] if agents else []

        with self._lock:
            # 创建任务状态
            task_state = TaskState(context_id, agent_ids)
            self._task_states[context_id] = task_state

            # 注册智能体
            if agents:
                for agent in agents:
                    if agent and agent.agent_id:
                        self.register_agent_instance(agent)

            # 加入活跃上下文
            self.add_active_context(context)

            # 将任务状态更新为 ACTIVE
            task_state.status = TaskStatus.ACTIVE

        logger.info(f"Initialized task: {context_id} with {len(agent_ids)} agents")

    def terminate_task(self, context: SimulationContext):
        """
        终止任务。

        Args:
            context: 任务对应的仿真上下文
        """
        if not context or not context.biz_scene_instance_id:
            logger.warning("Cannot terminate task: invalid context")
            return

        context_id = context.biz_scene_instance_id

        with self._lock:
            # 更新任务状态
            task_state = self._task_states.get(context_id)
            if task_state:
                task_state.status = TaskStatus.TERMINATING
                task_state.terminated_at = datetime.now()

            # 从活跃上下文移除
            self.remove_active_context(context)

            # 标记任务已终止
            if task_state:
                task_state.status = TaskStatus.TERMINATED

        logger.info(f"Terminated task: {context_id}")

    def get_task_state(self, context_id: str) -> Optional[TaskState]:
        """
        获取任务状态。

        Args:
            context_id: 上下文 ID（biz_scene_instance_id）

        Returns:
            找到时返回任务状态，否则返回 None
        """
        with self._lock:
            return self._task_states.get(context_id)

    def get_active_tasks(self) -> List[TaskState]:
        """
        获取全部活跃任务。

        Returns:
            活跃任务状态列表
        """
        with self._lock:
            return [
                task for task in self._task_states.values()
                if task.status == TaskStatus.ACTIVE
            ]

    def get_agents_for_context(self, context_id: str) -> List[HydroAgentInstance]:
        """
        获取与指定上下文关联的全部智能体。

        Args:
            context_id: 上下文 ID（biz_scene_instance_id）

        Returns:
            该上下文下的智能体实例列表
        """
        with self._lock:
            task_state = self._task_states.get(context_id)
            if not task_state:
                return []

            agents = []
            for agent_id in task_state.agent_ids:
                agent = self._agent_instances.get(agent_id)
                if agent:
                    agents.append(agent)

            return agents

    # ========================================================================
    # 工具方法
    # ========================================================================

    def clear(self):
        """清空全部状态。"""
        with self._lock:
            self._active_contexts.clear()
            self._task_states.clear()
            self._agent_instances.clear()
            self._local_agent_instances.clear()
        logger.info("Cleared all state (contexts, tasks, agents)")
