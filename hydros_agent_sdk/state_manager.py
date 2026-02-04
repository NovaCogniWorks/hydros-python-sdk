"""
Unified state management for multi-task agent services.

This module provides centralized state management for Hydro agent services,
handling simulation contexts, agent instances, and task lifecycle tracking.
"""

from typing import Optional, Set, Dict, List
from datetime import datetime
from enum import Enum
import logging

from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    HydroAgentInstance,
    AgentBizStatus
)

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task lifecycle status."""
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
        # Core state
        self._active_contexts: Set[str] = set()  # biz_scene_instance_id set
        self._task_states: Dict[str, TaskState] = {}  # context_id → task state
        self._agent_instances: Dict[str, HydroAgentInstance] = {}  # agent_id → instance
        self._local_agent_instances: Set[str] = set()  # local agent_id set
        self._hydros_cluster_id: Optional[str] = None  # current cluster ID
        self._hydros_node_id: Optional[str] = None  # current node ID

    # ========================================================================
    # Cluster and Node Management
    # ========================================================================

    def set_cluster_id(self, cluster_id: str):
        """Set the current cluster ID."""
        self._hydros_cluster_id = cluster_id
        logger.info(f"Cluster ID set to: {cluster_id}")

    def get_cluster_id(self) -> Optional[str]:
        """Get the current cluster ID."""
        return self._hydros_cluster_id

    def set_node_id(self, node_id: str):
        """Set the current node ID."""
        self._hydros_node_id = node_id
        logger.info(f"Node ID set to: {node_id}")

    def get_node_id(self) -> Optional[str]:
        """Get the current node ID."""
        return self._hydros_node_id

    # ========================================================================
    # Context Management (from AgentContextManager)
    # ========================================================================

    def add_active_context(self, context: SimulationContext):
        """
        Add a simulation context to the active set.
        Called when a task is initialized.
        """
        if context and context.biz_scene_instance_id:
            self._active_contexts.add(context.biz_scene_instance_id)
            logger.info(f"Added active context: {context.biz_scene_instance_id}")

    def remove_active_context(self, context: SimulationContext):
        """
        Remove a simulation context from the active set.
        Called when a task is terminated.
        """
        if context and context.biz_scene_instance_id:
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

        is_active = context.biz_scene_instance_id in self._active_contexts
        logger.debug(f"Context {context.biz_scene_instance_id} active: {is_active}")
        return is_active

    def get_active_contexts(self) -> Set[str]:
        """
        Get all active context IDs.

        Returns:
            Set of active biz_scene_instance_id values
        """
        return self._active_contexts.copy()

    # ========================================================================
    # Agent Instance Management
    # ========================================================================

    def register_agent_instance(self, agent: HydroAgentInstance):
        """
        Register an agent instance.

        Args:
            agent: The agent instance to register
        """
        if agent and agent.agent_id:
            self._agent_instances[agent.agent_id] = agent
            logger.info(f"Registered agent instance: {agent.agent_id}")

    def unregister_agent_instance(self, agent_id: str):
        """
        Unregister an agent instance.

        Args:
            agent_id: The ID of the agent to unregister
        """
        if agent_id in self._agent_instances:
            del self._agent_instances[agent_id]
            logger.info(f"Unregistered agent instance: {agent_id}")

    def get_agent_instance(self, agent_id: str) -> Optional[HydroAgentInstance]:
        """
        Get an agent instance by ID.

        Args:
            agent_id: The agent ID to look up

        Returns:
            The agent instance if found, None otherwise
        """
        return self._agent_instances.get(agent_id)

    def update_agent_status(self, agent_id: str, status: AgentBizStatus):
        """
        Update the status of an agent instance.

        Args:
            agent_id: The agent ID
            status: The new status
        """
        agent = self._agent_instances.get(agent_id)
        if agent:
            agent.agent_biz_status = status
            logger.info(f"Updated agent {agent_id} status to: {status}")
        else:
            logger.warning(f"Cannot update status: agent {agent_id} not found")

    def get_agent_status(self, agent_id: str) -> Optional[AgentBizStatus]:
        """
        Get the status of an agent instance.

        Args:
            agent_id: The agent ID

        Returns:
            The agent status if found, None otherwise
        """
        agent = self._agent_instances.get(agent_id)
        return agent.agent_biz_status if agent else None

    # ========================================================================
    # Local/Remote Agent Tracking (from AgentContextManager)
    # ========================================================================

    def add_local_agent(self, agent_instance: HydroAgentInstance):
        """
        Register a local agent instance.

        Args:
            agent_instance: The agent instance to register
        """
        if agent_instance and agent_instance.agent_id:
            self._local_agent_instances.add(agent_instance.agent_id)
            logger.info(f"Registered local agent: {agent_instance.agent_id}")

    def remove_local_agent(self, agent_instance: HydroAgentInstance):
        """
        Unregister a local agent instance.

        Args:
            agent_instance: The agent instance to unregister
        """
        if agent_instance and agent_instance.agent_id:
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

        # Check by agent_id first (explicit registration)
        if agent_instance.agent_id in self._local_agent_instances:
            return True

        # Check by node_id if available (implicit check)
        # Only consider it local if node_id matches AND agent is not explicitly registered as remote
        if self._hydros_node_id and agent_instance.hydros_node_id == self._hydros_node_id:
            # If agent_id is known but not in local set, it's not local
            if agent_instance.agent_id:
                return False
            # If agent_id is unknown, use node_id as fallback
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
    # Task Lifecycle Management
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

        # Create task state
        task_state = TaskState(context_id, agent_ids)
        self._task_states[context_id] = task_state

        # Register agents
        if agents:
            for agent in agents:
                if agent and agent.agent_id:
                    self.register_agent_instance(agent)

        # Add to active contexts
        self.add_active_context(context)

        # Update task status to ACTIVE
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

        # Update task state
        task_state = self._task_states.get(context_id)
        if task_state:
            task_state.status = TaskStatus.TERMINATING
            task_state.terminated_at = datetime.now()

        # Remove from active contexts
        self.remove_active_context(context)

        # Mark task as terminated
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
        return self._task_states.get(context_id)

    def get_active_tasks(self) -> List[TaskState]:
        """
        Get all active tasks.

        Returns:
            List of active task states
        """
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
    # Utility
    # ========================================================================

    def clear(self):
        """Clear all state."""
        self._active_contexts.clear()
        self._task_states.clear()
        self._agent_instances.clear()
        self._local_agent_instances.clear()
        logger.info("Cleared all state (contexts, tasks, agents)")
