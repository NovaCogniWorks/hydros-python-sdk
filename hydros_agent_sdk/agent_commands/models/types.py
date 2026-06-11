"""
智能体指令类型常量。
"""


class AgentCommandTypes:
    """把已知的命令类型字面量统一收口到一个地方。"""

    AGTCMD_AGENT_EVENT_REPORT_REQUEST = "agent_event_report_request"
    AGTCMD_AGENT_EVENT_REPORT_RESPONSE = "agent_event_report_response"
    AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST = "update_station_target_value_request"
    AGTCMD_UPDATE_STATION_TARGET_VALUE_RESPONSE = "update_station_target_value_response"
    AGTCMD_REQUEST_RECEIVED_ACK = "request_revived_ack"


ALL_AGENT_COMMAND_TYPES = (
    AgentCommandTypes.AGTCMD_AGENT_EVENT_REPORT_REQUEST,
    AgentCommandTypes.AGTCMD_AGENT_EVENT_REPORT_RESPONSE,
    AgentCommandTypes.AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST,
    AgentCommandTypes.AGTCMD_UPDATE_STATION_TARGET_VALUE_RESPONSE,
    AgentCommandTypes.AGTCMD_REQUEST_RECEIVED_ACK,
)
