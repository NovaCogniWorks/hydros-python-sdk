"""
MQTT 指令分派器的消息过滤逻辑。

本模块实现与 Java 侧 SimCoordinationSlave.messageArrived()
和 AgentCommonService.isActiveToTaskSimCommand() 类似的消息过滤。
"""

import logging
from hydros_agent_sdk.protocol.commands import (
    SimCommand,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimCoordinationRequest,
    AgentInstanceStatusReport,
    EdgeControlExecutionReport,
    MpcExecutionStatusReport,
    MpcPredictionResultReport,
)
from hydros_agent_sdk.state_manager import AgentStateManager

logger = logging.getLogger(__name__)


class MessageFilter:
    """
    基于智能体上下文和消息类型过滤传入的 MQTT 消息。

    这里实现 Java 侧如下逻辑：
    - SimCoordinationSlave.messageArrived() (line 241-249)
    - AgentCommonService.isActiveToTaskSimCommand()
    - SimCoordinationSlave.isReceived() (line 286-301)
    """

    def __init__(self, context_manager: AgentStateManager):
        self.context_manager = context_manager

    def is_active_to_task_sim_command(self, sim_command: SimCommand) -> bool:
        """
        根据活跃上下文检查该指令是否应被处理。

        这里实现如下 Java 逻辑：
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
            sim_command: 要检查的指令

        Returns:
            指令应处理时返回 True，应过滤时返回 False
        """
        # 始终接受任务初始化请求
        if isinstance(sim_command, SimTaskInitRequest):
            logger.debug(f"Accepting SimTaskInitRequest: {sim_command.command_id}")
            return True

        # 检查指令上下文是否处于活跃状态
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

        # 没有上下文或上下文不活跃
        logger.debug(f"Filtering out command {sim_command.command_type}: no active context")
        return False

    def is_received(self, sim_command: SimCommand) -> bool:
        """
        检查收到的消息是否应被处理。

        这里实现 SimCoordinationSlave.isReceived() 中的 Java 逻辑（line 286-301）：
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
            sim_command: 要检查的指令

        Returns:
            消息应处理时返回 True，否则返回 False
        """
        # 始终接收请求
        if isinstance(sim_command, SimCoordinationRequest):
            logger.debug(f"Receiving request: {sim_command.command_type}")
            return True

        # 显式报告只接收远端智能体发出的消息
        if isinstance(
            sim_command,
            (AgentInstanceStatusReport, MpcPredictionResultReport, MpcExecutionStatusReport),
        ):
            is_remote = self.context_manager.is_remote_agent(sim_command.source_agent_instance)
            if is_remote:
                logger.debug(f"Receiving report from remote agent: {sim_command.command_type}")
                return True
            else:
                logger.debug(f"Filtering out report from local agent: {sim_command.command_type}")
                return False

        # 任务初始化响应只接收远端智能体发出的消息
        if isinstance(sim_command, SimTaskInitResponse):
            is_remote = self.context_manager.is_remote_agent(sim_command.source_agent_instance)
            if is_remote:
                logger.debug(f"Receiving SimTaskInitResponse from remote agent: {sim_command.command_type}")
                return True
            else:
                logger.debug(f"Filtering out SimTaskInitResponse from local agent: {sim_command.command_type}")
                return False

        # 默认不接收其他消息类型
        logger.debug(f"Filtering out message (not in receive list): {sim_command.command_type}")
        return False

    def should_process_message(self, sim_command: SimCommand) -> bool:
        """
        组合过滤：同时检查活跃上下文过滤和接收过滤。

        这里组合 Java messageArrived() 中的两个过滤：
        1. isActiveToTaskSimCommand() - 按活跃上下文过滤
        2. isReceived() - 按消息来源过滤

        Args:
            sim_command: 要检查的指令

        Returns:
            消息应处理时返回 True，应过滤时返回 False
        """
        # 第一层过滤：检查是否属于活跃任务
        if not self.is_active_to_task_sim_command(sim_command):
            logger.debug(f"Message filtered (inactive context): {sim_command.command_type}, "
                         f"command_id={sim_command.command_id}")
            return False

        if isinstance(sim_command, EdgeControlExecutionReport):
            if not self.context_manager.is_remote_agent(sim_command.source_agent_instance):
                return False
            target = sim_command.target_agent_instance
            return target is None or self.context_manager.is_local_agent(target)

        # 第二层过滤：检查是否应接收
        if not self.is_received(sim_command):
            logger.debug(f"Message filtered (local source): {sim_command.command_type}, "
                         f"command_id={sim_command.command_id}")
            return False

        # 通过两层过滤
        logger.debug(f"Message accepted: {sim_command.command_type}, command_id={sim_command.command_id}")
        return True
