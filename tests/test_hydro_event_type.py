from hydros_agent_sdk import AgentEventType
from hydros_agent_sdk.protocol.events import (
    OutflowTimeSeriesDataChangedEvent,
    OutflowTimeSeriesEvent,
    TimeSeriesDataChangedEvent,
)
from hydros_agent_sdk.protocol.hydro_event_type import AgentEventType as ProtocolAgentEventType


def test_agent_event_type_constants_match_java_codes():
    assert AgentEventType.WEATHER_FORECAST == "WEATHER_FORECAST"
    assert AgentEventType.WATER_USE == "WATER_USE"
    assert AgentEventType.PUMP_STATION_POWER_OUTAGE == "PUMP_STATION_POWER_OUTAGE"
    assert AgentEventType.DEVICE_FAULT == "DEVICE_FAULT"
    assert AgentEventType.NOISE_SIMULATION == "NOISE_SIMULATION"
    assert AgentEventType.OUTFLOW_TIME_SERIES == "OUTFLOW_TIME_SERIES"
    assert AgentEventType.DEVICE_STATUS_CHANGE == "DEVICE_STATUS_CHANGE"
    assert AgentEventType.HYDRO_ALERT == "HYDRO_ALERT"
    assert AgentEventType.HYDRO_MONITOR_RULE == "HYDRO_MONITOR_RULE"
    assert AgentEventType.TIME_SERIES_DATA_UPDATED == "TIME_SERIES_DATA_UPDATED"
    assert AgentEventType.OUTFLOW_TIME_SERIES_DATA_UPDATED == "OUTFLOW_TIME_SERIES_DATA_UPDATED"
    assert AgentEventType.STEP_TICK == "STEP_TICK"


def test_protocol_and_top_level_exports_use_same_agent_event_type():
    assert ProtocolAgentEventType is AgentEventType


def test_existing_hydro_events_serialize_agent_event_type_values():
    assert TimeSeriesDataChangedEvent().model_dump()["hydro_event_type"] == "TIME_SERIES_DATA_UPDATED"
    assert (
        TimeSeriesDataChangedEvent(
            hydro_event_type=AgentEventType.TIME_SERIES_DATA_UPDATED
        ).model_dump()["hydro_event_type"]
        == "TIME_SERIES_DATA_UPDATED"
    )
    assert (
        OutflowTimeSeriesDataChangedEvent().model_dump()["hydro_event_type"]
        == "OUTFLOW_TIME_SERIES_DATA_UPDATED"
    )
    assert OutflowTimeSeriesEvent().model_dump()["hydro_event_type"] == "OUTFLOW_TIME_SERIES"
