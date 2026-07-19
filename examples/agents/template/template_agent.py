"""面向 SDK 开发者的最小组合式 Hydros Agent 模板。"""

import logging

from hydros_agent_sdk import CustomAgent, AgentExecutionContext
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskTerminateRequest,
    TickCmdRequest,
)

logger = logging.getLogger(__name__)


class TemplateAgent(CustomAgent):
    """可实际运行的最小时间步驱动 Agent 实现。"""

    def on_init(self, runtime: AgentExecutionContext, request: SimTaskInitRequest) -> None:
        logger.info("Initializing template agent: %s", runtime.agent.agent_id)

    def on_tick(self, runtime: AgentExecutionContext, request: TickCmdRequest) -> None:
        logger.info("Template tick: step=%s, command_id=%s", request.step, request.command_id)

    def on_terminate(self, runtime: AgentExecutionContext, request: SimTaskTerminateRequest) -> None:
        logger.info("Terminating template agent: %s", runtime.agent.agent_id)
