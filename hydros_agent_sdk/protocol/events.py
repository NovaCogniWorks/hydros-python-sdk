from __future__ import annotations
from typing import List, Optional, Any, Literal, Union
from pydantic import Field
from .models import SimulationContext, ObjectTimeSeries
from .base import HydroBaseModel

class BaseHydroEvent(HydroBaseModel):
    hydro_event_type: str
    hydroEventId: Optional[str] = None
    hydroEventName: Optional[str] = None
    context: Optional[SimulationContext] = None
    createdTime: Optional[Any] = None
    autoScheduleAtStep: int = -1
    hydroEventSourceType: Optional[str] = None
    hydroEventSource: Optional[str] = None
    hydroEventDescription: Optional[str] = None

class HydroEvent(BaseHydroEvent):
    pass

class TimeSeriesDataChangedEvent(HydroEvent):
    hydro_event_type: Literal["HYDRO_EVENT_TIME_SERIES_DATA_UPDATED"] = "HYDRO_EVENT_TIME_SERIES_DATA_UPDATED"
    objectTimeSeries: List[ObjectTimeSeries] = Field(default_factory=list)

# Union for polymorphic events if needed later
HydroEventUnion = Union[
    TimeSeriesDataChangedEvent,
    # Add generic HydroEvent as fallback?
    HydroEvent
]

def get_event_type(obj: Any) -> str:
    if isinstance(obj, dict):
        return obj.get("hydro_event_type")
    return getattr(obj, "hydro_event_type", None)
