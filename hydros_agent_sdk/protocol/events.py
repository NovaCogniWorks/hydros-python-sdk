from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Any, Literal, Union
from pydantic import AliasChoices, Field
from .models import SimulationContext, ObjectTimeSeries
from .base import HydroBaseModel

class BaseHydroEvent(HydroBaseModel):
    hydro_event_type: str
    hydro_event_id: Optional[str] = None
    hydro_event_name: Optional[str] = None
    context: Optional[SimulationContext] = None
    created_time: Optional[Any] = None
    auto_schedule_at_step: int = -1
    source_agent_code: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("source_agent_code", "sourceAgentCode"),
        serialization_alias="sourceAgentCode",
    )
    hydro_event_source_type: Optional[str] = None
    hydro_event_source: Optional[str] = None
    hydro_event_description: Optional[str] = None

class HydroEvent(BaseHydroEvent):
    pass

class TimeSeriesDataChangedEvent(HydroEvent):
    hydro_event_type: Union[Literal["TIME_SERIES_DATA_UPDATED"], Literal["TimeSeriesDataChangedEvent"]] = "TIME_SERIES_DATA_UPDATED"
    object_time_series: List[ObjectTimeSeries] = Field(default_factory=list)

class OutflowTimeSeriesDataChangedEvent(HydroEvent):
    hydro_event_type: Literal["OUTFLOW_TIME_SERIES_DATA_UPDATED"] = "OUTFLOW_TIME_SERIES_DATA_UPDATED"
    object_type: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("object_type", "objectType")
    )
    object_time_series: List[ObjectTimeSeries] = Field(
        default_factory=list,
        validation_alias=AliasChoices("object_time_series", "objectTimeSeries")
    )

class OutflowTimeSeriesEvent(HydroEvent):
    hydro_event_type: Literal["OUTFLOW_TIME_SERIES"] = "OUTFLOW_TIME_SERIES"
    event_content_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("event_content_url", "eventContentUrl")
    )
    priority: Optional[str] = None

# Union for polymorphic events if needed later
HydroEventUnion = Union[
    TimeSeriesDataChangedEvent,
    OutflowTimeSeriesDataChangedEvent,
    OutflowTimeSeriesEvent,
    # Add generic HydroEvent as fallback?
    HydroEvent
]

def get_event_type(obj: Any) -> str:
    if isinstance(obj, dict):
        return obj.get("hydro_event_type")
    return getattr(obj, "hydro_event_type", None)
