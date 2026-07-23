"""Java ``CommandTypes`` 中 agent-command 子集的 Python 镜像。"""


class AgentCommandCatalog:
    """Agent command 的稳定 type 字面量。"""

    AGTCMD_AGENT_EVENT_REPORT_REQUEST = "agent_event_report_request"
    AGTCMD_AGENT_EVENT_REPORT_RESPONSE = "agent_event_report_response"
    AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST = "update_station_target_value_request"
    AGTCMD_UPDATE_STATION_TARGET_VALUE_RESPONSE = "update_station_target_value_response"
    AGTCMD_REQUEST_RECEIVED_ACK = "request_revived_ack"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return (
            cls.AGTCMD_AGENT_EVENT_REPORT_REQUEST,
            cls.AGTCMD_AGENT_EVENT_REPORT_RESPONSE,
            cls.AGTCMD_UPDATE_STATION_TARGET_VALUE_REQUEST,
            cls.AGTCMD_UPDATE_STATION_TARGET_VALUE_RESPONSE,
            cls.AGTCMD_REQUEST_RECEIVED_ACK,
        )
