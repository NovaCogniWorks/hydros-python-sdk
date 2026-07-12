"""Agent-command ACK 的运行时构造。"""

from hydros_agent_sdk.protocol.agent_commands import HydroCommandReceivedAckReply
from hydros_agent_sdk.protocol.agent_commands.base import AgentCommandRequest


class AgentCommandAckFactory:
    """按 request 的收发方向构造 ACK DTO。"""

    def build(self, request: AgentCommandRequest) -> HydroCommandReceivedAckReply:
        return HydroCommandReceivedAckReply.from_request(request)
