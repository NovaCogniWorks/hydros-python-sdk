"""
Unified state management for multi-task agent services.

This module provides centralized state management for Hydro agent services,
handling simulation contexts, agent instances, and task lifecycle tracking.
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
    Represents the state of a simulation task.

    Tracks task lifecycle, associated agents, and timing information.
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
    Unified state manager for multi-task agent services.

    Manages:
    - Active simulation contexts (multi-task isolation)
    - Agent instances and their lifecycle
    - Task states and transitions
    - Local/remote agent tracking

    This class combines functionality from the original AgentContextManager
    with enhanced task lifecycle tracking and agent instance management.
    """

    def __init__(self):
        # 核心状态
        self._active_contexts: Set[str] = set()  # biz_scene_instance_id set
        self._task_states: Dict[str, TaskState] = {}  # context_id → task state
        self._agent_instances: Dict[str, HydroAgentInstance] = {}  # agent_id → instance
        self._local_agent_instances: Set[str] = set()  # local agent_id set
        self._hydros_cluster_id: Optional[str] = None  # current cluster ID
        self._hydros_node_id: Optional[str] = None  # current node ID
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
        Add a simulation context to the active set.
        Called when a task is initialized.
        """
        if context and context.biz_scene_instance_id:
            with self._lock:
                self._active_contexts.add(context.biz_scene_instance_id)
            logger.info(f"Added active context: {context.biz_scene_instance_id}")

    def remove_active_context(self, context: SimulationContext):
        """
        Remove a simulation context from the active set.
        Called when a task is terminated.
        """
        if context and context.biz_scene_instance_id:
            with self._lock:
                self._active_contexts.discard(context.biz_scene_instance_id)
            logger.info(f"Removed active context: {context.biz_scene_instance_id}")

    def has_active_context(self, context: SimulationContext) -> bool:
        """
        Check if a simulation context is currently active.

        Args:
            context: The simulation context to check

        Returns:
            True if the context is active, False otherwise
        """
        if not context or not context.biz_scene_instance_id:
            return False

        with self._lock:
            is_active = context.biz_scene_instance_id in self._active_contexts
        logger.debug(f"Context {context.biz_scene_instance_id} active: {is_active}")
        return is_active

    def get_active_contexts(self) -> Set[str]:
        """
        Get all active context IDs.

        Returns:
            Set of active biz_scene_instance_id values
        """
        with self._lock:
            return self._active_contexts.copy()

    # ========================================================================
    # 智能体实例管理
    # ========================================================================

    def register_agent_instance(self, agent: HydroAgentInstance):
        """
        Register an agent instance.

        Args:
            agent: The agent instance to register
        """
        if agent and agent.agent_id:
            with self._lock:
                self._agent_instances[agent.agent_id] = agent
            logger.info(f"Registered agent instance: {agent.agent_id}")

    def unregister_agent_instance(self, agent_id: str):
        """
        Unregister an agent instance.

        Args:
            agent_id: The ID of the agent to unregister
        """
        with self._lock:
            if agent_id in self._agent_instances:
                del self._agent_instances[agent_id]
                self._local_agent_instances.discard(agent_id)
                logger.info(f"Unregistered agent instance: {agent_id}")

    def get_agent_instance(self, agent_id: str) -> Optional[HydroAgentInstance]:
        """
        Get an agent instance by ID.

        Args:
            agent_id: The agent ID to look up

        Returns:
            The agent instance if found, None otherwise
        """
        with self._lock:
            return self._agent_instances.get(agent_id)

    def update_agent_status(self, agent_id: str, status: AgentStatus):
        """
        Update the status of an agent instance.

        Args:
            agent_id: The agent ID
            status: The new status
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
        Get the status of an agent instance.

        Args:
            agent_id: The agent ID

        Returns:
            The agent status if found, None otherwise
        """
        with self._lock:
            agent = self._agent_instances.get(agent_id)
            return agent.agent_status if agent else None

    # ========================================================================
    # 本地/远端智能体跟踪（来自 AgentContextManager）
    # ========================================================================

    def add_local_agent(self, agent_instance: HydroAgentInstance):
        """
        Register a local agent instance.

        Args:
            agent_instance: The agent instance to register
        """
        if agent_instance and agent_instance.agent_id:
            with self._lock:
                self._local_agent_instances.add(agent_instance.agent_id)
            logger.info(f"Registered local agent: {agent_instance.agent_id}")

    def remove_local_agent(self, agent_instance: HydroAgentInstance):
        """
        Unregister a local agent instance.

        Args:
            agent_instance: The agent instance to unregister
        """
        if agent_instance and agent_instance.agent_id:
            with self._lock:
                self._local_agent_instances.discard(agent_instance.agent_id)
            logger.info(f"Unregistered local agent: {agent_instance.agent_id}")

    def is_local_agent(self, agent_instance: HydroAgentInstance) -> bool:
        """
        Check if an agent instance is local (running on this node).

        Args:
            agent_instance: The agent instance to check

        Returns:
            True if the agent is local, False otherwise
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
        Check if an agent instance is remote (running on another node).

        Args:
            agent_instance: The agent instance to check

        Returns:
            True if the agent is remote, False otherwise
        """
        if not agent_instance:
            return False

        return not self.is_local_agent(agent_instance)

    # ========================================================================
    # 任务生命周期管理
    # ========================================================================

    def init_task(self, context: SimulationContext, agents: Optional[List[HydroAgentInstance]] = None):
        """
        Initialize a new task.

        Args:
            context: The simulation context for the task
            agents: Optional list of agents associated with this task
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
        Terminate a task.

        Args:
            context: The simulation context for the task
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
        Get the state of a task.

        Args:
            context_id: The context ID (biz_scene_instance_id)

        Returns:
            The task state if found, None otherwise
        """
        with self._lock:
            return self._task_states.get(context_id)

    def get_active_tasks(self) -> List[TaskState]:
        """
        Get all active tasks.

        Returns:
            List of active task states
        """
        with self._lock:
            return [
                task for task in self._task_states.values()
                if task.status == TaskStatus.ACTIVE
            ]

    def get_agents_for_context(self, context_id: str) -> List[HydroAgentInstance]:
        """
        Get all agents associated with a context.

        Args:
            context_id: The context ID (biz_scene_instance_id)

        Returns:
            List of agent instances for the context
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
