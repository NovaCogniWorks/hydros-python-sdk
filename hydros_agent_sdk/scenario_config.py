"""Scenario configuration models used by the Python agent runtime."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field

from hydros_agent_sdk.protocol.base import HydroBaseModel


class SimAgentProperties(HydroBaseModel):
    """Simulation-level agent properties from biz scenario configuration."""

    model_config = ConfigDict(extra="allow")

    total_steps: Optional[int] = None
    sim_step_size: Optional[int] = None
    output_step_size: Optional[int] = None
    biz_start_time: Optional[str] = None
    roll_steps: Optional[int] = None
    output_future_steps: Optional[int] = None
    step_interval: Optional[int] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class BizScenarioConfiguration(HydroBaseModel):
    """Subset of biz scenario configuration needed by the Python SDK runtime."""

    model_config = ConfigDict(extra="allow")

    hydros_objects_modeling_url: Optional[str] = None
    sim_agent_properties: Optional[SimAgentProperties] = None
