"""场景配置模型，供 Python agent 运行时使用。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_snake


class ScenarioConfigBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_snake,
        populate_by_name=True,
        from_attributes=True,
    )


class SimAgentProperties(ScenarioConfigBaseModel):
    """来自业务场景配置的仿真级智能体属性。"""

    model_config = ConfigDict(extra="allow")

    total_steps: Optional[int] = None
    sim_step_size: Optional[int] = None
    output_step_size: Optional[int] = None
    biz_start_time: Optional[str] = None
    roll_steps: Optional[int] = None
    output_future_steps: Optional[int] = None
    step_interval: Optional[int] = None
    properties: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_runtime_options(
        cls,
        runtime_options: Optional["SimulationRuntimeOptions"],
    ) -> Optional["SimAgentProperties"]:
        if runtime_options is None:
            return None

        properties = dict(runtime_options.runtime_properties or {})
        if runtime_options.tick_seconds is not None:
            properties.setdefault("tick_seconds", runtime_options.tick_seconds)

        return cls(
            total_steps=runtime_options.max_steps,
            sim_step_size=runtime_options.tick_seconds,
            output_step_size=runtime_options.output_step_seconds,
            biz_start_time=runtime_options.biz_start_time,
            roll_steps=runtime_options.roll_steps,
            output_future_steps=runtime_options.output_future_steps,
            step_interval=runtime_options.step_delay_ms,
            properties=properties,
        )


class SimulationRuntimeOptions(ScenarioConfigBaseModel):
    """仿真任务运行参数，Python SDK 对齐 Java SimulationRuntimeOptions。"""

    model_config = ConfigDict(extra="allow")

    tick_seconds: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("tick_seconds", "tickSeconds", "sim_step_size", "simStepSize"),
    )
    max_steps: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("max_steps", "maxSteps", "total_steps", "totalSteps"),
    )
    output_step_seconds: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices(
            "output_step_seconds",
            "outputStepSeconds",
            "output_step_size",
            "outputStepSize",
            "output_precision_seconds",
            "outputPrecisionSeconds",
        ),
    )
    biz_start_time: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("biz_start_time", "bizStartTime", "business_start_time", "businessStartTime"),
    )
    step_delay_ms: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("step_delay_ms", "stepDelayMs", "step_interval", "stepInterval"),
    )
    roll_steps: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("roll_steps", "rollSteps"),
    )
    output_future_steps: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("output_future_steps", "outputFutureSteps"),
    )
    runtime_properties: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("runtime_properties", "runtimeProperties", "properties"),
    )

    @classmethod
    def from_sim_agent_properties(
        cls,
        sim_agent_properties: Optional[SimAgentProperties],
    ) -> Optional["SimulationRuntimeOptions"]:
        if sim_agent_properties is None:
            return None

        return cls(
            tick_seconds=sim_agent_properties.sim_step_size,
            max_steps=sim_agent_properties.total_steps,
            output_step_seconds=sim_agent_properties.output_step_size,
            biz_start_time=sim_agent_properties.biz_start_time,
            step_delay_ms=sim_agent_properties.step_interval,
            roll_steps=sim_agent_properties.roll_steps,
            output_future_steps=sim_agent_properties.output_future_steps,
            runtime_properties=dict(sim_agent_properties.properties or {}),
        )

    def merged_with(self, override: Optional["SimulationRuntimeOptions"]) -> "SimulationRuntimeOptions":
        if override is None:
            return self.model_copy(deep=True)

        merged = self.model_copy(deep=True)
        for field_name in (
            "tick_seconds",
            "max_steps",
            "output_step_seconds",
            "biz_start_time",
            "step_delay_ms",
            "roll_steps",
            "output_future_steps",
        ):
            value = getattr(override, field_name)
            if value is not None:
                setattr(merged, field_name, value)

        if override.runtime_properties:
            merged.runtime_properties.update(override.runtime_properties)
        return merged

    def fill_missing_from(self, fallback: Optional["SimulationRuntimeOptions"]) -> "SimulationRuntimeOptions":
        if fallback is None:
            return self

        for field_name in (
            "tick_seconds",
            "max_steps",
            "output_step_seconds",
            "biz_start_time",
            "step_delay_ms",
            "roll_steps",
            "output_future_steps",
        ):
            if getattr(self, field_name) is None:
                setattr(self, field_name, getattr(fallback, field_name))

        for key, value in (fallback.runtime_properties or {}).items():
            self.runtime_properties.setdefault(key, value)
        return self


class BizScenarioConfiguration(ScenarioConfigBaseModel):
    """业务场景配置子集，供 Python SDK 运行时使用。"""

    model_config = ConfigDict(extra="allow")

    hydros_objects_modeling_url: Optional[str] = None
    simulation_runtime_options: Optional[SimulationRuntimeOptions] = Field(
        default=None,
        validation_alias=AliasChoices(
            "simulation_runtime_options",
            "simulationRuntimeOptions",
            "default_simulation_preferences",
            "defaultSimulationPreferences",
        ),
    )
    sim_agent_properties: Optional[SimAgentProperties] = Field(
        default=None,
        validation_alias=AliasChoices("sim_agent_properties", "simAgentProperties"),
    )

    @model_validator(mode="after")
    def normalize_runtime_options(self) -> "BizScenarioConfiguration":
        legacy_runtime_options = SimulationRuntimeOptions.from_sim_agent_properties(self.sim_agent_properties)
        if self.simulation_runtime_options is None:
            self.simulation_runtime_options = legacy_runtime_options
        else:
            self.simulation_runtime_options.fill_missing_from(legacy_runtime_options)

        self.sim_agent_properties = SimAgentProperties.from_runtime_options(self.simulation_runtime_options)
        return self

    def merge_simulation_runtime_options(
        self,
        runtime_options: Optional[SimulationRuntimeOptions],
    ) -> None:
        if runtime_options is None:
            return

        if self.simulation_runtime_options is None:
            self.simulation_runtime_options = runtime_options.model_copy(deep=True)
        else:
            self.simulation_runtime_options = self.simulation_runtime_options.merged_with(runtime_options)
        self.sim_agent_properties = SimAgentProperties.from_runtime_options(self.simulation_runtime_options)
