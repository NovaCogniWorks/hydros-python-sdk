from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import Field

from hydros_agent_sdk.contract.v1.common import ObjectTimeSeries, TaskContextRef
from hydros_agent_sdk.protocol.base import HydroBaseModel


class BaseHydroEvent(HydroBaseModel):
    hydro_event_type: str
    hydro_event_id: Optional[str] = None
    hydro_event_name: Optional[str] = None
    context_ref: Optional[TaskContextRef] = None
    created_time: Optional[Any] = None
    auto_schedule_at_step: int = -1
    hydro_event_source_type: Optional[str] = None
    hydro_event_source: Optional[str] = None
    hydro_event_description: Optional[str] = None


class HydroEvent(BaseHydroEvent):
    pass


class TimeSeriesDataChangedEvent(HydroEvent):
    hydro_event_type: Literal["TIME_SERIES_DATA_UPDATED"] = "TIME_SERIES_DATA_UPDATED"
    object_time_series: List[ObjectTimeSeries] = Field(default_factory=list)


HydroEventUnion = Union[
    TimeSeriesDataChangedEvent,
    HydroEvent,
]
