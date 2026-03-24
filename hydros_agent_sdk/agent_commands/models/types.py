"""
Agent command type constants.
"""


class AgentCommandTypes:
    """Collect known command type literals in one place."""

    AGTCMD_AGENT_EVENT_REPORT_REQUEST = "agent_event_report_request"
    AGTCMD_AGENT_EVENT_REPORT_RESPONSE = "agent_event_report_response"
    AGTCMD_GATE_OPENING_REQUEST = "direct_gate_opening_request"
    AGTCMD_GATE_OPENING_RESPONSE = "direct_gate_opening_response"
    AGTCMD_DISTURBANCE_NODE_WATER_FLOW_REQUEST = "disturbance_node_water_flow_request"
    AGTCMD_DISTURBANCE_NODE_WATER_FLOW_RESPONSE = "disturbance_node_water_flow_response"
    AGTCMD_UPDATE_TARGET_WATER_LEVEL_REQUEST = "update_target_water_level_request"
    AGTCMD_UPDATE_TARGET_WATER_LEVEL_RESPONSE = "update_target_water_level_response"
    AGTCMD_UPDATE_STATION_TARGET_LEVEL_REQUEST = "update_station_target_level_request"
    AGTCMD_UPDATE_STATION_TARGET_LEVEL_RESPONSE = "update_station_target_level_response"
    AGTCMD_REQUEST_RECEIVED_ACK = "request_revived_ack"


ALL_AGENT_COMMAND_TYPES = (
    AgentCommandTypes.AGTCMD_AGENT_EVENT_REPORT_REQUEST,
    AgentCommandTypes.AGTCMD_AGENT_EVENT_REPORT_RESPONSE,
    AgentCommandTypes.AGTCMD_GATE_OPENING_REQUEST,
    AgentCommandTypes.AGTCMD_GATE_OPENING_RESPONSE,
    AgentCommandTypes.AGTCMD_DISTURBANCE_NODE_WATER_FLOW_REQUEST,
    AgentCommandTypes.AGTCMD_DISTURBANCE_NODE_WATER_FLOW_RESPONSE,
    AgentCommandTypes.AGTCMD_UPDATE_TARGET_WATER_LEVEL_REQUEST,
    AgentCommandTypes.AGTCMD_UPDATE_TARGET_WATER_LEVEL_RESPONSE,
    AgentCommandTypes.AGTCMD_UPDATE_STATION_TARGET_LEVEL_REQUEST,
    AgentCommandTypes.AGTCMD_UPDATE_STATION_TARGET_LEVEL_RESPONSE,
    AgentCommandTypes.AGTCMD_REQUEST_RECEIVED_ACK,
)
