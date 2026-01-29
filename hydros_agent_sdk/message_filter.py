"""
Message filtering logic for MQTT command dispatcher.

This module implements message filtering similar to the Java implementation in
SimCoordinationSlave.messageArrived() and AgentCommonService.isActiveToTaskSimCommand().
"""

import logging
from hydros_agent_sdk.protocol.commands import (
    SimCommand,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimCoordinationRequest,
    AgentInstanceStatusReport,
)
from hydros_agent_sdk.state_manager import AgentStateManager

# Backward compatibility alias
AgentContextManager = AgentStateManager

logger = logging.getLogger(__name__)


class MessageFilter:
    """
    Filters incoming MQTT messages based on agent context and message type.

    This implements the filtering logic from Java's:
    - SimCoordinationSlave.messageArrived() (line 241-249)
    - AgentCommonService.isActiveToTaskSimCommand()
    - SimCoordinationSlave.isReceived() (line 286-301)
    """

    def __init__(self, context_manager: AgentStateManager):
        self.context_manager = context_manager

    def is_active_to_task_sim_command(self, sim_command: SimCommand) -> bool:
        """
        Check if the command should be processed based on active contexts.

        This implements the Java logic:
        ```java
        @Override
        public boolean isActiveToTaskSimCommand(SimCommand simCommand) {
            if (simCommand instanceof SimTaskInitRequest) {
                return true;
            }

            if (AgentManager.hasActiveContext(simCommand.getContext())) {
                return true;
            }

            return false;
        }
        ```

        Args:
            sim_command: The command to check

        Returns:
            True if the command should be processed, False if it should be filtered out
        """
        # Always accept task init requests
        if isinstance(sim_command, SimTaskInitRequest):
            logger.debug(f"Accepting SimTaskInitRequest: {sim_command.command_id}")
            return True

        # Check if the command's context is active
        if hasattr(sim_command, 'context') and sim_command.context:
            has_context = self.context_manager.has_active_context(sim_command.context)
            if has_context:
                logger.debug(f"Accepting command {sim_command.command_type} for active context: "
                           f"{sim_command.context.biz_scene_instance_id}")
                return True
            else:
                logger.debug(f"Filtering out command {sim_command.command_type} for inactive context: "
                           f"{sim_command.context.biz_scene_instance_id}")
                return False

        # No context or not active
        logger.debug(f"Filtering out command {sim_command.command_type}: no active context")
        return False

    def is_received(self, sim_command: SimCommand) -> bool:
        """
        Check if a received message should be processed.

        This implements the Java logic from SimCoordinationSlave.isReceived() (line 286-301):
        ```java
        private boolean isReceived(SimCommand simCommand) {
            if (simCommand instanceof SimCoordinationRequest) {
                return true;
            }

            if (simCommand instanceof AgentInstanceStatusReport agentInstanceStatusReport) {
                return agentCommonService.isRemoteAgent(agentInstanceStatusReport.getSourceAgentInstance());
            }

            if (simCommand instanceof SimTaskInitResponse simTaskInitResponse) {
                return agentCommonService.isRemoteAgent(simTaskInitResponse.getSourceAgentInstance());
            }

            return false;
        }
        ```

        Args:
            sim_command: The command to check

        Returns:
            True if the message should be processed, False otherwise
        """
        # Always receive requests
        if isinstance(sim_command, SimCoordinationRequest):
            logger.debug(f"Receiving request: {sim_command.command_type}")
            return True

        # For AgentInstanceStatusReport, only receive from remote agents
        if isinstance(sim_command, AgentInstanceStatusReport):
            is_remote = self.context_manager.is_remote_agent(sim_command.source_agent_instance)
            if is_remote:
                logger.debug(f"Receiving AgentInstanceStatusReport from remote agent: {sim_command.command_type}")
                return True
            else:
                logger.debug(f"Filtering out AgentInstanceStatusReport from local agent: {sim_command.command_type}")
                return False

        # For SimTaskInitResponse, only receive from remote agents
        if isinstance(sim_command, SimTaskInitResponse):
            is_remote = self.context_manager.is_remote_agent(sim_command.source_agent_instance)
            if is_remote:
                logger.debug(f"Receiving SimTaskInitResponse from remote agent: {sim_command.command_type}")
                return True
            else:
                logger.debug(f"Filtering out SimTaskInitResponse from local agent: {sim_command.command_type}")
                return False

        # Default: don't receive other message types
        logger.debug(f"Filtering out message (not in receive list): {sim_command.command_type}")
        return False

    def should_process_message(self, sim_command: SimCommand) -> bool:
        """
        Combined filter: check both active context and receive filters.

        This combines the two filters from Java's messageArrived():
        1. isActiveToTaskSimCommand() - filter by active context
        2. isReceived() - filter by message source

        Args:
            sim_command: The command to check

        Returns:
            True if the message should be processed, False if it should be filtered out
        """
        # First filter: check if active to task
        if not self.is_active_to_task_sim_command(sim_command):
            logger.info(f"Message filtered (inactive context): {sim_command.command_type}, "
                       f"command_id={sim_command.command_id}")
            return False

        # Second filter: check if should be received
        if not self.is_received(sim_command):
            logger.info(f"Message filtered (local source): {sim_command.command_type}, "
                       f"command_id={sim_command.command_id}")
            return False

        # Passed both filters
        logger.debug(f"Message accepted: {sim_command.command_type}, command_id={sim_command.command_id}")
        return True
