import json
from hydros_agent_sdk.protocol.commands import (
    TimeSeriesCalculationRequest, 
    TimeSeriesDataUpdateRequest, 
    SimCommandEnvelope, 
    HydroAgentInstance
)
from hydros_agent_sdk.protocol.events import TimeSeriesDataChangedEvent, HydroEvent
from hydros_agent_sdk.protocol.models import SimulationContext, ObjectTimeSeries, TimeSeriesValue

def test_models():
    # 1. Test TimeSeriesDataUpdateRequest
    print("Testing TimeSeriesDataUpdateRequest...")
    cmd_update = TimeSeriesDataUpdateRequest(
        command_id="cmd_update_1",
        context=SimulationContext(biz_scene_instance_id="scene1", task_id="task1"),
        time_series_data_changed_event=TimeSeriesDataChangedEvent(
            hydro_event_type="HYDRO_EVENT_TIME_SERIES_DATA_UPDATED",
            object_time_series=[
                ObjectTimeSeries(
                    time_series_name="ts1",
                    object_id=101,
                    time_series=[TimeSeriesValue(step=1, value=10.5)]
                )
            ]
        )
    )
    json_update = cmd_update.model_dump_json(by_alias=True) # Important: by_alias=True
    print("Update JSON Payload (Should be snake_case):", json_update)

    # Check if snake_case keys exist
    parsed = json.loads(json_update)
    assert "time_series_data_changed_event" in parsed
    assert "object_time_series" in parsed["time_series_data_changed_event"]

    # Test Deserialization from snake_case
    envelope = SimCommandEnvelope(command=parsed)
    assert isinstance(envelope.command, TimeSeriesDataUpdateRequest)
    print("Update Deserialization OK")

def test_calc_request():
    # 2. Test TimeSeriesCalculationRequest
    print("\nTesting TimeSeriesCalculationRequest...")
    cmd_calc = TimeSeriesCalculationRequest(
        command_id="cmd_calc_1",
        context=SimulationContext(biz_scene_instance_id="scene1"),
        target_agent_instance=HydroAgentInstance(
            agent_id="agent1",
            agent_code="TEST_AGENT",
            agent_type="TEST_TYPE",
            agent_configuration_url="http://test.url/config.yaml",
            biz_scene_instance_id="scene1",
            hydros_cluster_id="cluster1",
            hydros_node_id="node1",
            context=SimulationContext(biz_scene_instance_id="scene1")
        ),
        hydro_event=HydroEvent(hydro_event_type="GENERIC_EVENT")
    )
    json_calc = cmd_calc.model_dump_json(by_alias=True)
    print("Calc JSON Payload (Should be snake_case):", json_calc)

    parsed = json.loads(json_calc)
    assert "target_agent_instance" in parsed

    envelope = SimCommandEnvelope(command=parsed)
    assert isinstance(envelope.command, TimeSeriesCalculationRequest)
    print("Calc Deserialization OK")

if __name__ == "__main__":
    test_models()
    test_calc_request()
